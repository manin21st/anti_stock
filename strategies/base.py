from abc import ABC, abstractmethod
import logging
import time
import pandas as pd
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class BaseStrategy(ABC):
    def __init__(self, config, broker, risk, portfolio, market_data, trader):
        self.config = config
        self.broker = broker
        self.risk = risk
        self.portfolio = portfolio
        self.market_data = market_data
        self.trader = trader
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Validate Config immediately
        self.validate_config()
        
        self.enabled = config.get("enabled", True) # 기본값: 활성화
        
        # 공통 캐싱 (Common Caching)
        self.daily_cache = {} # {symbol: {'date': 'YYYYMMDD', 'data': DataFrame}}
        self.last_log_state = {} # {symbol: 'state_string'}
        
        # [Day Trading Rule] 당일 손절 종목 재진입 금지 목록
        # 변경: set -> dict {symbol: date_str}
        # 날짜를 확인하여 하루가 지나면 자동 해제되도록 함.
        self.stopped_out_symbols = {}
        
        # 날짜 변경 감지용 (초기값: 현재 날짜)
        self._current_trading_date = time.strftime("%Y%m%d")

    def validate_config(self):
        """
        [설정 검증]
        필수 설정 키가 모두 존재하는지 확인합니다.
        각 전략 클래스는 'REQUIRED_KEYS' 리스트를 클래스 속성으로 정의해야 합니다.
        """
        required_keys = getattr(self, "REQUIRED_KEYS", [])
        missing_keys = [key for key in required_keys if key not in self.config]
        
        if missing_keys:
            error_msg = f"[{self.__class__.__name__}] 설정 오류: 필수 파라미터 누락 {missing_keys}"
            self.logger.error(error_msg)
            raise ValueError(error_msg)
            
    def update_config(self, new_config):
        """동적으로 설정을 업데이트합니다."""
        self.config.update(new_config)
        try:
            self.validate_config()
        except ValueError as e:
            self.logger.error(f"Config update rejected: {e}")
            # 업데이트가 실패했을 때의 처리는 현재 단순 로깅만 수행.
            # dict.update는 이미 적용되었으므로 롤백 로직이 필요할 수 있으나,
            # 현재는 에러만 기록합니다.
            pass
            
        self.enabled = self.config.get("enabled", True)
        self.logger.info(f"Config updated. Enabled: {self.enabled}")

    def on_bar(self, symbol: str, bar: Dict):
        """
        [표준 인터페이스]
        실시간 데이터(on_market_data) 및 백테스터에서 공통으로 호출하는 진입점입니다.
        preprocessing()을 거쳐 execute()를 실행합니다.
        """
        if not self.preprocessing(symbol, bar):
            return None
        return self.execute(symbol, bar)

    # --- Interface for Child Classes ---
    
    @abstractmethod
    def execute(self, symbol, bar):
        """
        [전략 핵심 로직]
        자식 전략 클래스에서 반드시 구현해야 합니다.
        preprocessing()이 True를 반환한 경우에만 호출됩니다. (진입 조건 판단)
        """
        pass

    def _check_new_day(self):
        """날짜가 변경되었는지 확인하고, 일일 초기화 작업을 수행합니다."""
        now_date = time.strftime("%Y%m%d")
        if self._current_trading_date != now_date:
            self.logger.info(f"[일일 초기화] 날짜 변경 감지 ({self._current_trading_date} -> {now_date})")
            
            # 1. 중복 로그 상태 초기화 (새로운 날에는 다시 안내)
            self.last_log_state.clear()
            
            # 2. 오래된 금지 목록 정리
            expired = [s for s, date in self.stopped_out_symbols.items() if date != now_date]
            for s in expired:
                del self.stopped_out_symbols[s]
                
            if expired:
                self.logger.info(f"[일일 초기화] 금지 목록 해제 ({len(expired)}종목): {expired}")

            self._current_trading_date = now_date

    def preprocessing(self, symbol, data) -> bool:
        """
        [게이트키퍼 (Gatekeeper)]
        execute() 실행 여부를 결정하는 전처리 단계입니다.
        
        수행 작업:
        0. 날짜 변경 확인 (New)
        1. 기본 데이터 체크 및 Rate Limit 확인
        2. 당일 손절 종목 재진입 차단 (Cool-down)
        3. 장 운영 시간 확인
        4. 포지션 관리 (청산 - 손절/익절/트레일링)
        5. 일봉 추세 필터링
        
        Returns:
            bool: True면 execute()(진입 로직) 진행, False면 건너뜀.
        """
        # 0. 날짜 변경 체크
        self._check_new_day()

        # 1. 기본 데이터 체크 및 Rate Limit
        if not data: return False
        
        # [Cool-down] 당일 손절 종목 재진입 방지
        # manage_position에서 손절매 발생 시 이 목록에 추가됨
        stop_date = self.stopped_out_symbols.get(symbol)
        if stop_date:
            if stop_date == self._current_trading_date:
                # 당일 차단된 종목
                return False
            else:
                # 날짜 지났으면 해제 (Safety net, _check_new_day에서도 처리하지만 즉시성을 위해)
                del self.stopped_out_symbols[symbol]

        if not self.check_rate_limit(symbol, interval_seconds=5):
            return False
            
        current_time = data.get('time', '')
        if not self.can_enter_market(current_time):
             return False

        # 데이터 준비
        current_price = data.get('close') or data.get('price', 0.0)
        stock_name = self.market_data.get_stock_name(symbol)
        position = self.portfolio.get_position(symbol)

        # 2. 포지션 관리 (청산)
        # 포지션이 있다면 청산 시그널을 먼저 확인합니다.
        if position:
            self.manage_position(position, symbol, stock_name, current_price)
            # 정책: 포지션이 있어도(또는 방금 일부 청산했어도) 추가 진입(불타기/분할매수) 가능성을 위해 
            # 진입 로직(execute)으로 진행을 허용합니다. (단, 손절 시에는 재진입 차단됨)

        # 3. 일봉 추세 필터
        if self.check_daily_trend(symbol, stock_name) is None:
            return False

        return True

    def calculate_buy_quantity(self, symbol: str, current_price: float) -> int:
        """
        리스크 관리 및 목표 비중 로직에 따라 매수 수량을 계산합니다.
        신규 진입 및 분할 매수(불타기) 시 모두 사용됩니다.
        """
        if current_price <= 0:
            return 0

        # 1. 기본 리스크 관리 (Step Size)
        # 총 자산의 risk_pct(예: 3%) 만큼을 1회 매수 기준으로 삼습니다.
        risk_pct = self.config.get("risk_pct", 0.03)
        
        # [성과 기반 가중치 적용] 수익이 잘 났던 종목은 더 크게, 손실 난 종목은 작게.
        perf_weight = self.get_performance_weight(symbol)
        adjusted_risk_pct = risk_pct * perf_weight
        
        self.logger.info(f"[비중 계산] {symbol} | 성과 가중치: {perf_weight}x (최종 리스크: {adjusted_risk_pct*100:.1f}%)")

        risk_step_qty = self.calc_position_size(symbol, risk_pct=adjusted_risk_pct)
        
        # 2. 목표 비중 관리 (Target Weight Logic)
        # 종목당 최대 비중(예: 10%)을 설정합니다.
        # target_weight가 없으면 risk_pct 기준 수량을 그대로 반환합니다.
        target_weight = self.config.get("target_weight", 0.0) 
        
        if target_weight <= 0:
            # 목표 비중이 없으면 단순히 성과 가중치가 반영된 1회 매수량 반환
            return risk_step_qty

        # 부족분(Deficit) 계산
        total_equity = self.portfolio.get_account_value()
        target_val = total_equity * target_weight
        
        current_qty = 0
        position = self.portfolio.get_position(symbol)
        if position:
            current_qty = position.qty
            
        current_val = current_qty * current_price
        deficit_val = target_val - current_val
        
        if deficit_val <= 0:
            # 이미 목표 비중을 채웠거나 초과함
            return 0
            
        # 금액을 수량으로 환산
        deficit_qty = int(deficit_val // current_price)
        
        # 3. 최종 수량 결정
        # '1회 매수량'과 '남은 한도' 중 작은 값을 선택합니다. (한 번에 너무 많이 사지 않도록)
        buy_qty = min(risk_step_qty, deficit_qty)
        
        # 로깅 컨텍스트
        if buy_qty > 0:
            # 추가 매수(불타기)인 경우 로그로 상황을 남깁니다.
            if current_qty > 0:
                self.logger.info(f"[비중 조절] {symbol} | 목표부족: {deficit_val:,.0f}원({deficit_qty}주) | 매수진행: {buy_qty}주")
        
        return buy_qty

    def calc_position_size(self, symbol, risk_pct=None):
        """리스크 비율(%)에 따른 포지션 크기(수량) 계산"""
        account_value = self.portfolio.get_account_value()
        if risk_pct is None:
            risk_pct = self.config.get("risk_pct", 0.03) # 기본 3%

        alloc = account_value * risk_pct
        price = self.market_data.get_last_price(symbol)
        
        if price <= 0:
            return 0
            
        qty = int(alloc // price)
        return max(qty, 0)

    def check_rate_limit(self, symbol: str, interval_seconds: int = 5) -> bool:
        """
        API 호출 빈도 제한을 확인합니다.
        Returns:
            True: 진행 가능, False: 제한 걸림(스킵)
        """
        # 1. 시뮬레이션 모드는 패스
        if self.config.get("is_simulation", False):
            return True
            
        # 2. 실시간 제한 확인
        now = time.time()
        if not hasattr(self, "_last_analysis_time"):
            self._last_analysis_time = {}
            
        if now - self._last_analysis_time.get(symbol, 0) < interval_seconds:
            return False
            
        self._last_analysis_time[symbol] = now
        return True

    def can_enter_market(self, current_time_str: str = None) -> bool:
        """
        설정된 '장 시작 시간'(entry_start_time) 이후인지 확인합니다.
        초반 변동성을 피하기 위해 사용됩니다.
        """
        if not current_time_str:
            return True
            
        start_time_raw = self.config.get("entry_start_time", "090000")
        
        # Defensive Type Conversion & Padding
        start_time = str(start_time_raw).zfill(6)

        if current_time_str < start_time:
            # Silent reject or debug log?
            return False
            
        return True

    # --- Common Logic Extensions ---

    def check_daily_trend(self, symbol, stock_name):
        """
        [공통 필터] 일봉 추세(MA20, 거래량)를 확인합니다.
        Returns:
            DataFrame: 조건 만족 시 일봉 데이터 반환
            None: 조건 불만족 시
        """
        daily = self.get_daily_data(symbol)
        if daily is None: return None

        # 일봉 추세 필터 (MA20)
        # 백테스트 시 데이터가 부족할 경우(20일 미만) 시뮬레이션을 위해 유연하게 대응
        is_sim = self.config.get("is_simulation", False)
        min_bars = 2 if is_sim else 20
        
        if len(daily) < min_bars:
            if is_sim:
                self.logger.debug(f"[시뮬레이션] {symbol} 일봉 데이터 부족 ({len(daily)}개), 필터 통과 처리")
                return daily
            return None

        # 가용한 데이터 범위 내에서 MA 계산
        win_size = min(20, len(daily))
        ma20_now = daily.close.iloc[-win_size:].mean()
        ma20_prev = daily.close.iloc[-(win_size+1):-1].mean() if len(daily) > win_size else ma20_now
        curr_close = daily.close.iloc[-1]

        if curr_close < ma20_now:
            self.log_state_once(symbol, f"[감시 제외] {stock_name} | 하락 추세 (주가 < 20일선)")
            return None
            
        if ma20_now < ma20_prev:
            self.log_state_once(symbol, f"[감시 제외] {stock_name} | 20일선 하락 중")
            return None

        # 거래량 필터
        defaults = getattr(self, "CONSTANTS", {})
        prev_daily_vol_k = self.config.get("prev_daily_vol_k", defaults.get("prev_daily_vol_k", 1.5))
        
        if len(daily) < 22:
            if is_sim:
                self.logger.debug(f"[시뮬레이션] {symbol} 거래량 데이터 부족, 필터 통과 처리")
                return daily
            return None
            
        prev_vol = daily.volume.iloc[-2]
        prev_avg_vol = daily.volume.iloc[-22:-2].mean()

        if prev_avg_vol > 0 and prev_vol < (prev_avg_vol * prev_daily_vol_k):
             self.log_state_once(symbol, f"[감시 제외] {stock_name} | 전일 거래량 부족")
             if not is_sim: return None # 시뮬레이션에서는 로그만 남기고 일단 진행 (데이터셋 한계 고려)
             
        return daily

    def get_daily_data(self, symbol):
        """
        일봉 데이터를 조회하고 캐싱합니다 (Symbol별 하루 1회 호출).
        """
        today_date = time.strftime("%Y%m%d")
        
        # Check Cache
        cached = self.daily_cache.get(symbol)
        if cached and cached['date'] == today_date:
            return cached['data']
            
        # Fetch from API
        daily = self.market_data.get_bars(symbol, timeframe="1d")
        if daily is None or len(daily) < 22: # Minimum 22 for MA20 calculation
            return None
            
        # Update Cache
        self.daily_cache[symbol] = {'date': today_date, 'data': daily}
        return daily

    def log_state_once(self, symbol, msg):
        """
        상태가 변경되었을 때만 로그를 출력합니다.
        단, 시뮬레이션 모드에서는 모든 진행 상황을 보기 위해 항상 출력할 수 있습니다.
        """
        # [Verification Mode] 시뮬레이션 중에는 항상 출력 (상세 분석용)
        # if self.broker.__class__.__name__ == "SimBroker" or self.config.get("is_simulation"):
        #     self.logger.info(msg)
        #     return

        last_msg = self.last_log_state.get(symbol)
        
        # [User Request] 감시 제외 로그는 중복되어도 계속 표시 (확인용)
        force_log = "[감시 제외]" in msg
        
        if last_msg != msg or force_log:
            self.logger.info(msg)
            self.last_log_state[symbol] = msg
        else:
            self.logger.debug(msg)

    def manage_position(self, position, symbol, stock_name, current_price):
        """
        [공통 청산 관리] 손절(Stop Loss) 및 트레일링 스탑(Trailing Stop)을 처리합니다.
        자식 클래스에서 '부분 익절' 등을 위해 오버라이드하거나 확장할 수 있습니다.
        """
        if current_price <= 0: return

        avg_price = position.avg_price
        pnl_ratio = (current_price - avg_price) / avg_price if avg_price > 0 else 0.0

        # 고점 갱신 (트레일링 스탑용)
        if current_price > position.max_price:
            position.max_price = current_price
            self.portfolio.save_state()

        # 1. 손절매 (Stop Loss) - 필수
        stop_loss_pct = self.config.get("stop_loss_pct")
        if stop_loss_pct and pnl_ratio <= -stop_loss_pct:
            self.logger.info(f"[손절매] {symbol} {stock_name} | 수익률: {pnl_ratio*100:.2f}% | 당일 재진입 금지 처리")
            self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
            
            # [Cool-down] 손절매 발생 종목 기록 -> preprocessing에서 차단
            # 변경: 날짜 정보 포함하여 저장
            self.stopped_out_symbols[symbol] = self._current_trading_date
            return True # Action taken

        # 2. 부분 익절 (Optional - 공통 로직으로 통합됨)
        # 설정(config)를 먼저 확인하고, 없으면 자식 클래스 상수(CONSTANTS) 사용
        defaults = getattr(self, "CONSTANTS", {})
        tp1_pct = self.config.get("take_profit1_pct", defaults.get("take_profit1_pct"))
        
        if tp1_pct and (not position.partial_taken) and pnl_ratio >= tp1_pct:
            # 엣지 케이스: 1주인 경우 절반은 0주 -> 최소 1주 매도 or 전량 매도
            half_qty = position.qty // 2
            sell_qty = half_qty if half_qty > 0 else position.qty
            
            self.logger.info(f"[익절] {symbol} {stock_name} | 수익률: {pnl_ratio*100:.2f}% (1차, {sell_qty}주/50%)")
            self.broker.sell_market(symbol, sell_qty, tag=self.config["id"])
            position.partial_taken = True
            self.portfolio.save_state()
            return True

        # 3. 트레일링 스탑 (Optional)
        trail_stop_pct = self.config.get("trail_stop_pct", defaults.get("trail_stop_pct"))
        trail_act_pct = self.config.get("trail_activation_pct", defaults.get("trail_activation_pct"))
        
        if trail_stop_pct and trail_act_pct:
            activation_price = avg_price * (1 + trail_act_pct)
            
            if position.max_price >= activation_price:
                drawdown = (current_price - position.max_price) / position.max_price
                
                if drawdown <= -trail_stop_pct:
                    if current_price < avg_price: return False # 평단 아래에서는 보류 (선택 사항)
                    self.logger.info(f"[트레일링 스탑] {symbol} {stock_name} | 고점 대비 하락: {drawdown*100:.2f}%")
                    self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
                    return True

        return False # 아무 동작도 하지 않음

    # --- 추가된 전략 고도화 로직 (Trend & Performance) ---

    def get_performance_weight(self, symbol: str) -> float:
        """
        해당 종목의 최근 매매 성과를 분석하여 가중치(0.3 ~ 3.0)를 산출합니다.
        최근 5회의 SELL 이벤트를 분석합니다. (객체 및 딕셔너리 모두 지원)
        """
        try:
            def g(obj, attr, default=None):
                if isinstance(obj, dict): return obj.get(attr, default)
                return getattr(obj, attr, default)

            # 최근 5회의 실현 손익 이벤트 필터링
            history_pool = self.trader.trade_history
            recent_trades = []
            
            for t in history_pool:
                t_symbol = g(t, 'symbol')
                t_side = g(t, 'side')
                t_pnl_pct = g(t, 'pnl_pct')
                
                if t_symbol == symbol and t_side == "SELL" and t_pnl_pct is not None:
                    recent_trades.append(t)
            
            if not recent_trades:
                return 1.0 # 기록 없으면 기본값
                
            # 최근 5건 추출 (이미 역순 정렬되어 있다고 가정 - Trader.trade_history는 prepend함)
            # 단, Backtest history는 append할 수 있으므로 주의 필요. 
            # 일단 최신순으로 정렬 유도.
            # TradeEvent는 timestamp를 가짐.
            history = sorted(recent_trades, key=lambda x: g(x, 'timestamp'), reverse=True)[:5]
            weights = []
            
            for trade in history:
                pnl_pct = g(trade, 'pnl_pct')
                if pnl_pct > 0:
                    # 수익인 경우: 수익률에 비례하여 가중치 (최대 1.5)
                    w = 1.0 + min(pnl_pct / 10.0, 0.5) 
                    weights.append(w)
                else:
                    # 손실인 경우: 손실률에 비례하여 감점 (최소 0.5)
                    w = 1.0 + max(pnl_pct / 10.0, -0.5) 
                    weights.append(w)
            
            avg_w = sum(weights) / len(weights)
            
            # 승률 보너스
            wins = [t for t in history if g(t, 'pnl_pct') > 0]
            win_rate = len(wins) / len(history)
            
            if win_rate >= 0.8: # 승률 80% 이상: 보너스
                avg_w *= 1.5
            elif win_rate <= 0.2: # 승률 20% 이하
                # [기존 로직 제거] 손실 종목 비중 축소 패널티는 RR 필터로 대체하므로 제거함.
                # 단, 우수 종목 가중치는 유지.
                avg_w = 1.0 # 감점 없음
                
            # 최종 범위 제한: 1.0x ~ 3.0x (공격적 세팅, 손실 종목 축소 로직 제거됨)
            final_w = round(min(max(avg_w, 1.0), 3.0), 2)
            
            if final_w > 1.0:
                 self.logger.info(f"[성과 가중치] {symbol} | 최근 {len(history)}회 성과(승률 {win_rate*100:.0f}%) 기반: {final_w}x 비중 확대")
                 
            return final_w
            
        except Exception as e:
            self.logger.error(f"Error calculating performance weight for {symbol}: {e}")
            return 1.0

    def get_cumulative_pnl(self, symbol: str) -> float:
        """
        해당 종목의 누적 손익률(%)을 계산합니다. (전체 이력 기반)
        """
        try:
            def g(obj, attr, default=None):
                if isinstance(obj, dict): return obj.get(attr, default)
                return getattr(obj, attr, default)

            history = [t for t in self.trader.trade_history 
                      if g(t, 'symbol') == symbol and g(t, 'side') == "SELL" and g(t, 'pnl_pct') is not None]
            
            if not history:
                return 0.0
                
            total_pnl = sum([g(t, 'pnl_pct') for t in history])
            return round(total_pnl, 2)
        except Exception as e:
            self.logger.error(f"Error calculating cumulative PnL for {symbol}: {e}")
            return 0.0

    def calculate_rr_ratio(self, symbol: str, current_price: float, bars: pd.DataFrame) -> Dict:
        """
        현재가 기준 예상 손익비(Risk/Reward Ratio)를 계산합니다.
        Target(Reward): 최근 20~60봉 이내의 최고가 (저항대)
        Stop(Risk): 설정된 손절 % 지점
        """
        if current_price <= 0 or bars is None or len(bars) < 20:
            return {"rr_ratio": 0, "reward_pct": 0, "risk_pct": 0}

        # 1. Reward (예상 수익)
        # 최근 60봉(또는 가용 데이터) 중 최고가를 목표가로 설정
        lookback = min(len(bars), 60)
        recent_high = bars.high.iloc[-lookback:].max()
        
        reward_amt = recent_high - current_price
        reward_pct = (reward_amt / current_price) * 100 if current_price > 0 else 0

        # 2. Risk (예상 손실)
        # 기본 설정된 stop_loss_pct 사용
        stop_loss_pct = self.config.get("stop_loss_pct", 0.03) 
        risk_pct = stop_loss_pct * 100
        
        # 3. RR Ratio
        rr_ratio = reward_pct / risk_pct if risk_pct > 0 else 0
        
        return {
            "rr_ratio": round(rr_ratio, 2),
            "reward_pct": round(reward_pct, 2),
            "risk_pct": round(risk_pct, 2),
            "target_price": recent_high
        }

    def calculate_adx(self, bars: pd.DataFrame, period: int = 14) -> float:
        """
        ADX (Average Directional Index)를 계산합니다. (추세 강도 지표)
        참고: 25 이상이면 강한 추세로 간주합니다.
        """
        if len(bars) < period * 2:
            return 0.0
            
        df = bars.copy()
        df['up_move'] = df.high.diff()
        df['down_move'] = df.low.diff().mul(-1)
        
        df['plus_dm'] = 0.0
        df.loc[(df.up_move > df.down_move) & (df.up_move > 0), 'plus_dm'] = df.up_move
        
        df['minus_dm'] = 0.0
        df.loc[(df.down_move > df.up_move) & (df.down_move > 0), 'minus_dm'] = df.down_move
        
        # True Range
        df['tr'] = pd.concat([
            df.high - df.low,
            (df.high - df.close.shift()).abs(),
            (df.low - df.close.shift()).abs()
        ], axis=1).max(axis=1)
        
        # Smoothing (Simple Rolling for efficiency)
        tr_smooth = df.tr.rolling(period).sum()
        plus_dm_smooth = df.plus_dm.rolling(period).sum()
        minus_dm_smooth = df.minus_dm.rolling(period).sum()
        
        df['plus_di'] = 100 * (plus_dm_smooth / tr_smooth)
        df['minus_di'] = 100 * (minus_dm_smooth / tr_smooth)
        
        df['dx'] = 100 * (df.plus_di - df.minus_di).abs() / (df.plus_di + df.minus_di)
        adx = df.dx.rolling(period).mean().iloc[-1]
        
        return round(float(adx), 2) if not pd.isna(adx) else 0.0

    def get_ma_slope(self, bars: pd.DataFrame, ma_period: int = 20, lookback: int = 5) -> float:
        """
        이평선(MA)의 기울기를 계산합니다. (최근 lookback 기간 동안의 변화량)
        기울기가 양수(+)이면 우상향으로 판단합니다.
        """
        if len(bars) < ma_period + lookback:
            return 0.0
            
        ma = bars.close.rolling(ma_period).mean()
        
        # 최근 lookback 기간 동안의 변화율(%) 계산
        curr_ma = ma.iloc[-1]
        prev_ma = ma.iloc[-lookback-1]
        
        if prev_ma <= 0: return 0.0
        
        slope_pct = (curr_ma - prev_ma) / prev_ma * 100
        return round(float(slope_pct), 4)
