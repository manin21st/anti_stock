import os
import sys
import time
import yaml
import logging
from datetime import datetime
from typing import Dict, List, Optional

from labs.lab1 import lab1_cond, lab1_act

from core.dao import WatchlistDAO
from core.scanner import Scanner
from core.market_data import MarketData
from core.broker import Broker
from core.portfolio import Portfolio
from core.universe import Universe # [추가] 엔진 호환성
from core.config import Config # [추가] 엔진 호환성
from core.trade import Trader
from core.backtester import Backtester
from core import interface as ka
from utils.telegram import TelegramBot # [추가] 알림 발송용

logger = logging.getLogger(__name__)

# Windows 환경에서 한글 출력 깨짐 방지
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

class Investor:
    """
    전략 실험실용 Investor 클래스
    - 1. 초기화 (__init__)
    - 2. 실행 (run)
    - 3. 스캔 (scan)
    - 4. 감시 (watch)
    - 5. 청산 (exit)
    - 6. 진입 (entry)
    """

    def __init__(self, config_path: str = "config/strategies.yaml"):
        """
        [1. 초기화]
        API 인증 및 Scanner, MarketData, Broker 초기화
        """
        logger.info("[시스템] Investor 초기화 중...")
        
        # 1. 설정(Config) 로드
        self.config_actor = Config(strategies_path=config_path)
        self.config = self.config_actor.config
        self.system_config = self.config_actor.get_system_config()

        # 2. API 인증
        env_type = self.system_config.get("env_type", "paper")
        svr = "vps" if env_type == "paper" else "prod"
        
        try:
            ka.auth(svr=svr)
            ka.auth_ws(svr=svr)
            logger.info("[시스템] API 인증 완료")
        except Exception as e:
            logger.error(f"[시스템] API 인증 실패: {e}")

        # 3. Core Components 초기화
        self.market_data = MarketData()
        self.broker = Broker()
        self.portfolio = Portfolio()
        self.scanner = Scanner()
        self.telegram = TelegramBot(self.system_config)
        self.trader = Trader(telegram_bot=self.telegram, env_type=env_type)
        self.universe = Universe(self.system_config, self.market_data, self.scanner, self.portfolio)
        self.backtester = Backtester(self.config, {})
        
        # 텔레그램 초기 알림 (봇 초기화 성공 시)
        if self.telegram:
            logger.info("[시스템] 텔레그램 봇 연결 완료")
            self.telegram.send_system_alert("🚀 <b>System Started</b>\nAnti-Stock Lab1 Engine Initialized.")

        # 4. Event Subscriptions (동기화 핵심)
        # Subscribe to Broker and Portfolio events via Trader
        self.broker.on_order_sent.append(self.trader.record_order_event)
        # Optimistic Update for Portfolio (Buying Power)
        self.broker.on_order_sent.append(lambda x: self.portfolio.on_order_sent(x, self.market_data))
        # Pass market_data dynamically using lambda
        self.portfolio.on_position_change.append(lambda x: self.trader.record_position_event(x, self.market_data))

        self.is_trading = True
        self.strategies = {"lab1": "Active"}
        self.last_sync_time = 0

        try:
             # DB 상호작용을 위해 WatchlistDAO 사용
            self.watchlist_pool = WatchlistDAO.get_all_symbols()
            logger.info(f"[시스템] DB 관심종목 로드 완료: {len(self.watchlist_pool)}개")
        except Exception as e:
            logger.error(f"[시스템] 관심종목 로드 실패: {e}")
            self.watchlist_pool = []

        # 5. 초기 잔고 동기화 (중요: 매수 여력 확보)
        self._sync_balance(notify=False)
            
        # 6. 감시 대상 초기화 (Run 루프에서 갱신됨)
        self.target_universe = []
        
        # [장 운영 시간] 상태 추적용 (None: 초기상태, True: 장중, False: 장외)
        self._last_market_status = None
        
        logger.info("[시스템] 초기화 완료")


    # --- [엔진 호환성] 서버 연동 훅 (Server Hooks) ---
    @property
    def watchlist(self):
        """웹: 감시종목 페이지용"""
        # Lab1은 target_universe를 우선 사용, 없으면 DB 목록
        return self.target_universe if self.target_universe else self.watchlist_pool

    @property
    def trade_history(self):
        """웹: 차트/로그용 Proxy"""
        return self.trader.trade_history

    def update_system_config(self, new_config: Dict):
        """웹: 설정 변경"""
        self.config_actor.update_system_config(new_config)
        self.system_config.update(new_config)
        if hasattr(self, 'telegram'):
            self.telegram.reload_config(self.system_config)

    def update_strategy_config(self, new_config: Dict):
        """웹: 전략 설정"""
        self.config_actor.update_strategy_config(new_config)

    def start_trading(self):
        self.is_trading = True
        if self.telegram: self.telegram.send_system_alert("▶️ 매매 재개")

    def stop_trading(self):
        self.is_trading = False
        if self.telegram: self.telegram.send_system_alert("⏸ 매매 중지")
        
    def restart(self):
        logger.info("[시스템] 재시작 요청됨 (Stub)")
        
    def register_strategy(self, strategy_class, strategy_id: str):
        pass # Stub
    
    def _resolve_strategy_tag(self, symbol: str) -> str:
        """포트폴리오 동기화 시 태그(전략ID) 복구 헬퍼"""
        # Lab1은 단일 전략이므로 기본값 LAB1 반환하되, 거래내역이 있으면 참조
        for event in reversed(self.trader.trade_history):
            if event.symbol == symbol and event.event_type == "ORDER_SUBMITTED":
                 return event.strategy_id
        return "lab1"

    def _sync_balance(self, notify: bool = True):
        """실시간 잔고 동기화 (기본 5초 간격)"""
        now = time.time()
        # notify가 False이면(초기화 등) 시간 체크 없이 강제 수행하거나, 
        # last_sync_time이 0일 때도 통과하므로 그대로 둠
        if (now - self.last_sync_time > 5) or (not notify):
            try:
                balance = self.broker.get_balance()
                if balance:
                    self.portfolio.sync_with_broker(balance, notify=notify, tag_lookup_fn=self._resolve_strategy_tag)
                            
                    # [단순화] Lab1은 WebSocket 폴링을 사용하지 않으므로 무조건 현재가 업데이트 수행
                    for symbol in list(self.portfolio.positions.keys()):
                        price = self.market_data.get_last_price(symbol)
                        if price > 0:
                            self.portfolio.update_market_price(symbol, price)
                self.last_sync_time = now
            except Exception as e:
                logger.error(f"주기적 잔고 동기화 실패: {e}")

    # --- [엔진 호환성] 끝 ---

    def _is_market_open(self) -> bool:
        """
        현재 시간이 장 운영 시간(평일 09:00 ~ 15:30)인지 확인하고 상태 변경 시 로그를 출력합니다.
        단순화를 위해 공휴일 API 체크는 생략하고 요일과 시간만 봅니다.
        """
        now = datetime.now()
        is_open = False
        
        # 1. 주말 체크 (월=0, ... 금=4, 토=5, 일=6)
        if now.weekday() < 5:
            # 2. 시간 체크
            current_time = now.time()
            start_time = now.replace(hour=9, minute=0, second=0, microsecond=0).time()
            end_time = now.replace(hour=15, minute=30, second=0, microsecond=0).time()
            
            if start_time <= current_time <= end_time:
                is_open = True
        
        # 상태 변경 감지 및 로그 출력 (최초 1회 포함)
        if self._last_market_status != is_open:
            if is_open:
                logger.info("▶️ [시스템] 장 운영 시간입니다 (Market Open). 감시를 시작합니다.")
            else:
                logger.info("⏸ [시스템] 장 운영 시간이 아닙니다 (Market Closed). 대기 모드로 전환합니다.")
            
            self._last_market_status = is_open

        return is_open

    def run(self):
        """
        [2. 실행]
        메인 루프로, watch를 호출하고 제어권을 양보(Yield)합니다.
        """
        logger.info("[시스템] 실행 루프 시작 (run)")
        
        tick_count = 0
        scan_interval = 3

        try:
            while True:
                # 0. 장 운영 시간 체크 (상태 변경 로그는 내부에서 처리)
                if not self._is_market_open():
                    time.sleep(30) # 장외 시간 대기
                    continue

                # 종목 스캔 (주기적 실행)
                if tick_count % scan_interval == 0:
                    self.scan()
                
                # 실시간 잔고 동기화 (5초 간격)
                self._sync_balance()

                # 감시 단계 (선정된 target_universe 대상) - 매 루프 실행
                if self.is_trading and self.target_universe:
                    self.watch()
                else:
                    # 로그 소음 방지를 위해 스캔 주기에만 로그 출력
                    if tick_count % scan_interval == 0:
                        logger.info("[시스템] 감시 대상 종목이 없습니다. 대기 중...")
                
                # CPU 점유를 낮추고 제어권 양보
                tick_count += 1
                time.sleep(1) 
        except KeyboardInterrupt:
            logger.info("[시스템] 사용자 중단 요청으로 종료합니다.")

    def scan(self):
        """
        [3. 스캔]
        거래대금 상위 종목 스캔 + 보유 종목 (중복 제거) -> 최종 감시 대상 선정
        """
        try:
            # 1. 거래대금 상위 스캔 (후보군)
            scanned_items = self.scanner.get_trading_value_leaders(limit=50)
            scanned_symbols = {item['symbol'] for item in scanned_items if 'symbol' in item}
            
            # 2. Watchlist 교집합 (관심종목 필터링)
            candidates = set()
            if self.watchlist_pool:
                candidates = set(self.watchlist_pool) & scanned_symbols
            
            # 3. 보유 종목 추가 (강제 감시 대상)
            balance = self.broker.get_balance()
            holdings = balance.get('holdings', [])
            # KIS API 잔고 조회 시 종목코드는 보통 'pdno' 키 사용
            holding_symbols = {h['pdno'] for h in holdings if 'pdno' in h}
            
            # 4. 합집합 도출 (중복 제거)
            final_targets = list(candidates | holding_symbols)
            self.target_universe = final_targets

            # 로깅
            if self.target_universe:
                target_names = [f"{self.market_data.get_stock_name(s)}({s})" for s in self.target_universe]
                logger.info(f"[스캐너] 최종 감시 대상 ({len(self.target_universe)}개): 후보 {len(candidates)}개 + 보유 {len(holding_symbols)}개 -> {target_names}")
            else:
                 if not self.watchlist_pool:
                     logger.warning("[스캐너] 관심종목 Pool이 비어있습니다.")
                 else:
                     logger.info("[스캐너] 감시 대상 없음 (조건 만족 종목 및 보유 종목 없음)")

        except Exception as e:
            logger.error(f"[스캐너] 스캔 중 오류 발생: {e}")
            # 오류 발생 시 이전 target_universe 유지

    def watch(self):
        """
        [4. 감시]
        등록된 조건식을 통과한 종목만 선별하여 처리합니다.
        청산(exit) -> 진입(entry) 순서로 호출합니다.
        """
        # 전체 대상 종목 순회
        # 전체 대상 종목 순회
        for symbol in self.target_universe:
            try:
                # [조건 1] 감시 조건 확인 (lab1_cond.py 위임)
                is_watch_condition_met = lab1_cond.should_watch(symbol, self.market_data)
            except Exception as e:
                logger.error(f"[{symbol}] 감시 조건 확인 중 오류: {e}")
                is_watch_condition_met = False

            if is_watch_condition_met:
                # 감시 조건을 통과한 경우에만 다음 단계 진행
                
                # 5. 청산 먼저 시도 (보유 중이라면)
                self.exit(symbol)
                
                # 6. 진입 시도
                self.entry(symbol)
            else:
                name = self.market_data.get_stock_name(symbol)
                logger.info(f"[{name}({symbol})] 감시 조건 미달 -> 패스")
            
            # 루프 도중에도 제어권 양보 (화면 갱신 등 필요 시)
            time.sleep(0.1)

    def exit(self, symbol):
        """
        [5. 청산]
        청산 조건식을 확인하고 통과 시 매도(Sell)합니다.
        """
        name = self.market_data.get_stock_name(symbol)
        
        try:
             # 청산 조건 확인 (lab1_cond.py 위임) - 결과와 실행 파라미터(dict) 함께 반환
             is_exit_condition_met, action_params = lab1_cond.should_exit(symbol, self.market_data, self.portfolio)
        except Exception as e:
             logger.error(f"[{symbol}] 청산 조건 확인 중 오류: {e}")
             is_exit_condition_met = False
             action_params = {}

        if is_exit_condition_met:
            # Action 파라미터(예: {'qty': 100})를 매도 함수로 전달
            lab1_act.sell(symbol, self.broker, self.portfolio, self.market_data, telegram=self.telegram, **action_params)
        else:
            pass
            # logger.info(f"[{name}({symbol})] 청산 조건 미충족")

    def entry(self, symbol):
        """
        [6. 진입]
        진입 조건식을 확인하고 통과 시 매수(Buy)합니다.
        """
        name = self.market_data.get_stock_name(symbol)
        
        try:
            # 진입 조건 확인 - 결과와 실행 파라미터(dict) 함께 반환
            is_entry_condition_met, action_params = lab1_cond.should_enter(symbol, self.market_data, self.portfolio)
        except Exception as e:
            logger.error(f"[{symbol}] 진입 조건 확인 중 오류: {e}")
            is_entry_condition_met = False
            action_params = {}

        if is_entry_condition_met:
            # Action 파라미터(예: {'target_pct': 10})를 매수 함수로 전달
            lab1_act.buy(symbol, self.broker, self.portfolio, self.market_data, telegram=self.telegram, **action_params)
        else:
            logger.info(f"[{name}({symbol})] 진입 조건 미충족")

# [레거시 별칭]
class Engine(Investor):
    """main.py 호환성을 위한 별칭"""
    pass


