"""
[전략 실험실 - 조건식 정의 파일]
config/strategies_sandbox.yaml 설정을 읽어 동적으로 판단합니다.
테스트를 위해 가상의 시세 데이터(Mock Data)를 생성하여 사용합니다.
"""
import os
import yaml
import random
import logging

logger = logging.getLogger(__name__)

# 설정 파일 경로 식별 (같은 폴더 내 lab1_cond.yaml)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "lab1_cond.yaml")

# --- 설정 로드 ---
try:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        _yaml_data = yaml.safe_load(f)
    # 최상위 키가 하나라고 가정 (MySandboxStrategy)
    STRATEGY_NAME = list(_yaml_data.keys())[0]
    STRATEGY_CONFIG = _yaml_data[STRATEGY_NAME]
    VARIABLES = STRATEGY_CONFIG.get("variables", {})
    
    logger.info(f"[lab1_cond] '{STRATEGY_NAME}' 설정 로드 완료")
except Exception as e:
    logger.error(f"[lab1_cond] 설정 로드 실패 (기본값 사용): {e}")
    STRATEGY_CONFIG = {}
    VARIABLES = {}

def _get_mock_data(symbol: str) -> dict:
    """
    조건식 평가를 위한 더미 데이터 생성
    YAML의 variables(ma_short 등)와 가상의 시세(price, volume 등)를 합쳐서 반환합니다.
    """
    # 1. 기본 변수 복사
    data = VARIABLES.copy()
    
    # 2. 랜덤 시세 데이터 생성 (테스트용)
    # 가격: 900 ~ 1100 (1000원 기준 동전주 테스트 가능)
    price = random.randint(900, 1100)
    data['price'] = price
    
    # 거래량: 5000 ~ 15000 (10000주 미만 필터 테스트 가능)
    volume = random.randint(5000, 15000)
    data['volume'] = volume
    
    # 전일 거래량 및 평균 거래량 (거래량 급증 테스트용)
    data['prev_volume'] = random.randint(4000, 12000)
    data['avg_volume_long'] = random.randint(5000, 10000)
    
    # 이동평균선 (골든크로스 등 테스트용)
    # 단기 이평: 현재가 근처
    data['ma_short'] = price + random.randint(-50, 50)
    # 장기 이평: 현재가 근처
    data['ma_long'] = price + random.randint(-100, 100)
    
    # 이전 봉 데이터 (크로스 계산용, 추세 확인용)
    data['prev_price'] = price - random.randint(-30, 30)
    data['prev_ma_short'] = data['ma_short'] - random.randint(-20, 20)
    data['prev_ma_long'] = data['ma_long'] - random.randint(-10, 10) # 20일선 상승/하락 확인용
    
    # 수익률 (청산 테스트용, -3.0% ~ +6.0%)
    data['pnl_pct'] = random.uniform(-3.0, 6.0)
    
    return data

def _evaluate_single_condition(condition: dict, symbol: str, data: dict) -> bool:
    """
    단일 조건식 평가 헬퍼 함수
    condition: {'code': '...', 'desc': '...'}
    """
    if not condition:
        return False
        
    code = condition.get('code', '').strip()
    if not code:
        return False # 코드가 없으면 False (또는 의도에 따라 True? 보통 조건 없으면 False 처리하거나 상위에서 처리)

    try:
        # eval(): 문자열 코드를 실행하여 bool 결과 반환
        req_met = eval(code, {}, data)
        return bool(req_met)
    except Exception as e:
        logger.error(f"  [오류] {symbol} 조건식 실행 불가: {code} -> {e}")
        return False

def should_watch(symbol: str) -> bool:
    """
    [감시 조건] watch_conditions (포함 조건)
    True여야 '감시 대상'이 됨
    """
    # 이제 리스트가 아니라 단일 딕셔너리
    condition = STRATEGY_CONFIG.get("watch_conditions", {})
    if not condition or not condition.get('code'):
        return True # 조건이 아예 없으면 모두 감시(기본값)
        
    data = _get_mock_data(symbol)
    
    # 단일 조건 평가
    is_watched = _evaluate_single_condition(condition, symbol, data)
    
    return is_watched

def should_enter(symbol: str) -> bool:
    """
    [진입 조건] entry_conditions
    True면 매수 진입
    """
    condition = STRATEGY_CONFIG.get("entry_conditions", {})
    if not condition or not condition.get('code'):
        return False # 진입 조건 없으면 진입 불가
        
    data = _get_mock_data(symbol)
    can_enter = _evaluate_single_condition(condition, symbol, data)
    
    if can_enter:
        logger.info(f"  [Debug] {symbol} 진입 데이터: Price={data['price']}, MA5={data['ma_short']}, PrevP={data['prev_price']}")
        
    return can_enter

def should_exit(symbol: str) -> bool:
    """
    [청산 조건] exit_conditions
    True면 매도 청산
    """
    condition = STRATEGY_CONFIG.get("exit_conditions", {})
    if not condition or not condition.get('code'):
        return False
        
    data = _get_mock_data(symbol)
    can_exit = _evaluate_single_condition(condition, symbol, data)
    
    if can_exit:
        logger.info(f"  [Debug] {symbol} 청산 데이터: PnL={data['pnl_pct']:.2f}%")
        
    return can_exit
