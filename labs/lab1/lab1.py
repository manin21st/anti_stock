import time
import sys
import lab1_cond  # [전략 실험실] 조건식 정의 모듈 Import

# Windows 환경에서 한글 출력 깨짐 방지
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

class Investor:
    """
    전략 실험실용 Investor 클래스
    - 초기화 (__init__)
    - 실행 (run)
    - 감시 (watch)
    - 진입 (entry)
    - 청산 (exit)
    """

    def __init__(self):
        print("[시스템] Investor 초기화 중...")
        # 나중에 실제 조건식이나 설정 등을 여기서 로드합니다.
        self.target_universe = ["005930", "000660"]  # 예시: 삼성전자, SK하이닉스
        print("[시스템] 초기화 완료")

    def run(self):
        """
        [2. 실행]
        메인 루프로, watch를 호출하고 제어권을 양보(Yield)합니다.
        """
        print("[시스템] 실행 루프 시작 (run)")
        try:
            while True:
                # 3. 감시 단계 호출
                self.watch()
                
                # Yield: CPU 점유를 낮추고 제어권 양보 (파워빌더 Yield() 유사 효과)
                time.sleep(1) 
        except KeyboardInterrupt:
            print("[시스템] 사용자 중단 요청으로 종료합니다.")

    def watch(self):
        """
        [3. 감시]
        등록된 조건식을 통과한 종목만 선별하여 처리합니다.
        청산(exit) -> 진입(entry) 순서로 호출합니다.
        """
        print("\n--- [3. 감시 단계] ---")
        
        # 전체 대상 종목 순회
        for symbol in self.target_universe:
            # [조건 1] 감시 조건 확인
            if self.check_watch_condition(symbol):
                # 감시 조건을 통과한 경우에만 다음 단계 진행
                
                # 5. 청산 먼저 시도 (보유 중이라면)
                self.exit(symbol)
                
                # 4. 진입 시도
                self.entry(symbol)
            else:
                print(f"[{symbol}] 감시 조건 미달 -> 패스")
            
            # 루프 도중에도 제어권 양보 (화면 갱신 등 필요 시)
            time.sleep(0.1)

    def entry(self, symbol):
        """
        [4. 진입]
        진입 조건식을 확인하고 통과 시 매수(Buy)합니다.
        """
        if self.check_entry_condition(symbol):
            print(f"[{symbol}] 진입 조건 만족 -> [매수 주문] 실행")
            self.buy(symbol)
        else:
            print(f"[{symbol}] 진입 조건 미충족")

    def exit(self, symbol):
        """
        [5. 청산]
        청산 조건식을 확인하고 통과 시 매도(Sell)합니다.
        """
        if self.check_exit_condition(symbol):
            print(f"[{symbol}] 청산 조건 만족 -> [매도 주문] 실행")
            self.sell(symbol)
        else:
            print(f"[{symbol}] 청산 조건 미충족")

    # --- 조건식 및 주문 처리를 위한 메소드들 ---

    def check_watch_condition(self, symbol):
        """감시 조건 확인 (lab1_cond.py 위임)"""
        try:
            return lab1_cond.should_watch(symbol)
        except Exception as e:
            print(f"[{symbol}] 감시 조건 확인 중 오류: {e}")
            return False

    def check_entry_condition(self, symbol):
        """진입 조건 확인 (lab1_cond.py 위임)"""
        try:
            return lab1_cond.should_enter(symbol)
        except Exception as e:
            print(f"[{symbol}] 진입 조건 확인 중 오류: {e}")
            return False

    def check_exit_condition(self, symbol):
        """청산 조건 확인 (lab1_cond.py 위임)"""
        try:
            return lab1_cond.should_exit(symbol)
        except Exception as e:
            print(f"[{symbol}] 청산 조건 확인 중 오류: {e}")
            return False

    def buy(self, symbol):
        """매수 실행"""
        print(f"  >>> {symbol} 매수 완료!")

    def sell(self, symbol):
        """매도 실행"""
        print(f"  >>> {symbol} 매도 완료!")

if __name__ == "__main__":
    # 프로그램 실행 진입점
    investor = Investor()
    investor.run()
