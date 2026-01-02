import time
import logging

logger = logging.getLogger(__name__)

# 인터페이스 호환성을 위한 우선순위 상수
PRIORITY_ORDER = 0
PRIORITY_MANUAL = 1
PRIORITY_ACCOUNT = 2
PRIORITY_DATA = 5
PRIORITY_BACKGROUND = 9

class RateLimiterService:
    """
    [Extremely Minimal Mode]
    모든 요청을 0.5초 대기 후 즉시 실행합니다.
    큐, 리트라이, 분산 제어 로직을 모두 제거했습니다.
    """
    _instance = None
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(RateLimiterService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, tps_limit=2.0, tps_server_url=None):
        if self._initialized: return
        self._initialized = True
        logger.info("[RateLimiter] Minimal mode enabled. Fixed 0.5s interval.")

    def execute(self, func, *args, **kwargs):
        # 우선순위 파라미터가 있으면 제거 (동작에는 영향을 주지 않음)
        kwargs.pop('priority', None)
        
        # 무조건 0.5초 대기
        time.sleep(0.5)
        
        # 즉시 실행 및 결과 반환
        return func(*args, **kwargs)

    def configure(self, *args, **kwargs): pass
    def start(self): pass
    def stop(self): pass
    def get_stats(self):
        return {"mode": "minimal", "status": "active", "fixed_interval": 0.5}

# 싱글톤 인스턴스 (호환성 유지)
params_limiter = RateLimiterService()
