"""
[전략 실험실 - 조건식 정의 파일]
config/strategies_sandbox.yaml 설정을 읽어 동적으로 판단합니다.
테스트를 위해 가상의 시세 데이터(Mock Data)를 생성하여 사용합니다.
"""
import os
import yaml
import random

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
    
    print(f"[lab1_cond] '{STRATEGY_NAME}' 설정 로드 완료")
except Exception as e:
    print(f"[lab1_cond] 설정 로드 실패 (기본값 사용): {e}")
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
    data['volume'] = random.randint(5000, 15000)
    
    # 이동평균선 (골든크로스 등 테스트용)
    # 단기 이평: 현재가 근처
    data['ma_short'] = price + random.randint(-50, 50)
    # 장기 이평: 현재가 근처
    data['ma_long'] = price + random.randint(-100, 100)
    
    # 이전 봉 데이터 (크로스 계산용)
    data['prev_price'] = price - random.randint(-30, 30)
    data['prev_ma_short'] = data['ma_short'] - random.randint(-20, 20)
    
    # 수익률 (청산 테스트용, -3.0% ~ +6.0%)
    data['pnl_pct'] = random.uniform(-3.0, 6.0)
    
    return data

def _evaluate_conditions(conditions: list, symbol: str, data: dict, logic_type: str = "AND") -> bool:
    """
    조건식 리스트 평가 헬퍼 함수
    logic_type: 
      - "AND": 모든 조건이 True여야 최종 True (진입용)
      - "OR": 하나라도 True면 최종 True (청산/제외용)
    """
    if not conditions:
        return False
        
    results = []
    
    # 디버깅용 로그 문자열
    log_details = []

    for cond in conditions:
        code = cond.get('code', 'False')
        desc = cond.get('desc', '')
        try:
            # eval(): 문자열 코드를 실행하여 bool 결과 반환
            # data 딕셔너리를 로컬 네임스페이스로 전달
            req_met = eval(code, {}, data)
            results.append(req_met)
            
            # (로그가 너무 많으면 주석 처리)
            # log_details.append(f"'{desc}':{req_met}")
        except Exception as e:
            print(f"  [오류] {symbol} 조건식 실행 불가: {code} -> {e}")
            results.append(False)

    # 로직 타입에 따른 최종 판단
    if logic_type == "AND":
        final_result = all(results)
    elif logic_type == "OR":
        final_result = any(results)
    else:
        final_result = False
        
    return final_result

def should_watch(symbol: str) -> bool:
    """
    [감시 조건] monitoring_exclusions (제외 조건)
    하나라도 True면 '감시 제외'이므로, 함수 반환값은 False여야 함.
    """
    exclusions = STRATEGY_CONFIG.get("monitoring_exclusions", [])
    if not exclusions:
        return True # 제외 조건 없으면 감시
        
    data = _get_mock_data(symbol)
    
    # 제외 조건은 하나라도 걸리면(OR) True
    is_excluded = _evaluate_conditions(exclusions, symbol, data, logic_type="OR")
    
    if is_excluded:
        # 디버깅: 왜 제외됐는지 알면 좋음 (나중에 상세 로그 추가 가능)
        # 예: data['volume']이 9000이라서 제외됨 등
        return False
        
    return True

def should_enter(symbol: str) -> bool:
    """
    [진입 조건] entry_conditions
    모두 만족해야(AND) 매수 진입
    """
    conditions = STRATEGY_CONFIG.get("entry_conditions", [])
    if not conditions:
        return False
        
    data = _get_mock_data(symbol)
    can_enter = _evaluate_conditions(conditions, symbol, data, logic_type="AND")
    
    # 디버깅 출력 (진입 성공 시에만)
    if can_enter:
        print(f"  [Debug] {symbol} 진입 데이터: Price={data['price']}, MA5={data['ma_short']}, PrevP={data['prev_price']}")
        
    return can_enter

def should_exit(symbol: str) -> bool:
    """
    [청산 조건] exit_conditions
    하나라도 만족하면(OR) 매도 청산
    """
    conditions = STRATEGY_CONFIG.get("exit_conditions", [])
    if not conditions:
        return False
        
    data = _get_mock_data(symbol)
    can_exit = _evaluate_conditions(conditions, symbol, data, logic_type="OR")
    
    if can_exit:
        print(f"  [Debug] {symbol} 청산 데이터: PnL={data['pnl_pct']:.2f}%")
        
    return can_exit
