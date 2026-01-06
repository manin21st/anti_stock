import logging
import time
import threading
from typing import Dict, List, Optional
import sys
import os
import uuid

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.market_data import MarketData
from core.broker import Broker
from core.portfolio import Portfolio
from core.risk import Risk
from core.scanner import Scanner
from core.dao import TradeDAO, WatchlistDAO
from utils.telegram import TelegramBot
from core.config import Config
from core.trade import Trader
from core.universe import Universe
from core.backtester import Backtester
from datetime import datetime
from core import interface as ka

logger = logging.getLogger(__name__)

class Engine:
    def __init__(self, config_path: str = "config/strategies.yaml"):
        # 1. Config (기존 ConfigManager)
        self.config_actor = Config(strategies_path=config_path)
        self.config = self.config_actor.config
        self.system_config = self.config_actor.get_system_config()
        
        # 2. Authenticate
        env_type = self.system_config.get("env_type", "paper")
        svr = "vps" if env_type == "paper" else "prod"
        logger.debug(f"Authenticating for {env_type} ({svr})")
        
        try:
            ka.auth(svr=svr)
            ka.auth_ws(svr=svr)
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
        
        # 3. Core Components
        self.market_data = MarketData()
        self.broker = Broker()
        self.portfolio = Portfolio()
        self.risk = Risk(self.portfolio, self.config) # RiskManager -> Risk
        self.scanner = Scanner()
        self.telegram = TelegramBot(self.system_config)
        self.telegram.send_system_alert("🚀 <b>System Started</b>\nAnti-Stock Engine Initialized.")
        
        # 4. Actors (기존 Managers)
        self.trader = Trader(telegram_bot=self.telegram, env_type=env_type) # TradeManager -> Trader
        self.universe = Universe(self.system_config, self.market_data, self.scanner, self.portfolio) # UniverseManager -> Universe
        self.backtester = Backtester(self.config, {}) # strategy_classes will be filled later

        self.strategies = {} # strategy_id -> Strategy Instance
        self.strategy_classes = {} # strategy_id -> Strategy Class
        
        # Link backtester to strategy classes
        self.backtester.strategy_classes = self.strategy_classes

        self.is_running = False
        self.is_trading = False
        self.restart_requested = False
        self.last_sync_time = 0
        self._last_wait_log_time = 0
        self._last_heartbeat_time = 0
        
        # [24/7 최적화] 휴장일 동적 관리를 위한 변수
        self._last_holiday_check_date = ""  # 마지막으로 휴장 여부를 확인한 날짜 (YYYYMMDD)
        self._is_today_holiday = False      # 오늘이 휴장일인지 여부
        self._day_initialized = False       # 새로운 날의 장중 초기화 완료 여부
        
        # Subscribe to market data events
        self.market_data.subscribers.append(self.on_market_data)
        
        # Subscribe to Broker and Portfolio events via Trader
        self.broker.on_order_sent.append(self.trader.record_order_event)
        # Optimistic Update for Portfolio (Buying Power)
        self.broker.on_order_sent.append(lambda x: self.portfolio.on_order_sent(x, self.market_data))
        # Pass market_data dynamically using lambda
        self.portfolio.on_position_change.append(lambda x: self.trader.record_position_event(x, self.market_data))

        # 5. 시스템 사전 준비 (Sync & Load)
        # 웹 서버가 켜지기 전에 데이터를 채워두기 위해 동기식으로 진행합니다.
        self._prepare_system_data()

    def _prepare_system_data(self):
        """프로그램 시작 시 필요한 기초 데이터를 확보합니다 (API 시도 -> 실패 시 로컬 복구)."""
        logger.info("시스템 기초 데이터 준비 중...")
        
        # 1. 초기 잔고 및 포지션 동기화
        try:
            balance = self.broker.get_balance()
            if balance:
                self.portfolio.sync_with_broker(balance, notify=False, tag_lookup_fn=self._resolve_strategy_tag)
                # API 성공 시에도 로컬 상태 세부 정보(tag 등) 보완을 위해 로드 시도 가능
                self.portfolio.load_state() 
                logger.info(f"실시간 잔고 동기화 완료 (자산: {int(self.portfolio.total_asset):,}원)")
            else:
                logger.warning("증권사 잔고 조회 실패. 로컬 장부에서 데이터를 복구합니다.")
                self.portfolio.load_state()
        except Exception as e:
            logger.error(f"초기 잔고 동기화 중 오류 발생: {e}")
            self.portfolio.load_state()

        # 2. 초기 관심종목 캐싱
        target_group = self.system_config.get("watchlist_group_code", "000")
        try:
            self.cached_watchlist = self.scanner.get_watchlist(target_group_code=target_group)
            if self.cached_watchlist:
                logger.info(f"실시간 관심종목 캐싱 완료 ({len(self.cached_watchlist)} 종목)")
            else:
                logger.warning("실시간 관심종목 조회 결과 없음. DB에서 불러옵니다.")
                self.cached_watchlist = []
        except Exception as e:
            logger.warning(f"관심종목 API 조회 실패 ({e}). DB 데이터를 사용합니다.")
            self.cached_watchlist = []

        # 3. 유니버스 점검
        self.universe.load_watchlist()
        logger.info("시스템 기초 준비 완료.")

    def _update_market_status(self, target_date: str):
        """오늘의 휴장 여부를 KIS API를 통해 동적으로 업데이트합니다."""
        logger.info(f"[{target_date}] 시장 운영 상태 확인 중...")
        try:
            holidays = ka.fetch_holiday(target_date)
            if holidays:
                # API 응답 중 오늘(target_date)에 해당하는 정보 찾기
                today_info = next((h for h in holidays if h.get("bass_dt") == target_date), None)
                if today_info:
                    # 'opnd_yn'은 개장 여부, 'tr_day_yn'은 영업일 여부
                    self._is_today_holiday = (today_info.get("opnd_yn") == "N")
                    self._last_holiday_check_date = target_date
                    status_str = "휴장일" if self._is_today_holiday else "영업일"
                    logger.info(f"시장 상태 확인 완료: 오늘은 {status_str}입니다.")
                    return

            # API 응답이 없거나 오늘 정보가 없을 경우 주말 여부로 기본 판단
            dt = datetime.strptime(target_date, "%Y%m%d")
            self._is_today_holiday = (dt.weekday() >= 5)
            self._last_holiday_check_date = target_date
            logger.warning("API 응답 없음. 요일 기반으로 휴장 여부를 추정합니다.")
        except Exception as e:
            logger.error(f"시장 상태 업데이트 중 오류 발생: {e}")
            # 오류 시 주말 여부로 최소한의 방어
            dt = datetime.strptime(target_date, "%Y%m%d")
            self._is_today_holiday = (dt.weekday() >= 5)
            self._last_holiday_check_date = target_date

    @property
    def trade_history(self):
        """Proxy to trader.trade_history for backward compatibility"""
        return self.trader.trade_history

    @property
    def watchlist(self):
        """Proxy to universe.watchlist"""
        return self.universe.watchlist

    def import_broker_watchlist(self):
        """Import watchlist from Broker"""
        return self.universe.import_broker_watchlist()

    def update_watchlist(self, new_list: List[str]):
        """Update entire watchlist"""
        self.universe.update_watchlist(new_list)
        # If trading is active, ensure polling is updated
        if self.is_trading and not self.market_data.is_polling:
             self.market_data.start()

    def update_system_config(self, new_config: Dict):
        """Update system configuration and save to appropriate files"""
        self.config_actor.update_system_config(new_config)
        
        # Reload components
        if hasattr(self, 'telegram'):
            self.telegram.reload_config(self.system_config)
            

    def update_strategy_config(self, new_config: Dict):
        """Update strategy configuration (Config only, applied on restart)"""
        self.config_actor.update_strategy_config(new_config)

    def restart(self):
        """Restart the engine with new settings"""
        logger.info("Restart requested...")
        self.restart_requested = True
        self.is_trading = False
        

    def start_trading(self):
        """Enable trading"""
        self.is_trading = True
        logger.info("Trading started")

    def stop_trading(self):
        """Disable trading"""
        self.is_trading = False
        logger.info("Trading stopped (Standby)")

    def run(self):
        """매매 엔진의 메인 루프입니다. (Blocking)"""
        self.is_running = True
        self.is_trading = True
        
        while self.is_running:
            time.sleep(0.5) # 연결 안정성을 위한 최소 대기
            logger.info("매매 엔진 메인 루프 가동")
            
            # 1. 루프 환경 초기화 (인증, 설정, 전략 인스턴스화)
            self._initialize_loop_context()
            
            # 2. 실시간 거래 루프 (Inner Loop)
            self.restart_requested = False
            self._last_heartbeat_time = time.time()
            
            try:
                while not self.restart_requested and self.is_running:
                    # [긴급] CPU 100% 점유 방지를 위한 1초 대기 (Busy Loop 방지)
                    time.sleep(1)
                    
                    # 3. 장 운영 시간 체크 및 대기 (Gating)
                    if not self._handle_market_gating():
                        continue # 장외 시간일 경우 아래 로직을 실행하지 않고 대기
                        
                    # 4. 주기적 작업 수행 (스캐너, 헬스체크, 잔고 동기화)
                    self._run_periodic_tasks()
            except KeyboardInterrupt:
                self.stop()
                return

            if self.restart_requested:
                logger.info("엔진 재시작 프로세스 진행 중...")
                time.sleep(1)
                continue
            
            if not self.is_running:
                break

    def _initialize_loop_context(self):
        """루프 시작 또는 재시작 시 필요한 환경(인증, 전략, 설정)을 초기화합니다."""
        env_type = self.system_config.get("env_type", "paper")
        svr = "vps" if env_type == "paper" else "prod"
        
        try:
            # 재시작 요청 시 보안을 위해 재인증 수행
            if self.restart_requested:
                logger.debug(f"시스템 재인증 중 ({env_type} / {svr})")
                ka.auth(svr=svr)
                
                # [Environment Hot-Swap Fix]
                # Auth 상태 변경에 따라 Broker와 Trader의 내부 상태도 갱신해야 함
                self.broker.refresh_env()
                self.trader.update_env_type(env_type)
            
            # 설정 및 전략 재로드
            self.strategies.clear()
            self.config_actor.reload()
            self.config = self.config_actor.config
            self.system_config = self.config_actor.get_system_config()
            
            active_strategy_id = self.config.get("active_strategy")
            if active_strategy_id and active_strategy_id in self.strategy_classes:
                # 전략 설정 병합 (공통 + 전략별)
                strategy_config = self.config.get("common", {}).copy()
                strategy_config.update(self.config.get(active_strategy_id, {}))
                strategy_config["id"] = active_strategy_id
                    
                strategy_class = self.strategy_classes[active_strategy_id]
                self.strategies[active_strategy_id] = strategy_class(
                    config=strategy_config,
                    broker=self.broker,
                    risk=self.risk,
                    portfolio=self.portfolio,
                    market_data=self.market_data,
                    trader=self.trader
                )
                logger.debug(f"활성 전략 초기화 완료: {active_strategy_id}")
            else:
                logger.warning(f"활성 전략을 찾을 수 없습니다: {active_strategy_id}")
            
            # 초기 유니버스 설정 (장중일 경우)
            if self._is_trading_hour():
                logger.info("장중 가동: 유니버스 스캔을 즉시 수행합니다.")
                self.universe.update_universe()
            else:
                logger.info("장외 가동: 모니터링을 일시 중단하고 대기합니다.")

        except Exception as e:
            logger.error(f"루프 컨텍스트 초기화 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _handle_market_gating(self) -> bool:
        """장 운영 시간 여부에 따라 시스템 활동을 제어합니다. (True 실행, False 대기)"""
        if not self._is_trading_hour():
            # 장 종료 시 폴링 중단
            if self.market_data.is_polling:
                logger.info("장 운영 시간이 종료되었습니다. 실시간 시세 수집을 중단합니다.")
                self.market_data.stop()
                self._last_wait_log_time = int(time.time())
            
            # 장외 시간 안내 로그 (딱 한 번만 출력하여 로그 소음 방지)
            if self._last_wait_log_time == 0:
                 logger.info("장 운영 시간이 아닙니다. 대기 모드로 전환합니다. (조회 서비스 유지)")
                 self._last_wait_log_time = int(time.time())
            
            return False # 장외이므로 이후 로직 실행 안 함
        
        # --- 장 운영 시간 진입 ---
        if self._last_wait_log_time != 0:
             self._last_wait_log_time = 0

        if self.is_trading and not self.market_data.is_polling:
             # 새로운 영업일 첫 진입 시 유니버스 갱신
             if not self._day_initialized:
                 logger.info("새로운 영업일 장이 시작되었습니다. 유니버스 스캔 수행.")
                 self.universe.update_universe()
                 self._day_initialized = True

             if hasattr(self.market_data, 'polling_symbols') and self.market_data.polling_symbols:
                 logger.info("장 운영 시간입니다. 실시간 감시를 재개합니다.")
                 self.market_data.start()
        
        return True # 장중이므로 로직 계속 실행

    def _run_periodic_tasks(self):
        """주기적으로 수행해야 하는 보조 작업들을 처리합니다."""
        now = time.time()

        # 1. 자동 스캐너 업데이트 (60초 간격)
        if self.system_config.get("use_auto_scanner", False):
            if now - self.universe.last_scan_time > 60:
                self.universe.update_universe()
                if self.is_trading and not self.market_data.is_polling:
                    self.market_data.start()
                
                if hasattr(self.market_data, 'polling_symbols'):
                    symbols = self.market_data.polling_symbols
                    logger.info(f"[감시 업데이트] {len(symbols)}종목: {', '.join(symbols[:10])}...")

        # 2. 시스템 헬스체크 및 상태 요약 (60초 간격)
        if now - self._last_heartbeat_time > 60:
            n_monitoring = len(self.market_data.polling_symbols) if hasattr(self.market_data, 'polling_symbols') else 0
            n_positions = len(self.portfolio.positions)
            total_asset = int(self.portfolio.total_asset)
            logger.info(f"[시스템 정상] 감시: {n_monitoring} | 보유: {n_positions} | 총자산: {total_asset:,}원")
            self._last_heartbeat_time = now

        # 3. 실시간 잔고 동기화 (5초 간격)
        if now - self.last_sync_time > 5:
            try:
                balance = self.broker.get_balance()
                if balance:
                    self.portfolio.sync_with_broker(balance, notify=True, tag_lookup_fn=self._resolve_strategy_tag)
                    
                    # 폴링 중이 아닐 때만 수동으로 현재가 업데이트 (보유 종목 평가용)
                    if not self.market_data.is_polling:
                        for symbol in list(self.portfolio.positions.keys()):
                            price = self.market_data.get_last_price(symbol)
                            if price > 0:
                                self.portfolio.update_market_price(symbol, price)
                self.last_sync_time = now
            except Exception as e:
                logger.error(f"주기적 잔고 동기화 실패: {e}")

    def _is_trading_hour(self) -> bool:
        """현재 시간이 장 운영 시간인지 확인합니다 (휴장일 동적 체크 포함)."""
        if self.config.get("system", {}).get("env_type") == "dev":
            return True
            
        market_type = self.system_config.get("market_type", "KRX")
        now = datetime.now()
        current_date = now.strftime("%Y%m%d")
        
        # [24/7 핵심 로직] 날짜가 바뀌었다면 오늘의 휴장 여부를 새로 확인
        if current_date != self._last_holiday_check_date:
            self._update_market_status(current_date)
            self._day_initialized = False # 새로운 날이 되었으므로 초기화 플래그 리셋
            self._last_wait_log_time = 0   # 새로운 날의 대기 로그를 위해 플래그 리셋

        # 1. 휴장일(공휴일/주말) 체크
        if self._is_today_holiday:
            return False
            
        # 2. 거래 시간 체크
        if market_type == "KRX":
            current_time = now.time()
            start = now.replace(hour=9, minute=0, second=0, microsecond=0).time()
            end = now.replace(hour=15, minute=30, second=0, microsecond=0).time()
            return start <= current_time <= end
        elif market_type == "NXT":
            current_time = now.time()
            start = now.replace(hour=8, minute=0, second=0, microsecond=0).time()
            end = now.replace(hour=20, minute=0, second=0, microsecond=0).time()
            return start <= current_time <= end
            
        return True


    def register_strategy(self, strategy_class, strategy_id: str):
        """Register a strategy class"""
        self.strategy_classes[strategy_id] = strategy_class
        # Also update backtester
        self.backtester.strategy_classes = self.strategy_classes

    def stop(self):
        self.is_running = False
        if self.market_data:
            self.market_data.stop()
        
        # Stop status loop
        self.running = False
        logger.info("Engine stopped")

    def _resolve_strategy_tag(self, symbol: str) -> str:
        """Helper to find the last strategy that traded this symbol from history"""
        for event in reversed(self.trader.trade_history):
            if event.symbol == symbol and event.event_type == "ORDER_SUBMITTED":
                 return event.strategy_id
        return ""

    def on_market_data(self, data: Dict):
        """Handle real-time market data"""
        if not self.is_running:
            return

        if not self._is_trading_hour():
            return

        symbol = data.get("symbol")
        if not symbol:
            return
        
        if not self.is_trading:
            return

        self.portfolio.update_market_price(symbol, data.get("price", 0.0))

        for strategy in self.strategies.values():
            try:
                # [Refactoring] 1. Preprocessing (Gateway)
                # Performs Rate Limit, Time Check, etc.
                if not strategy.preprocessing(symbol, data):
                    continue

                current_price = data.get('price', 0.0)
                bar = {
                    'open': data.get('open', current_price),
                    'high': data.get('high', current_price),
                    'low': data.get('low', current_price),
                    'close': data.get('close', current_price),
                    'volume': data.get('volume', 0),
                    'time': data.get('time', '')
                }
                
                # [Refactoring] 2. Execution (Main Logic)
                strategy.execute(symbol, bar)
                
            except Exception as e:
                logger.error(f"Error in strategy execution: {e}")

    # Delegation methods
    def load_trade_history(self):
        self.trader.load_trade_history()

    def sync_trade_history(self, start_date, end_date):
        return self.trader.sync_trade_history(start_date, end_date)

    def run_backtest(self, strategy_id: str, symbol: str, start_date: str, end_date: str, initial_cash: int = 100000000, strategy_config: Dict = None, progress_callback=None) -> Dict:
        return self.backtester.run_backtest(strategy_id, symbol, start_date, end_date, initial_cash, strategy_config, progress_callback)
