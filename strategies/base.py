from abc import ABC, abstractmethod
import logging
import time

logger = logging.getLogger(__name__)

class BaseStrategy(ABC):
    def __init__(self, config, broker, risk, portfolio, market_data):
        self.config = config
        self.broker = broker
        self.risk = risk
        self.portfolio = portfolio
        self.market_data = market_data
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Validate Config immediately
        self.validate_config()
        
        self.enabled = config.get("enabled", True) # 기본값: 활성화
        
        # 공통 캐싱 (Common Caching)
        self.daily_cache = {} # {symbol: {'date': 'YYYYMMDD', 'data': DataFrame}}
        self.last_log_state = {} # {symbol: 'state_string'}
        
        # [Day Trading Rule] 당일 손절 종목 재진입 금지 목록
        # 키: 심볼, 값: 손절 발생한 날짜 (YYYYMMDD) - 나중에 날짜 바뀌면 초기화 로직 추가 가능
        # 현재는 런타임 세션 기준
        self.stopped_out_symbols = set()

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

    # --- Interface for Child Classes ---
    
    @abstractmethod
    def execute(self, symbol, bar):
        """
        [전략 핵심 로직]
        자식 전략 클래스에서 반드시 구현해야 합니다.
        preprocessing()이 True를 반환한 경우에만 호출됩니다. (진입 조건 판단)
        """
        pass

    def preprocessing(self, symbol, data) -> bool:
        """
        [게이트키퍼 (Gatekeeper)]
        execute() 실행 여부를 결정하는 전처리 단계입니다.
        
        수행 작업:
        1. 기본 데이터 체크 및 Rate Limit 확인
        2. 당일 손절 종목 재진입 차단 (Cool-down)
        3. 장 운영 시간 확인
        4. 포지션 관리 (청산 - 손절/익절/트레일링)
        5. 일봉 추세 필터링
        
        Returns:
            bool: True면 execute()(진입 로직) 진행, False면 건너뜀.
        """
        # 1. 기본 데이터 체크 및 Rate Limit
        if not data: return False
        
        # [Cool-down] 당일 손절 종목 재진입 방지
        # manage_position에서 손절매 발생 시 이 목록에 추가됨
        if symbol in self.stopped_out_symbols:
            # 로그 과다 출력을 막기 위해 디버그 레벨로 하거나, 한 번만 출력해야 함.
            return False

        if not self.check_rate_limit(symbol, interval_seconds=5): # 5초 제한 (캔들 지연 방지)
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
        # 일봉 추세가 좋지 않으면 신규 진입을 하지 않습니다.
        # check_daily_trend returns DataFrame or None
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
        risk_step_qty = self.calc_position_size(symbol, risk_pct=self.config.get("risk_pct"))
        
        # 2. 목표 비중 관리 (Target Weight Logic)
        # 종목당 최대 비중(예: 10%)을 설정합니다.
        # target_weight가 없으면 risk_pct 기준 수량을 그대로 반환합니다.
        target_weight = self.config.get("target_weight", 0.0) 
        
        if target_weight <= 0:
            # 목표 비중이 없으면 단순히 1회 매수량 반환
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
        ma20_now = daily.close.iloc[-20:].mean()
        ma20_prev = daily.close.iloc[-21:-1].mean()
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
        
        prev_vol = daily.volume.iloc[-2]
        prev_avg_vol = daily.volume.iloc[-22:-2].mean()

        if prev_avg_vol > 0 and prev_vol < (prev_avg_vol * prev_daily_vol_k):
             self.log_state_once(symbol, f"[감시 제외] {stock_name} | 전일 거래량 부족")
             return None
             
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
        """상태가 변경되었을 때만 로그를 출력합니다."""
        last_msg = self.last_log_state.get(symbol)
        if last_msg != msg:
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
            self.stopped_out_symbols.add(symbol)
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
