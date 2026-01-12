import time
import sys
import os
import logging

# [Fix] 프로젝트 루트 경로를 가장 먼저 추가해야 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import lab1_cond  # [전략 실험실] 조건식 정의 모듈 Import

from core.dao import WatchlistDAO
from core.scanner import Scanner
from core.market_data import MarketData
from core.broker import Broker
from core.portfolio import Portfolio
from core import interface as ka
import lab1_act # [Refactor] 매매 로직 분리

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

    def __init__(self):
        """
        [1. 초기화]
        API 인증 및 Scanner, MarketData, Broker 초기화
        """
        logger.info("[시스템] Investor 초기화 중...")
        
        # 1. API 인증 (Scanner 사용을 위해 필요)
        try:
            ka.auth(svr='vps') # 모의투자(vps) 환경 인증
            logger.info("[시스템] API 인증 완료 (Mock/VPS)")
        except Exception as e:
            logger.error(f"[시스템] API 인증 실패: {e}")

        # 2. Scanner 및 Watchlist 초기화
        self.scanner = Scanner()
        self.market_data = MarketData() # [수정] MarketData 초기화
        self.broker = Broker() # [추가] 브로커(주문 집행기) 초기화
        self.portfolio = Portfolio() # [추가] 포트폴리오 관리자 (자산/잔고)
        
        try:
            self.watchlist_pool = WatchlistDAO.get_all_symbols()
            logger.info(f"[시스템] DB 관심종목 로드 완료: {len(self.watchlist_pool)}개")
        except Exception as e:
            logger.error(f"[시스템] 관심종목 로드 실패: {e}")
            self.watchlist_pool = []

        # 3. 초기 잔고 동기화 (중요: 매수 여력 확보)
        try:
            balance = self.broker.get_balance()
            if balance:
                self.portfolio.sync_with_broker(balance, notify=False, tag_lookup_fn=lambda x: "LAB1")
                logger.info(f"[시스템] 잔고 동기화 완료 (예수금: {int(self.portfolio.cash):,}원, 총자산: {int(self.portfolio.total_asset):,}원)")
            else:
                logger.warning("[시스템] 잔고 조회 실패 (Mock/API 오류). 자산 0으로 시작합니다.")
        except Exception as e:
            logger.error(f"[시스템] 잔고 동기화 중 오류: {e}")
            
        # 4. 감시 대상 초기화 (Run 루프에서 갱신됨)
        self.target_universe = []
        
        logger.info("[시스템] 초기화 완료")

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
                # 종목 스캔 (주기적 실행)
                if tick_count % scan_interval == 0:
                    self.scan()
                
                # 감시 단계 (선정된 target_universe 대상) - 매 루프 실행
                if self.target_universe:
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
            lab1_act.sell(symbol, self.broker, self.portfolio, self.market_data, **action_params)
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
            lab1_act.buy(symbol, self.broker, self.portfolio, self.market_data, **action_params)
        else:
            logger.info(f"[{name}({symbol})] 진입 조건 미충족")

if __name__ == "__main__":
    # 로그 설정
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 웹 서버 및 브라우저 실행 모듈
    import lab1_web
    lab1_web.start_server_thread(port=8000)
    
    # 프로그램 실행 진입점
    investor = Investor()
    investor.run()
