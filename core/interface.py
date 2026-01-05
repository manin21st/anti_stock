import time
import threading
import logging
import sys
import os
import random
import contextlib
from typing import Dict, Optional, Any, List, Callable
import requests
import json

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 전역 API 제어를 위한 단순 장치
_api_lock = threading.Lock()
_last_api_call = time.time()

logger = logging.getLogger(__name__)

# --- [Shadow Home Logic] ---
# Configure environment for kis_auth to read config/kis_devlp.yaml without modification
try:
    import shutil
    import hashlib
    
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    user_config_path = os.path.join(project_root, "config", "kis_devlp.yaml")
    
    # Check if user has provided a custom kis_devlp.yaml in config/
    if os.path.exists(user_config_path):
        # Determine original home directory
        original_home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
        if not original_home:
            original_home = os.path.expanduser("~")
            
        # Create a unique shadow directory in the User's Home based on project path hash
        # This keeps the project structure clean and separates instances (Paper/Real) 
        project_hash = hashlib.md5(project_root.encode('utf-8')).hexdigest()[:8]
        shadow_home_base = os.path.join(original_home, ".anti_stock", project_hash)
        
        shadow_kis_config_dir = os.path.join(shadow_home_base, "KIS", "config")
        os.makedirs(shadow_kis_config_dir, exist_ok=True)
        
        # Copy the user's config file to the shadow location
        target_path = os.path.join(shadow_kis_config_dir, "kis_devlp.yaml")
        shutil.copy2(user_config_path, target_path)
        
        # Override HOME/USERPROFILE for the current process
        os.environ["USERPROFILE"] = shadow_home_base # Windows
        os.environ["HOME"] = shadow_home_base        # Linux/Mac
        
        logger.debug(f"[INTERFACE] Shadow Home activated at {shadow_home_base} (Project: {os.path.basename(project_root)})")
    else:
        logger.info("[INTERFACE] Custom kis_devlp.yaml not found in config/, using system default")
        
except Exception as e:
    logger.error(f"[INTERFACE] Failed to setup Shadow Home: {e}")

# Add open-trading-api/examples_user to path to import original kis_auth
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "open-trading-api", "examples_user"))

import kis_auth as ka

# --- Backtest State Management ---
_backtest_mode = False
_mock_state = {
    "cash": 0,
    "positions": {},  # {symbol: {qty: 0, avg_price: 0, ...}}
    "prices": {},     # {symbol: price (int/float)}
    "date": None,     # YYYYMMDD
    "time": None      # HHMMSS
}
_mock_orders = []     # List of orders sent during the current step
_data_provider = None # Hook for fetch_daily_chart/fetch_minute_chart (avoid circular import)

def set_backtest_mode(mode: bool):
    global _backtest_mode
    _backtest_mode = mode
    logger.info(f"[INTERFACE] Backtest Mode set to: {mode}")

def set_mock_state(cash: int, positions: dict, prices: dict, date: str = None, time: str = None):
    """
    Update the mock state for the current backtest step.
    prices: {symbol: current_price}
    """
    global _mock_state
    _mock_state["cash"] = cash
    _mock_state["positions"] = positions
    _mock_state["prices"] = prices
    _mock_state["date"] = date
    _mock_state["time"] = time

def get_mock_orders() -> List[Dict]:
    """Retrieve and clear the list of orders sent during this step."""
    global _mock_orders
    orders = list(_mock_orders)
    _mock_orders.clear()
    return orders

def clear_mock_orders():
    global _mock_orders
    _mock_orders.clear()

def set_data_provider(provider_func: Callable):
    """
    Set a callback function to provide historical data during backtests.
    This prevents circular imports with data_loader.
    Signature: provider_func(symbol, type, date, ...)
    """
    global _data_provider
    _data_provider = provider_func

# --- API Executor Integration (Simplified) ---
def _execute_api(func, *args, **kwargs):
    """
    모든 API 호출의 단일 진입점. 
    최소 1.5초 간격을 보장하며, EGW00201 발생 시 자동 재시도.
    """
    global _last_api_call
    kwargs.pop('priority', None)
    
    for attempt in range(1, 4): # 최대 3번 시도
        with _api_lock:
            now = time.time()
            elapsed = now - _last_api_call
            interval = 1.1 # 정상 매매 가능 속도로 복구
            
            if elapsed < interval:
                time.sleep(interval - elapsed)
            
            _last_api_call = time.time()
            res = func(*args, **kwargs)
            
            # EGW00201(속도 제한) 또는 500(서버 점검/오류) 발생 시 조용히 1회 재시도
            try:
                msg = str(res.getErrorMessage() if hasattr(res, 'getErrorMessage') else '')
                # APIResp는 _rescode, APIRespError는 status_code 필드를 가짐
                status_code = getattr(res, '_rescode', getattr(res, 'status_code', 200))
                
                # EGW00201 또는 HTTP 500 에러 발생 시 재시도
                if ('EGW00201' in msg or status_code == 500) and attempt < 3:
                    wait_time = 1.5 if status_code != 500 else 2.0
                    if status_code == 500:
                        logger.warning(f"[INTERFACE] 500 Error detected ({msg}). Retrying {attempt}/3...")
                    time.sleep(wait_time)
                    continue
            except:
                pass
                
            return res
    return res

def configure_rate_limiter(tps_limit: float = None, server_url: str = None):
    # 이제 설정이 필요 없으므로 무시
    pass

def get_rate_limiter_stats() -> Dict:
    return {"status": "simple_lock", "interval": 1.1}

def stop_rate_limiter():
    pass

def wait_for_tps():
    pass

# Legacy alias (deprecated but kept for safety if external access exists)
rate_limiter = None 


# --- Wrapper Functions ---

def auth(svr="prod", product=None, url=None, force=False):
    """Wrapper for kis_auth.auth"""
    if _backtest_mode:
        return # Skip auth in backtest
        
    kwargs = {"svr": svr}
    if product is not None:
        kwargs["product"] = product
    if url is not None:
        kwargs["url"] = url

    if force:
        try:
            token_file = ka.token_tmp
            if os.path.exists(token_file):
                os.remove(token_file)
        except Exception:
            pass

    _execute_api(ka.auth, **kwargs)
    
    # 인증 직후 안정화를 위해 추가 대기
    time.sleep(1.0)
    # Executor handles timing internally

def auth_ws(svr="prod", product=None):
    if _backtest_mode:
        return
    kwargs = {"svr": svr}
    if product is not None:
        kwargs["product"] = product
    _execute_api(ka.auth_ws, **kwargs)

def is_paper_trading():
    if _backtest_mode:
        return True # Treat backtest as paper (or use explicit mock check)
    try:
        env = ka.getTREnv()
        url = getattr(env, 'my_url', '')
        if url and "openapivts" in url:
            return True
        return False
    except Exception:
        return False

def get_tr_env():
    if _backtest_mode:
        return type('MockEnv', (), {"my_acct": "MOCK_ACCT", "my_prod": "00"})()
    return ka.getTREnv()

def get_env():
    return ka.getEnv()

# Aliases
getTREnv = get_tr_env
isPaperTrading = is_paper_trading
KISWebSocket = ka.KISWebSocket 

def issue_request(api_url, ptr_id, tr_cont, params, appendHeaders=None, postFlag=False, hashFlag=True):
    """
    Generic wrapper for _url_fetch.
    In Backtest Mode: Block or Mock.
    """
    if _backtest_mode:
        # Prevent accidental API calls from Scanner or other components during backtest
        # Return a Dummy Response
        logger.debug(f"[INTERFACE Backtest] Blocked request to {api_url}")
        class MockResponse:
            def isOK(self): return True
            def getBody(self): return type('Body', (), {"output": []})()
        return MockResponse()

    return _execute_api(ka._url_fetch, api_url, ptr_id, tr_cont, params, appendHeaders, postFlag, hashFlag)

def fetch_price(symbol: str) -> Dict[str, Any]:
    """
    Wrapper for inquire-price (Current Price)
    Backtest: Return mocked price from _mock_state
    """
    if _backtest_mode:
        price = _mock_state["prices"].get(symbol)
        if price:
            # Emulate KIS API output structure minimal fields
            return {
                "stck_prpr": str(price),
                "rprs_mrkt_kor_name": f"Mock_{symbol}",
                "stck_shrn_iscd": symbol
            }
        return {}

    tr_id = "FHKST01010100"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": symbol
    }
    res = _execute_api(ka._url_fetch, "/uapi/domestic-stock/v1/quotations/inquire-price", tr_id, "", params)
    if res and res.isOK():
        return res.getBody().output
    else:
        logger.error(f"fetch_price failed for {symbol}: {res.getErrorMessage() if res else 'Unknown Error'}")
        return {}

def fetch_daily_chart(symbol: str, start_dt: str, end_dt: str, lookback: int = 100) -> Any:
    """Wrapper for inquire-daily-itemchartprice"""
    if _backtest_mode:
        if _data_provider:
             # Provide data via callback (from local files loaded by Backtester/DataLoader)
             return _data_provider(symbol, "day", start_dt, end_dt)
        return []

    tr_id = "FHKST03010100"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": symbol,
        "FID_INPUT_DATE_1": start_dt,
        "FID_INPUT_DATE_2": end_dt,
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "1"
    }
    return _execute_api(ka._url_fetch, "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", tr_id, "", params)

def fetch_minute_chart(symbol: str, current_time: str) -> Any:
    """Wrapper for inquire-time-itemchartprice"""
    if _backtest_mode:
         if _data_provider:
             return _data_provider(symbol, "min", _mock_state.get("date"), current_time)
         return []

    tr_id = "FHKST03010200"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": symbol,
        "FID_INPUT_HOUR_1": current_time,
        "FID_PW_DATA_INCU_YN": "Y",
        "FID_ETC_CLS_CODE": ""
    }
    return _execute_api(ka._url_fetch, "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice", tr_id, "", params)

def fetch_past_minute_chart(symbol: str, date: str, time: str, period_code: str = "N") -> Any:
    if _backtest_mode:
        return [] # TODO: implement if needed

    tr_id = "FHKST03010230"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": symbol,
        "FID_INPUT_HOUR_1": time,
        "FID_INPUT_DATE_1": date,
        "FID_PW_DATA_INCU_YN": period_code,
        "FID_FAKE_TICK_INCU_YN": ""
    }
    return _execute_api(ka._url_fetch, "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice", tr_id, "", params)

def send_order(tr_id: str, params: Dict[str, str]) -> Any:
    """
    Wrapper for order-cash
    Backtest: Record order in _mock_orders
    """
    if _backtest_mode:
        # params example: {'CANO': '...', 'PDNO': '005930', 'ORD_DVSN': '00', 'ORD_QTY': '10', 'ORD_UNPR': '0'}
        # Record this order
        order_info = params.copy()
        order_info['tr_id'] = tr_id # Store TR_ID to distinguish Buy/Sell
        
        # Calculate approximate price if market order (mock logic required by Backtester)
        # But 'send_order' usually relies on current price.
        # The Backtester will process these orders.
        
        _mock_orders.append(order_info)
        
        # Mock Response Object
        class MockOrderResponse:
             def isOK(self): return True
             def getBody(self):
                 # Return fake Order Number (ODNO)
                 return type('Body', (), {"output": {"ODNO": f"MOCK_{int(time.time()*1000)}"}})()
        
        return MockOrderResponse()

    return _execute_api(ka._url_fetch, "/uapi/domestic-stock/v1/trading/order-cash", tr_id, "", params, postFlag=True)

def get_balance(tr_id: str, params: Dict[str, str]) -> Any:
    """
    Wrapper for inquire-balance
    Backtest: Return mocked balance and holdings
    """
    if _backtest_mode:
        # Construct mocked response
        holdings = []
        total_eval_amt = 0
        total_buy_amt = 0
        
        # _mock_state['positions'] = {symbol: {'qty': 10, 'avg_price': 50000, 'amount': 500000}}
        for sym, pos in _mock_state["positions"].items():
            current_price = _mock_state["prices"].get(sym, pos['avg_price'])
            qty = pos['qty']
            avg_price = pos['avg_price']
            buy_amt = pos.get('amount', qty * avg_price)
            eval_amt = qty * current_price
            
            total_buy_amt += buy_amt
            total_eval_amt += eval_amt
            
            holdings.append({
                "pdno": sym,
                "prdt_name": f"Mock_{sym}",
                "hldg_qty": str(qty),
                "pchs_avg_pric": str(avg_price),
                "prpr": str(current_price),
                "evlu_amt": str(eval_amt),
                "pchs_amt": str(buy_amt),
                "evlu_pfls_amt": str(eval_amt - buy_amt),
                "evlu_pfls_rt": str(((eval_amt - buy_amt)/buy_amt)*100) if buy_amt > 0 else "0"
            })
            
        summary = {
            "dnca_tot_amt": str(_mock_state["cash"]),
            "tot_evlu_amt": str(_mock_state["cash"] + total_eval_amt), 
            "nass_amt": str(_mock_state["cash"] + total_eval_amt)
        }
        
        # Return dict that mimics getBody().output
        return {
            "output1": [summary],
            "output2": holdings
        }

    return _execute_api(ka._url_fetch, "/uapi/domestic-stock/v1/trading/inquire-balance", tr_id, "", params)

def fetch_daily_ccld(start_dt: str, end_dt: str, symbol: str = "", ctx_area_fk: str = "", ctx_area_nk: str = "") -> Any:
    if _backtest_mode:
        return None # Not used in backtest usually

    is_paper = is_paper_trading()
    tr_id = "VTTC0081R" if is_paper else "TTTC0081R"
    env = ka.getTREnv()
    cano = env.my_acct
    acnt_prdt_cd = env.my_prod

    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "INQR_STRT_DT": start_dt,
        "INQR_END_DT": end_dt,
        "SLL_BUY_DVSN_CD": "00",
        "CCLD_DVSN": "01",
        "PDNO": symbol,
        "INQR_DVSN": "00",
        "INQR_DVSN_1": "",
        "INQR_DVSN_3": "00",
        "ORD_GNO_BRNO": "",
        "ODNO": "",
        "ORD_DVSN": "00",
        "CTX_AREA_FK100": ctx_area_fk,
        "CTX_AREA_NK100": ctx_area_nk
    }
    return _execute_api(ka._url_fetch, "/uapi/domestic-stock/v1/trading/inquire-daily-ccld", tr_id, "", params)

def fetch_period_profit(start_dt: str, end_dt: str, ctx_area_fk: str = "", ctx_area_nk: str = "") -> Any:
    if _backtest_mode:
        return None

    is_paper = is_paper_trading()
    tr_id = "VTTC8708R" if is_paper else "TTTC8708R"

    env = ka.getTREnv()
    cano = env.my_acct
    acnt_prdt_cd = env.my_prod

    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "INQR_STRT_DT": start_dt,
        "INQR_END_DT": end_dt,
        "SORT_DVSN": "00",
        "INQR_DVSN": "00",
        "CBLC_DVSN": "00",
        "CTX_AREA_FK100": ctx_area_fk,
        "CTX_AREA_NK100": ctx_area_nk
    }
    return _execute_api(ka._url_fetch, "/uapi/domestic-stock/v1/trading/inquire-period-profit", tr_id, "", params)
def fetch_holiday(base_date: str) -> List[Dict]:
    """
    국내 휴장일 정보 조회 (CTCA0903R)
    base_date: 기준일자 (YYYYMMDD)
    참고: 이 API는 실전투자 계좌에서만 작동하며, 모의투자(VTS)에서는 지원되지 않을 수 있습니다.
    """
    if _backtest_mode or is_paper_trading():
        # 백테스트나 모의투자에서는 API 실패가 예상되므로 호출을 생략하고 빈 리스트를 반환하여
        # 엔진이 요일 기반으로 판단하게 유도합니다.
        return []

    tr_id = "CTCA0903R"
    params = {
        "BASS_DT": base_date,
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }
    res = _execute_api(ka._url_fetch, "/uapi/domestic-stock/v1/quotations/chk-holiday", tr_id, "", params)
    if res and res.isOK():
        return res.getBody().output
    else:
        # 실전투자인데도 실패한 경우에만 에러를 남깁니다.
        logger.error(f"fetch_holiday failed: {res.getErrorMessage() if res else 'Unknown Error'}")
        return []
