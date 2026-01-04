from .base import BaseStrategy
import pandas as pd
import time

class MovingAverageTrendStrategy(BaseStrategy):
    # 필수 설정 (User Config)
    REQUIRED_KEYS = ['ma_short', 'ma_long', 'stop_loss_pct', 'timeframe']
    
    # 내부 상수 (Internal Constants) - 오버라이드 가능
    CONSTANTS = {
        'vol_k': 1.5,            # 거래량 급증 기준 (배수)
        'prev_daily_vol_k': 1.5, # 전일 대비 거래량 기준
        'cross_lookback': 1,     # 크로스 발생 감지 범위 (캔들 수)
        'whipsaw_threshold': 0.0,# 휩쏘 방지 버퍼 (0.0 = 0%)
        'take_profit1_pct': 0.05,# 1차 익절 (기본 5% - 설정 없을 시) -> REQUIRED로 옮길지 고민 필요하지만, 일단 상수로.
        'trail_stop_pct': 0.03,  # 트레일링 스탑 낙폭
        'trail_activation_pct': 0.03 # 트레일링 스탑 발동 수익률
    }
    
    # *참고: take_profit1_pct 등도 사용자가 자주 바꾸면 REQUIRED로 올리는 게 좋지만, 
    # 일단 기존 코드 흐름 상 Optional하게 처리되던 것들은 상수로 둡니다.
    # 단, 코드 내에서 self.config.get(KEY, CONSTANTS[KEY]) 패턴을 사용해야 함.
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # self.daily_cache & self.last_log_state are now initialized in BaseStrategy

    def execute(self, symbol, data):
        try:
            # 1. 전처리 (공통 필터)
            if not self.preprocessing(symbol, data):
                return

            # SIM DEBUG
            if self.config.get("is_simulation"):
                print(f">>> [EXECUTE] {symbol} {data.get('time')} | Price: {data.get('close')}")

            # Preprocessing에서 이미 [전략 청산]과 [일봉 필터]를 통과함.
            # 여기서는 오직 [진입 시그널]만 확인하고 매수 수행.            
            stock_name = self.market_data.get_stock_name(symbol)
            current_price = data.get('close', 0.0)

            # 분봉 시그널 확인 및 매수
            if self._check_intraday_signal(symbol, stock_name, data):
                self._execute_entry(symbol, stock_name, current_price)

        except Exception as e:
            self.logger.error(f"[Error] {symbol} 전략 실행 중 예외 발생: {e}", exc_info=True)

    def _check_intraday_signal(self, symbol, stock_name, data):
        bars = self.market_data.get_bars(symbol, timeframe=self.config["timeframe"])
        if bars is None or len(bars) < 20: return False

        ma_short_win = self.config["ma_short"]
        ma_long_win = self.config["ma_long"]
        
        ma_short_series = bars.close.rolling(ma_short_win).mean()
        ma_long_series = bars.close.rolling(ma_long_win).mean()
        
        ma_short = ma_short_series.iloc[-1]
        ma_long = ma_long_series.iloc[-1]
        
        volume_now = bars.volume.iloc[-1]
        avg_vol20 = bars.volume.iloc[-20:].mean()
        
        vol_k = self.config.get("vol_k", self.CONSTANTS["vol_k"])
        vol_ok = volume_now > (avg_vol20 * vol_k)
        
        in_uptrend = ma_short > ma_long
        
        # [추세 고도화 필터 1] ADX (추세 강도)
        adx = self.calculate_adx(bars)
        adx_threshold = self.config.get("adx_threshold", 25) # 기본 25: 강한 추세
        adx_ok = adx >= adx_threshold

        # [추세 고도화 필터 2] MA20 기울기
        slope = self.get_ma_slope(bars, ma_period=ma_long_win)
        slope_ok = slope > 0 # 단순 우상향 확인

        # 1. 크로스 확인
        cross_lookback = self.config.get("cross_lookback", self.CONSTANTS["cross_lookback"])
        recent_cross = False
        
        log_msg = f"[감시 중] {stock_name} | 이평선: {'정배열' if in_uptrend else '역배열'} | ADX: {adx} ({'강함' if adx_ok else '약함'}) | 기울기: {slope:.3f}"

        if in_uptrend:
            shorts = ma_short_series.iloc[-(cross_lookback+1):]
            longs = ma_long_series.iloc[-(cross_lookback+1):]
            if (shorts.iloc[-cross_lookback:] > longs.iloc[-cross_lookback:]).all() and (shorts.iloc[-cross_lookback-1] <= longs.iloc[-cross_lookback-1]):
                 recent_cross = True
                 log_msg = f"[시그널 발견] {stock_name} | 골든크로스 발생! | ADX: {adx} | 기울기: {slope:.3f}"
                 if self.config.get("is_simulation"):
                     print(f"!!! [CROSS] {symbol} Golden Cross Triggered at {data.get('time')}")

        # [추세 고도화 필터 3] 손익비(RR Ratio) 및 손실 회복 필터
        rr_info = self.calculate_rr_ratio(symbol, data.get('close', 0), bars)
        rr_ratio = rr_info["rr_ratio"]
        reward_pct = rr_info["reward_pct"]
        
        cum_pnl = self.get_cumulative_pnl(symbol)
        
        # 필터 기준 설정
        if cum_pnl < 0:
            # [복구 모드] 손실 중인 종목: 더 엄격한 기준 적용 (손익비 3.0 이상)
            rr_threshold = 3.0 
            min_reward = abs(cum_pnl) * 0.5 # 과거 손실의 최소 50%는 만회 가능한 파동
            is_recovery_valid = rr_ratio >= rr_threshold and reward_pct >= min_reward
            
            if is_recovery_valid:
                 log_msg += f" | RR: {rr_ratio}(복구가능)"
            else:
                 # 진입 조건(크로스 등)은 맞지만 RR이 안될 때만 상세 로그
                 if recent_cross and in_uptrend:
                     self.logger.info(f"[진입 보류] {stock_name} | 손실 복구 부적합 (RR: {rr_ratio}<3.0 or Reward: {reward_pct}% < 복구기준)")
        else:
            # [표준 모드] 수익 중이거나 신규 종목 (손익비 2.0 이상)
            rr_threshold = 2.0
            is_recovery_valid = rr_ratio >= rr_threshold
            log_msg += f" | RR: {rr_ratio}"
            
            if not is_recovery_valid and recent_cross and in_uptrend:
                 self.logger.info(f"[진입 보류] {stock_name} | 손익비(RR) 부족 (RR: {rr_ratio:.2f} < {rr_threshold})")

        self.log_state_once(symbol, log_msg)

        # 진입 조건: 크로스 + 정배열 + 거래량 + 추세강도 + 우상향 + 손익비(RR)
        if recent_cross and in_uptrend and vol_ok and adx_ok and slope_ok and is_recovery_valid:
            whipsaw_threshold = self.config.get("whipsaw_threshold", self.CONSTANTS["whipsaw_threshold"])
            if bars.close.iloc[-1] < ma_long * (1 + whipsaw_threshold):
                 self.logger.info(f"[진입 보류] {stock_name} | 휩쏘 필터 미달")
                 return False
            return True
            
        return False

    def _execute_entry(self, symbol, stock_name, current_price):
        """매수 주문 실행"""
        # calculate_buy_quantity는 BaseStrategy에 있음 (목표 비중/리스크 관리)
        buy_qty = self.calculate_buy_quantity(symbol, current_price)
        if buy_qty > 0:
            if self.risk.can_open_new_position(symbol, buy_qty, current_price):
                self.logger.info(f"[매수 진입] {symbol} {stock_name} | 수량: {buy_qty} | 가격: {int(current_price):,}")
                self.broker.buy_market(symbol, buy_qty, tag=self.config["id"])
        else:
             self.logger.warning(f"[매수 실패] {symbol} {stock_name} | 자산 부족 또는 리스크 한도 초과 (목표 비중 달성)")
