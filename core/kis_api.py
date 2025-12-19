import time
import threading
import logging
import sys
import os
import random
import contextlib
from typing import Dict, Optional, Any
import requests
import json

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Add open-trading-api/examples_user to path to import original kis_auth
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "open-trading-api", "examples_user"))

import kis_auth as ka

logger = logging.getLogger(__name__)

class RateLimiter:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(RateLimiter, cls).__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        # Configurable TPS Limit (Default: 2.0 for single machine standard performance)
        try:
            self.tps_limit = float(os.environ.get("TPS_LIMIT", 2.0))
        except ValueError:
            self.tps_limit = 2.0
            
        self.min_interval = 1.0 / max(self.tps_limit, 0.1)  # Prevent division by zero
        self.last_call_time = 0.0
        self.lock = threading.Lock()
        
        # TPS Server Config
        self.server_url = os.environ.get("TPS_SERVER_URL", "http://localhost:9000")
        self.use_server = False 
        self.server_alive = True 
        self.server_fail_count = 0 
        self.logged_server_error = False 
        
        # Generate Client ID (Hostname + PID)
        import socket
        self.client_id = f"{socket.gethostname()}-{os.getpid()}"
        
        logger.info(f"[RateLimiter] Initialized with TPS_LIMIT={self.tps_limit} (Interval: {self.min_interval:.3f}s)")
        # Check if we should try to use server (if explicitly set or default)
        # We will try lazily in execute
        
    def set_limit(self, tps_limit: float):
        """Update TPS Limit dynamically"""
        with self.lock:
            self.tps_limit = float(tps_limit)
            self.min_interval = 1.0 / max(self.tps_limit, 0.1)
            logger.info(f"[RateLimiter] Limit updated to TPS={self.tps_limit} (Interval: {self.min_interval:.3f}s)")

    def set_server_url(self, url: str):
        """Update TPS Server URL dynamically"""
        with self.lock:
            if url and url != self.server_url:
                self.server_url = url.rstrip('/') # Normalize
                self.server_alive = True # Reset status to try new URL
                self.logged_server_error = False
                logger.info(f"[RateLimiter] Server URL updated to: {self.server_url}")

    def _request_token_from_server(self):
        """
        Request a token from the centralized server.
        Returns:
            True: Token acquired (Proceed)
            False: Limit exceeded (Wait)
            None: Server error (Fallback to Local)
        """
        try:
            # Short timeout to not block trading
            headers = {"X-Client-ID": self.client_id}
            resp = requests.get(f"{self.server_url}/token", headers=headers, timeout=0.1)
            
            if resp.status_code == 200:
                if not self.server_alive:
                     self.server_alive = True
                     logger.info(f"[RateLimiter] TPS Server Reconnected: {self.server_url}")
                     self.logged_server_error = False
                return True
            elif resp.status_code == 429:
                return False
            else:
                return False # Treat other codes as limit exceeded or error? Let's say False to backoff.
                
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if not self.logged_server_error:
                logger.warning(f"[RateLimiter] TPS Server Unreachable ({self.server_url}). Switching to Local Mode.")
                self.logged_server_error = True
            self.server_alive = False
            return None
        except Exception:
            return None

    def execute(self, func, *args, **kwargs):
        """
        Executes the function with Rate Limiting Lock held.
        """
        max_retries = 3
        
        for attempt in range(max_retries + 1):
            with self.lock:
                # Hybrid Rate Limiting
                # 1. Try Server if alive
                token_granted = False
                
                # Check server only if we haven't failed too much or logic dictates
                # We simply try if not failed recently? Or just try every time if not flagged?
                # The requirement says: switch to local if server fails.
                # Let's try server first.
                
                server_status = self._request_token_from_server()
                
                if server_status is True:
                    # Token Granted! Proceed immediately without efficient wait
                    pass 
                elif server_status is False:
                    # Limit Exceeded (Server said wait)
                    # We should wait a bit. Server usually returns 'wait' time in body but we didn't parse it for speed.
                    # Default wait 0.1s
                    time.sleep(0.1) 
                    # Don't increment call time, just loop
                    continue
                else:
                    # Server Error (None) -> Fallback to Local Interval
                    now = time.time()
                    elapsed = now - self.last_call_time
                    if elapsed < self.min_interval:
                        sleep_time = self.min_interval - elapsed
                        time.sleep(sleep_time)
                
                # 2. Execute API Call
                try:
                    # Suppress external library prints
                    with open(os.devnull, 'w') as devnull:
                        with contextlib.redirect_stdout(devnull):
                            result = func(*args, **kwargs)
                    
                    # 3. Check for Rate Limit Error (EGW00201)
                    is_rate_limit = False
                    if hasattr(result, 'getErrorCode') and result.getErrorCode() == "EGW00201":
                        is_rate_limit = True
                    elif hasattr(result, 'getErrorMessage'):
                         msg = result.getErrorMessage()
                         if msg and "EGW00201" in msg:
                             is_rate_limit = True

                    if is_rate_limit:
                        if attempt < max_retries:
                            jitter = random.uniform(0.0, 0.5)
                            backoff_time = 0.5 + jitter
                            logger.debug(f"[RateLimiter] Rate limit exceeded (EGW00201). Backing off {backoff_time:.2f}s... (Attempt {attempt+1})")
                            time.sleep(backoff_time)
                            self.last_call_time = time.time()
                            continue # Retry
                        else:
                            logger.error("[RateLimiter] Max retries exceeded for rate limit.")
                    
                    # 4. Check for Expired Token (EGW00123)
                    is_expired_token = False
                    if hasattr(result, 'getErrorCode') and result.getErrorCode() == "EGW00123":
                        is_expired_token = True
                    elif hasattr(result, 'getErrorMessage'):
                        msg = result.getErrorMessage()
                        if msg and "EGW00123" in msg:
                            is_expired_token = True
                            
                    if is_expired_token:
                        if attempt < max_retries:
                            logger.debug(f"[RateLimiter] Token expired (EGW00123). Re-authenticating...")
                            try:
                                if hasattr(ka, 'token_tmp') and os.path.exists(ka.token_tmp):
                                    os.remove(ka.token_tmp)
                            except Exception:
                                pass

                            svr = "vps" if ka.isPaperTrading() else "prod"
                            ka.auth(svr=svr)
                            
                            self.last_call_time = time.time()
                            continue 
                        else:
                            logger.error("[RateLimiter] Max retries exceeded for token expiration.")
                    
                    # Update timestamp (Local fallback needs this)
                    self.last_call_time = time.time()
                    return result

                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                    if attempt < max_retries:
                        backoff = 1.0 * (attempt + 1)
                        logger.warning(f"[RateLimiter] Connection unstable: {e}. Retrying in {backoff}s...")
                        time.sleep(backoff)
                        self.last_call_time = time.time()
                        continue
                    else:
                        logger.error(f"[RateLimiter] Max retries exceeded for connection error: {e}")
                        self.last_call_time = time.time()
                        raise e
                        
                except Exception as e:
                    self.last_call_time = time.time()
                    raise e
                    
# Global Instance
rate_limiter = RateLimiter()

def auth(svr="prod", product=None, url=None, force=False):
    """
    Wrapper for kis_auth.auth
    """
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
        
    ka.auth(**kwargs)
    
    if rate_limiter:
        rate_limiter.last_call_time = time.time()

def auth_ws(svr="prod", product=None):
    """
    Wrapper for kis_auth.auth_ws
    """
    kwargs = {"svr": svr}
    if product is not None:
        kwargs["product"] = product
    ka.auth_ws(**kwargs)


def is_paper_trading():
    return ka.isPaperTrading()

def get_tr_env():
    return ka.getTREnv()

def get_env():
    return ka.getEnv()


# Aliases for compatibility
getTREnv = get_tr_env
isPaperTrading = is_paper_trading
KISWebSocket = ka.KISWebSocket

def issue_request(api_url, ptr_id, tr_cont, params, appendHeaders=None, postFlag=False, hashFlag=True):
    """
    Generic wrapper for _url_fetch with Rate Limiting
    """
    return rate_limiter.execute(ka._url_fetch, api_url, ptr_id, tr_cont, params, appendHeaders, postFlag, hashFlag)

def fetch_price(symbol: str) -> Dict[str, Any]:
    """
    Wrapper for inquire-price (Current Price)
    TR_ID: FHKST01010100
    """
    tr_id = "FHKST01010100"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": symbol
    }
    
    res = rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/quotations/inquire-price", tr_id, "", params)
    
    if res.isOK():
        return res.getBody().output
    else:
        logger.error(f"fetch_price failed for {symbol}: {res.getErrorMessage()}")
        return {}

def fetch_daily_chart(symbol: str, start_dt: str, end_dt: str, lookback: int = 100) -> Any:
    """
    Wrapper for inquire-daily-itemchartprice
    TR_ID: FHKST03010100
    """
    tr_id = "FHKST03010100"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": symbol,
        "FID_INPUT_DATE_1": start_dt,
        "FID_INPUT_DATE_2": end_dt,
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "1"
    }
    
    return rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", tr_id, "", params)

def fetch_minute_chart(symbol: str, current_time: str) -> Any:
    """
    Wrapper for inquire-time-itemchartprice
    TR_ID: FHKST03010200
    """
    tr_id = "FHKST03010200"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": symbol,
        "FID_INPUT_HOUR_1": current_time,
        "FID_PW_DATA_INCU_YN": "Y",
        "FID_ETC_CLS_CODE": ""
    }
    
    return rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice", tr_id, "", params)

def fetch_past_minute_chart(symbol: str, date: str, time: str, period_code: str = "N") -> Any:
    """
    Wrapper for inquire-time-dailychartprice (Past Minute Data)
    TR_ID: FHKST03010230
    Max 1 year past data.
    """
    tr_id = "FHKST03010230"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": symbol,
        "FID_INPUT_HOUR_1": time,     # HHMMSS
        "FID_INPUT_DATE_1": date,     # YYYYMMDD
        "FID_PW_DATA_INCU_YN": period_code, # N: Current, Y: Past? No, this TR uses N usually.
        # Actually API docs say: FID_PW_DATA_INCU_YN: Past data include Y/N. 
        # But for this specific TR FHKST03010230, it iterates backwards from the given time/date?
        # Let's verify parameter names from the example.
        "FID_FAKE_TICK_INCU_YN": ""
    }
    
    return rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice", tr_id, "", params)

def send_order(tr_id: str, params: Dict[str, str]) -> Any:
    """
    Wrapper for order-cash
    """
    # postFlag=True is standard for orders
    return rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/trading/order-cash", tr_id, "", params, postFlag=True)

def get_balance(tr_id: str, params: Dict[str, str]) -> Any:
    """
    Wrapper for inquire-balance
    """
    return rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/trading/inquire-balance", tr_id, "", params)


# (End of file, removed Prod Token and Stock Info functions)

def fetch_daily_ccld(start_dt: str, end_dt: str, symbol: str = "", ctx_area_fk: str = "", ctx_area_nk: str = "") -> Any:
    """
    Wrapper for inquire-daily-ccld (Daily Execution History)
    TR_ID: TTTC0081R (Real/Inner) or VTSC9215R (Demo/Before) - simplified for Inner period
    """
    # Determine Environment and TR_ID
    # Simplified logic: Assuming 'inner' period (within 3 months) which is standard usage
    # For 'real' env: TTTC0081R, For 'paper' env: VTTC0081R
    
    is_paper = is_paper_trading()
    tr_id = "VTTC0081R" if is_paper else "TTTC0081R"
    
    # We need account info. In kis_auth, it's stored in global vars, but better to fetch or pass.
    # Assuming ka.getTREnv() has account details
    env = ka.getTREnv()
    cano = env.my_acct
    acnt_prdt_cd = env.my_prod
    
    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "INQR_STRT_DT": start_dt, # YYYYMMDD
        "INQR_END_DT": end_dt,    # YYYYMMDD
        "SLL_BUY_DVSN_CD": "00",  # 00: All
        "CCLD_DVSN": "01",        # 01: Executed Only
        "PDNO": symbol,           # Empty for all
        "INQR_DVSN": "00",        # 00: Descending (Latest first)
        "INQR_DVSN_1": "",
        "INQR_DVSN_3": "00",      # 00: All
        "ORD_GNO_BRNO": "",       # Required field: Branch Number
        "ODNO": "",               # Required field: Order Number
        "ORD_DVSN": "00",         # Required field: Order Division (00: All)
        "CTX_AREA_FK100": ctx_area_fk,
        "CTX_AREA_NK100": ctx_area_nk
    }
    
    # Use _url_fetch directly via rate_limiter
    return rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/trading/inquire-daily-ccld", tr_id, "", params)

def fetch_period_profit(start_dt: str, end_dt: str, ctx_area_fk: str = "", ctx_area_nk: str = "") -> Any:
    """
    Wrapper for inquire-period-profit (Period Profit Analysis)
    TR_ID: TTTC8708R (Real) or VTTC8708R (Paper)
    URL: /uapi/domestic-stock/v1/trading/inquire-period-profit
    """
    is_paper = is_paper_trading()
    # tr_id = "VTTC8708R" if is_paper else "TTTC8708R"
    # Try TTTC8708R for both first (Some TRs are shared or I can't find the V code)
    tr_id = "TTTC8708R"
    
    env = ka.getTREnv()
    cano = env.my_acct
    acnt_prdt_cd = env.my_prod
    
    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "INQR_STRT_DT": start_dt,
        "INQR_END_DT": end_dt,
        "SORT_DVSN": "00",        # 00: Descending
        "INQR_DVSN": "00",        # 00: All
        "CBLC_DVSN": "00",        # 00: All
        # "PDNO": "",             # Strip if empty
        # "CTX_AREA_FK100": ctx_area_fk,
        # "CTX_AREA_NK100": ctx_area_nk
    }
    
    if ctx_area_fk: params["CTX_AREA_FK100"] = ctx_area_fk
    if ctx_area_nk: params["CTX_AREA_NK100"] = ctx_area_nk
    
    # PDNO is optional, some APIs error if sent as empty string
    # But domestic_stock_functions.py sends it.
    # Let's try sending it ONLY if not empty.
    
    return rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/trading/inquire-period-profit", tr_id, "", params)
