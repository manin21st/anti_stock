"""
[전략 실험실 - 조건식 정의 파일]
config/strategies_sandbox.yaml 설정을 읽어 동적으로 판단합니다.
"""
import os
import sys
import yaml
import random
import logging
import pandas as pd

# Add project root to path to allow imports from core
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.market_data import MarketData # [Real Data]
from core import interface as ka # [Real Data] API 직접 호출용

logger = logging.getLogger(__name__)

# 설정 파일 경로 식별 (같은 폴더 내 lab1_cond.yaml)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "lab1_cond.yaml")

# --- 설정 로드 (Dynamic Reloading) ---
STRATEGY_CONFIG = {}
VARIABLES = {}
_LAST_LOAD_TIME = 0

def _reload_config():
    """설정 파일이 변경되었을 경우 다시 로드합니다."""
    global STRATEGY_CONFIG, VARIABLES, _LAST_LOAD_TIME
    
    try:
        # 파일 수정 시간 불일치 시 리로드
        mtime = os.path.getmtime(CONFIG_PATH)
        if mtime > _LAST_LOAD_TIME:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                _yaml_data = yaml.safe_load(f)
                
            # 최상위 키가 하나라고 가정 (MySandboxStrategy)
            strategy_name = list(_yaml_data.keys())[0]
            new_config = _yaml_data[strategy_name]
            
            STRATEGY_CONFIG = new_config
            VARIABLES = new_config.get("variables", {})
            
            _LAST_LOAD_TIME = mtime
            logger.info(f"[lab1_cond] '{strategy_name}' 설정 리로드 완료 (Updated)")
            
    except Exception as e:
        logger.error(f"[lab1_cond] 설정 리로드 실패: {e}")

# 초기 로드 실행
_reload_config()

def _initialize_context(symbol: str) -> dict:
    """
    [Context Init] 조건식 평가에 사용할 변수들을 기본값으로 초기화합니다.
    - 모든 변수를 이곳에 명시하여 NameError를 방지합니다.
    - LLM 프롬프트에 제공할 '사용 가능한 변수 목록'의 기준이 됩니다.
    """
    return {
        # 1. 기본 식별자
        'symbol': symbol,
        
        # 2. 시장 데이터 (현재가, 거래량)
        'price': 0.0,
        'volume': 0,
        'prev_price': 0.0,
        'prev_volume': 0,
        
        # 3. 보조 지표 (이동평균 등)
        'ma_short': 0.0,
        'ma_long': 0.0,
        'prev_ma_short': 0.0,
        'prev_ma_long': 0.0,
        'avg_volume_long': 0,
        
        # 4. 포트폴리오 상태 (보유 여부, 수익률 등)
        'has_position': False,
        'current_qty': 0,      # 보유 수량
        'avg_price': 0.0,      # 평단가
        'pnl_pct': 0.0,        # 수익률 (%)
        'pnl_amt': 0,          # 평가 손익금
        
        # 5. 자산 현황 (Action 수식에서 비중 계산용)
        'total_asset': 0,      # 총 자산 (예수금 + 평가금)
        'cash': 0,             # 주문 가능 현금 (예수금)
        'portfolio_value': 0,  # 주식 평가금 총액
    }

def _inject_portfolio_data(context: dict, portfolio, symbol: str):
    """
    [Portfolio Injection] 포트폴리오 주입 (보유 수량, 평단가, 수익률, 자산 정보)
    context 딕셔너리를 직접 업데이트합니다.
    """
    if not portfolio:
        return

    # 1. 개별 종목 포지션 정보
    pos = portfolio.get_position(symbol)
    if pos and pos.qty > 0:
        context['has_position'] = True
        context['current_qty'] = pos.qty
        context['avg_price'] = pos.avg_price
        
        # 수익률 실시간 계산
        current_price = context.get('price', 0.0)
        if pos.avg_price > 0 and current_price > 0:
            pnl_pct = ((current_price - pos.avg_price) / pos.avg_price) * 100
            pnl_amt = (current_price - pos.avg_price) * pos.qty
            
            context['pnl_pct'] = round(pnl_pct, 2)
            context['pnl_amt'] = int(pnl_amt)

    # 2. 전체 자산 정보 (비중 조절용)
    context['total_asset'] = int(portfolio.total_asset)
    context['cash'] = int(portfolio.cash)
    context['portfolio_value'] = int(portfolio.total_asset - portfolio.cash) # 주식 평가금

def _get_real_data(symbol: str, market_data: MarketData) -> dict:
    """
    [Real Data] 실제 시장 데이터를 조회하여 Context 업데이트
    """
    # 1. 기본값 초기화
    data = _initialize_context(symbol)
    
    # 사용자 정의 변수(상수) 병합
    data.update(VARIABLES)

    try:
        # 2. 일봉 데이터 조회 (MarketData 캐시 사용)
        df = market_data.get_bars(symbol, timeframe='1d', lookback=60)
        
        if df.empty or len(df) < 20:
            logger.warning(f"[{symbol}] 데이터 부족 (len={len(df)})")
            # 데이터가 부족해도 기본값(0)이 들어있는 data를 반환하여 에러 방지
            return data

        # 3. [실시간] 현재가 업데이트
        real_tick = ka.fetch_price(symbol)
        if real_tick:
            current_price = float(real_tick.get('stck_prpr', 0))
            current_vol = int(real_tick.get('acml_vol', 0))
            
            # DataFrame 마지막 행 업데이트
            df.iloc[-1, df.columns.get_loc('close')] = current_price
            df.iloc[-1, df.columns.get_loc('volume')] = current_vol
        
        # 4. 지표 재계산
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma20'] = df['close'].rolling(window=20).mean()
        
        # 5. 데이터 추출 Logic
        curr = df.iloc[-1] # 오늘
        prev = df.iloc[-2] # 전일
        
        data.update({
            'price': float(curr['close']),
            'volume': int(curr['volume']),
            
            'prev_price': float(prev['close']),
            'prev_volume': int(prev['volume']),
            'avg_volume_long': int(df['volume'].tail(20).mean()),
            
            'ma_short': float(curr['ma5']) if pd.notnull(curr['ma5']) else 0.0,
            'ma_long': float(curr['ma20']) if pd.notnull(curr['ma20']) else 0.0,
            
            'prev_ma_short': float(prev['ma5']) if pd.notnull(prev['ma5']) else 0.0,
            'prev_ma_long': float(prev['ma20']) if pd.notnull(prev['ma20']) else 0.0,
        })
        
        return data

    except Exception as e:
        logger.error(f"[{symbol}] 실시간 데이터 조회 실패: {e}")
        return data

def _evaluate_single_condition(condition: dict, symbol: str, data: dict) -> bool:
    """단일 조건식 평가"""
    if not condition: return False
    code = condition.get('code', '').strip()
    if not code: return False
    
    try:
        req_met = eval(code, {}, data)
        return bool(req_met)
    except Exception as e:
        logger.error(f"  [오류] {symbol} 조건식 실행 불가: {code} -> {e}")
        return False

def _evaluate_action(condition: dict, symbol: str, data: dict) -> dict:
    """
    [Action Evaluation] 실행 수식을 평가하여 매매 파라미터(dict) 반환
    예: "{'target_pct': 10}" -> {'target_pct': 10}
    """
    if not condition: return {}
    action_code = condition.get('action', '').strip()
    
    # 실행 수식이 없으면 빈 dict 반환 (기본값 동작)
    if not action_code: return {}

    try:
        # data 컨텍스트를 사용하여 수식 평가
        action_params = eval(action_code, {}, data)
        if isinstance(action_params, dict):
            return action_params
        else:
            logger.warning(f"[{symbol}] 실행 수식 결과가 Dict가 아님: {action_params}")
            return {}
    except Exception as e:
        logger.error(f"[{symbol}] 실행 수식 오류: {action_code} -> {e}")
        return {}

def should_watch(symbol: str, market_data: MarketData) -> bool:
    """[감시 조건]"""
    _reload_config() 
    condition = STRATEGY_CONFIG.get("watch_conditions", {})
    if not condition or not condition.get('code'):
        return True
    
    # Context 생성
    data = _get_real_data(symbol, market_data)
    return _evaluate_single_condition(condition, symbol, data)

def should_enter(symbol: str, market_data: MarketData, portfolio=None) -> tuple[bool, dict]:
    """[진입 조건] -> (진입여부, 실행파라미터)"""
    _reload_config()
    condition = STRATEGY_CONFIG.get("entry_conditions", {})
    if not condition or not condition.get('code'):
        return False, {}

    name = market_data.get_stock_name(symbol)    
    
    # 1. 데이터 준비
    data = _get_real_data(symbol, market_data)
    
    # 2. 포트폴리오 주입
    _inject_portfolio_data(data, portfolio, symbol)

    # 3. 조건식(When) 평가
    can_enter = _evaluate_single_condition(condition, symbol, data)

    action_params = {}
    if can_enter:
        desc = condition.get('desc', '진입 조건 설명 없음')
        logger.info(f"[{name}({symbol})] Data: {data}")
        logger.info(f"[{name}({symbol})] 진입 조건 통과: {desc}")
        
        # 4. 실행식(How) 평가
        action_params = _evaluate_action(condition, symbol, data)
        if action_params:
            logger.info(f"  => 실행 파라미터: {action_params}")

    return can_enter, action_params

def should_exit(symbol: str, market_data: MarketData, portfolio=None) -> tuple[bool, dict]:
    """[청산 조건] -> (청산여부, 실행파라미터)"""
    _reload_config()
    condition = STRATEGY_CONFIG.get("exit_conditions", {})
    if not condition or not condition.get('code'):
        return False, {}
        
    name = market_data.get_stock_name(symbol)    
    
    # 1. 데이터 준비
    data = _get_real_data(symbol, market_data)
    
    # 2. 포트폴리오 주입
    _inject_portfolio_data(data, portfolio, symbol)

    # 3. 조건식 평가
    can_exit = _evaluate_single_condition(condition, symbol, data)
    
    action_params = {}
    if can_exit:
        desc = condition.get('desc', '청산 조건 설명 없음')
        logger.info(f"[{name}({symbol})] 청산 조건 통과: {desc}")
        
        # 4. 실행식 평가
        action_params = _evaluate_action(condition, symbol, data)
        if action_params:
            logger.info(f"  => 실행 파라미터: {action_params}")
        
    return can_exit, action_params
