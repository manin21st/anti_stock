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

        logger.debug(f"[RateLimiter] Initialized with TPS_LIMIT={self.tps_limit} (Interval: {self.min_interval:.3f}s)")
        # Check if we should try to use server (if explicitly set or default)
        # We will try lazily in execute

    def set_limit(self, tps_limit: float):
        """Update TPS Limit dynamically"""
        with self.lock:
            self.tps_limit = float(tps_limit)
            self.min_interval = 1.0 / max(self.tps_limit, 0.1)
            logger.debug(f"[RateLimiter] Limit updated to TPS={self.tps_limit} (Interval: {self.min_interval:.3f}s)")

    def set_server_url(self, url: str):
        """Update TPS Server URL dynamically"""
        with self.lock:
            if url and url != self.server_url:
                self.server_url = url.rstrip('/') # Normalize
                self.server_alive = True # Reset status to try new URL
                self.logged_server_error = False
                logger.debug(f"[RateLimiter] Server URL updated to: {self.server_url}")

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
            # Increased timeout to 1.0s to prevent flapping during burst requests (e.g. Watchlist load)
            resp = requests.get(f"{self.server_url}/token", headers=headers, timeout=1.0)

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

    def get_server_stats(self) -> Dict[str, Any]:
        """Fetch statistics from TPS Server"""
        if not self.use_server and self.server_url == "http://localhost:9000":
             return {"status": "local", "current_tps": self.tps_limit}

        try:
            headers = {"X-Client-ID": self.client_id}
            resp = requests.get(f"{self.server_url}/stats", headers=headers, timeout=1.0)
            if resp.status_code == 200:
                stats = resp.json()
                stats["status"] = "running" # Ensure status is present
                return stats
            else:
                 return {"status": "error", "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "offline", "message": str(e)}

    def wait_for_tps(self):
        """Block until TPS Server is connected"""
        logger.info("[RateLimiter] TPS 서버 연결 대기 중... (Strict Mode)")
        while True:
            # Try to fetch token just to check connectivity
            status = self._request_token_from_server()
            if status is not None:
                # Connected (Whether token granted or not, server is alive)
                logger.info("[RateLimiter] TPS 서버 연결 성공! 시스템을 시작합니다.")
                return
            time.sleep(1.0) # Retry interval

    def execute(self, func, *args, **kwargs):
        """
        Executes the function with Rate Limiting Lock held.
        STRICT MODE: Only execute if TPS Server facilitates it.
        """
        max_retries = 3
        attempt = 0

        should_retry = True
        while should_retry:

            # Phase 1: Acquire Token from Server (Blocking until success)
            token_granted = False

            while not token_granted:
                # IMPORTANT: DO NOT SLEEP INSIDE LOCK
                # Request token logic should be fast.
                # If server connection hangs, requests.get timeout handles it.

                # Removed lock here to allow concurrent token requests
                server_status = self._request_token_from_server()

                if server_status is True:
                    token_granted = True
                elif server_status is False:
                     # Server said limit exceeded, wait a bit
                     time.sleep(0.1)
                else:
                     # Server Error / Unreachable
                     # In Strict Mode, we DO NOT fall back. We WAIT.
                     if not self.logged_server_error:
                         logger.warning("[RateLimiter] TPS 서버 연결 끊김. 대기 중...")
                         self.logged_server_error = True

                     time.sleep(1.0)

            # Token Granted. Reset error flag if we recovered
            if self.logged_server_error:
                logger.info("[RateLimiter] TPS 서버 재연결됨.")
                self.logged_server_error = False

            # Phase 2: Execute
            # Removed lock around execution to allow concurrency

            result = None
            exception = None
            is_rate_limit = False
            is_expired_token = False

            try:
                # Do NOT suppress output to avoid I/O on closed file in threads
                result = func(*args, **kwargs)

                # Check for Rate Limit Error (EGW00201)
                if hasattr(result, 'getErrorCode') and result.getErrorCode() == "EGW00201":
                    is_rate_limit = True
                elif hasattr(result, 'getErrorMessage'):
                        msg = result.getErrorMessage()
                        if msg and "EGW00201" in msg:
                            is_rate_limit = True

                # Check for Expired Token (EGW00123)
                if hasattr(result, 'getErrorCode') and result.getErrorCode() == "EGW00123":
                    is_expired_token = True
                elif hasattr(result, 'getErrorMessage'):
                    msg = result.getErrorMessage()
                    if msg and "EGW00123" in msg:
                        is_expired_token = True

                if is_expired_token and attempt < max_retries:
                    # Re-auth needs locking to prevent race conditions
                    with self.lock:
                        logger.debug(f"[RateLimiter] Token expired (EGW00123). Re-authenticating...")
                        try:
                            if hasattr(ka, 'token_tmp') and os.path.exists(ka.token_tmp):
                                os.remove(ka.token_tmp)
                        except Exception:
                            pass

                        svr = "vps" if ka.isPaperTrading() else "prod"
                        ka.auth(svr=svr)
                        self.last_call_time = time.time()

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                exception = e
                if attempt < max_retries:
                        is_rate_limit = True # Treat connection error as reason to retry
                else:
                    raise e
            except Exception as e:
                raise e

            # Phase 3: Handle Results & Retries

            if is_rate_limit:
                # [Strict Mode] Infinite Retry for Rate Limits
                backoff_time = 2.0 + random.uniform(0.0, 1.0)
                logger.debug(f"[RateLimiter] Rate limit exceeded (EGW00201). Backing off {backoff_time:.2f}s and retrying...")
                time.sleep(backoff_time)
                # Do NOT increment attempt count to prevent exhaustion for Rate Limit
                continue

            if is_expired_token:
                attempt += 1
                continue

            if exception:
                if attempt < max_retries:
                    time.sleep(1.0 * (attempt + 1))
                    attempt += 1
                    continue
                else:
                    raise exception

            # Return success or failure result
            return result

        return None

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
    """
    Check if running in Paper Trading (VPS) mode by inspecting the API URL.
    Robust against kis_auth internal changes.
    """
    try:
        env = ka.getTREnv()
        url = getattr(env, 'my_url', '')
        if url and "openapivts" in url:
            return True
        return False
    except Exception:
        # Fallback
        return False


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
    tr_id = "VTTC8708R" if is_paper else "TTTC8708R"
    # tr_id = "TTTC8708R"

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
        "CTX_AREA_FK100": ctx_area_fk,
        "CTX_AREA_NK100": ctx_area_nk
    }

    # PDNO is optional, some APIs error if sent as empty string
    # But domestic_stock_functions.py sends it.
    # Let's try sending it ONLY if not empty.

    return rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/trading/inquire-period-profit", tr_id, "", params)
