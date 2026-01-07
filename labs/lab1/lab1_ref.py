"""
[전략 실험실 - 참조 모듈 (Reference Module)]
Core 패키지의 기능을 참조하거나, 실험실 환경에 맞게 래핑(Wrapping)하여 제공하는 역할을 합니다.
"""
import sys
import os
import logging
import logging.config

# --- Core 모듈 참조를 위한 경로 설정 ---
# 현재 파일 위치: c:\DigitalTwin\anti_stock\labs\lab1
# 프로젝트 루트: c:\DigitalTwin\anti_stock
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir)) # labs -> anti_stock

if project_root not in sys.path:
    sys.path.append(project_root)

# 로거 설정
logger = logging.getLogger(__name__)

# --- Core 의존성 Import ---
# 여기서 필요한 Core 모듈을 Import 합니다.
try:
    from core.dao import WatchlistDAO
except ImportError as e:
    logger.error(f"[lab1_ref] Core 모듈 Import 실패: {e}")
    WatchlistDAO = None

def get_watch_list() -> list:
    """
    [Core 참조] DB에 저장된 감시 종목 리스트(Watchlist)를 반환합니다.
    
    Returns:
        list: 종목 코드 리스트 (예: ['005930', '000660'])
    """
    if not WatchlistDAO:
        logger.error("[lab1_ref] WatchlistDAO를 사용할 수 없습니다.")
        return []
    
    try:
        symbols = WatchlistDAO.get_all_symbols()
        logger.info(f"[lab1_ref] 감시 종목 로드 완료: {len(symbols)}개")
        return symbols
    except Exception as e:
        logger.error(f"[lab1_ref] 감시 종목 조회 실패: {e}")
        return []

# 테스트 코드
if __name__ == "__main__":
    # 로그 설정 (테스트 실행 시에만)
    logging.basicConfig(level=logging.INFO)
    
    print("=== lab1_ref.py 테스트 ===")
    watchlist = get_watch_list()
    print(f"가져온 감시 종목: {watchlist}")
