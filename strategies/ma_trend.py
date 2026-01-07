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

    def on_bar(self, symbol, data):
        """
        [오버라이드] BaseStrategy.on_bar
        백테스트 시표(지표) 기록을 위해, preprocessing 실패 시에도 지표를 계산하여 반환합니다.
        """
        # 1. 지표 우선 계산 (분석)
        stock_name = self.market_data.get_stock_name(symbol)
        bars = self.market_data.get_bars(symbol, timeframe=self.config["timeframe"])
        
        metrics = {}
        if bars is not None and len(bars) >= 20:
             try:
                 metrics = self._decide_and_act(symbol, stock_name, data, dry_run=True)
             except Exception:
                 pass

        # 2. 전처리 (공통 필터 - 매매 제한)
        if not self.preprocessing(symbol, data):
            # 진입 불가하지만 지표는 반환
            if metrics:
                metrics['action'] = "SKIP"
                if not metrics.get('msg'): metrics['msg'] = "[진입 제한] 전처리 필터"
                return metrics
            return None

        # 3. 진입 로직 실행
        return self.execute(symbol, data)

    def execute(self, symbol, data):
        try:
            # 1. 전처리 (공통 필터)
            if not self.preprocessing(symbol, data):
                return None

            # SIM DEBUG
            if self.config.get("is_simulation"):
                pass

            stock_name = self.market_data.get_stock_name(symbol)
            
            # 분봉 시그널 확인 및 매수, 결과 반환
            return self._decide_and_act(symbol, stock_name, data)

        except Exception as e:
            self.logger.error(f"[Error] {symbol} 전략 실행 중 예외 발생: {e}", exc_info=True)
            return None

    def _decide_and_act(self, symbol, stock_name, data, dry_run=False):
        # 데이터 부족 시 조기 리턴
        bars = self.market_data.get_bars(symbol, timeframe=self.config["timeframe"])
        if bars is None or len(bars) < 20: 
            self.log_state_once(symbol, f"[감시 중] {stock_name} | 데이터 수집 중... ({len(bars) if bars is not None else 0}/20)")
            return
            return None
        
        current_price = data.get('close', 0.0)
        
        trend_metrics = self._analyze_trend_metrics(symbol, stock_name, data, bars)
        
        # 4. 결정 로직 (Decision Logic)
        action = "HOLD"
        decision_msg = trend_metrics['msg']
        
        # 진입 조건 충족 여부 확인
        if trend_metrics['is_entry_valid']:
            # 휩쏘 필터 (마지막 관문)
            ma_long = trend_metrics['ma_long']
            whipsaw_threshold = self.config.get("whipsaw_threshold", self.CONSTANTS["whipsaw_threshold"])
            current_close = bars.close.iloc[-1]
            
            if current_close < ma_long * (1 + whipsaw_threshold):
                action = "HOLD"
                decision_msg = f"[진입 보류] {stock_name} | 휩쏘 필터 미달"
            else:
                if not dry_run:
                    action = "BUY"
                    trade_result = self._execute_entry(symbol, stock_name, current_price)
                    if not trade_result:
                         action = "FAIL"
                         decision_msg += " (자산부족/리스크초과)"
                else:
                    action = "BUY (Sim)"

        # 5. Decision Data 구성 (백테스트 로그용)
        # 이 데이터는 BaseStrategy.on_bar -> Backtester 로 전달되어 결과 테이블에 기록됨
        return {
            "adx": trend_metrics['adx'],
            "slope": trend_metrics['slope'],
            "rr_ratio": trend_metrics['rr_ratio'],
            "perf_weight": self.get_performance_weight(symbol), # 재계산(캐시됨)
            "ma_short": trend_metrics['ma_short'],
            "ma_long": trend_metrics['ma_long'],
            "volume": trend_metrics['volume'],
            "avg_vol": trend_metrics['avg_vol'],
            "action": action,
            "msg": decision_msg,
            "is_significant": ("보류" in decision_msg or "시그널" in decision_msg)
        }

    def _analyze_trend_metrics(self, symbol, stock_name, data, bars):
        """진입 판단에 필요한 모든 지표를 계산하고 검증 결과를 반환함"""
        ma_short_win = self.config["ma_short"]
        ma_long_win = self.config["ma_long"]
        
        ma_short_series = bars.close.rolling(ma_short_win).mean()
        ma_long_series = bars.close.rolling(ma_long_win).mean()
        
        ma_short = ma_short_series.iloc[-1]
        ma_long = ma_long_series.iloc[-1]
        
        # 1. 거래량 필터
        volume_now = bars.volume.iloc[-1]
        avg_vol20 = bars.volume.iloc[-20:].mean()
        vol_k = self.config.get("vol_k", self.CONSTANTS["vol_k"])
        vol_ok = volume_now > (avg_vol20 * vol_k)
        
        in_uptrend = ma_short > ma_long
        
        # [User Request] 감시 중 로그 추가 (필터 통과 시)
        # in_uptrend가 True이거나 적어도 하락 추세가 아니면 감시 중으로 표시
        # check_daily_trend를 통과했으므로 여기 왔다는 것은 기본 필터는 통과했다는 뜻임.
        if in_uptrend:
             # 상세 진행 상황
             self.log_state_once(symbol, f"[감시 중] {stock_name} | 상승 추세 (이격 {((ma_short/ma_long)-1)*100:.1f}%) | 거래량 {volume_now/avg_vol20:.1f}x")
        else:
             # 정배열은 아니지만 20일선 위에 있는 경우 등
             self.log_state_once(symbol, f"[감시 중] {stock_name} | 추세 확인 중 (단기 역배열)")
        
        # 2. 고도화 필터 (ADX, Slope)
        adx = self.calculate_adx(bars)
        adx_threshold = self.config.get("adx_threshold", 25)
        adx_ok = adx >= adx_threshold
        
        slope = self.get_ma_slope(bars, ma_period=ma_long_win)
        slope_ok = slope > 0
        
        # 3. 크로스 시그널
        cross_lookback = self.config.get("cross_lookback", self.CONSTANTS["cross_lookback"])
        recent_cross = False
        
        log_msg = f"이평:{'정' if in_uptrend else '역'} ADX:{adx} Slp:{slope:.1f}"
        
        if in_uptrend:
            shorts = ma_short_series.iloc[-(cross_lookback+1):]
            longs = ma_long_series.iloc[-(cross_lookback+1):]
            # 최근 N봉 이내 골든크로스 발생 여부
            if (shorts.iloc[-cross_lookback:] > longs.iloc[-cross_lookback:]).all() and (shorts.iloc[-cross_lookback-1] <= longs.iloc[-cross_lookback-1]):
                 recent_cross = True
                 log_msg = f"[시그널] 골든크로스! ADX:{adx} Slp:{slope:.1f}"

        # 4. RR 및 손실 회복
        rr_info = self.calculate_rr_ratio(symbol, data.get('close', 0), bars)
        rr_ratio = rr_info["rr_ratio"]
        reward_pct = rr_info["reward_pct"]
        cum_pnl = self.get_cumulative_pnl(symbol)
        
        if cum_pnl < 0:
            rr_threshold = 3.0 
            min_reward = abs(cum_pnl) * 0.5
            is_recovery_valid = rr_ratio >= rr_threshold and reward_pct >= min_reward
            log_rr_st = "OK(3.0+)" if is_recovery_valid else f"Fail({rr_ratio}<3.0)"
        else:
            rr_threshold = 2.0
            is_recovery_valid = rr_ratio >= rr_threshold
            log_rr_st = "OK(2.0+)" if is_recovery_valid else f"Fail({rr_ratio}<2.0)"

        if recent_cross and in_uptrend:
             log_msg += f" RR:{log_rr_st}"

        # 최종 진입 가능 여부
        is_valid = recent_cross and in_uptrend and vol_ok and adx_ok and slope_ok and is_recovery_valid
        
        # 보류 사유 상세
        if recent_cross and in_uptrend and not is_valid:
             reasons = []
             if not vol_ok: reasons.append("거래량")
             if not adx_ok: reasons.append(f"ADX")
             if not slope_ok: reasons.append(f"기울기")
             if not is_recovery_valid: reasons.append(f"RR")
             log_msg = f"[진입 보류] 필터미달({', '.join(reasons)})"
             if self.config.get("is_simulation"): # 시뮬레이션에서만 로그 남김 (중복 방지)
                 self.logger.info(f"{stock_name} {log_msg}")

        return {
            'is_entry_valid': is_valid,
            'msg': log_msg,
            'adx': adx,
            'slope': slope,
            'rr_ratio': rr_ratio,
            'ma_long': ma_long,
            'ma_short': ma_short,
            'volume': volume_now,
            'avg_vol': avg_vol20
        }

    # (Original _check_intraday_signal removed)

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
