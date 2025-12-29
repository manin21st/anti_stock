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

# Add open-trading-api/examples_user to path to import original kis_auth
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "open-trading-api", "examples_user"))

import kis_auth as ka

logger = logging.getLogger(__name__)

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
    logger.info(f"[KIS_API] Backtest Mode set to: {mode}")

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

# --- Rate Limiter (Unchanged) ---
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
        self.stopped = False # Shutdown flag

        # Generate Client ID (Hostname + PID)
        import socket
        from collections import deque
        self.client_id = f"{socket.gethostname()}-{os.getpid()}"
        
        # Metrics
        self.pending_count = 0
        self.request_history = deque(maxlen=600) # Store timestamps of processed requests (Last 10 mins max)

        logger.debug(f"[RateLimiter] Initialized with TPS_LIMIT={self.tps_limit} (Interval: {self.min_interval:.3f}s)")

    def stop(self):
        """Signal RateLimiter to stop accepting requests (Shutdown)"""
        with self.lock:
            self.stopped = True
        logger.info("[RateLimiter] Stopping...")

    def set_limit(self, tps_limit: float):
        """Update TPS Limit dynamically"""
        with self.lock:
            self.tps_limit = float(tps_limit)
            self.min_interval = 1.0 / max(self.tps_limit, 0.1)
            logger.debug(f"[RateLimiter] Limit updated to TPS={self.tps_limit} (Interval: {self.min_interval:.3f}s)")
    
    # ... (set_server_url, _request_token -> unchanged)

    # Note: I need to update execute separately or here? 
    # The instruction allows editing a chunk. 
    # I will edit _initialize and add stop first.
    # Then I will edit execute in a separate call or merged?
    # Merged is better if contiguous. But execute is far down (line 192).
    # I will stick to editing _initialize and adding stop first.
    # Wait, the tool is replace_file_content (single chunk).
    # _initialize is lines 84-112.
    # set_limit is 113.
    # I can replace 84-112 to include stop? No, stop should be outside _initialize.
    # I will insert stop after `_initialize`.

    # Wait, replace_file_content works on a block.
    # I will replace lines 99-120 (approx) to add self.stopped and def stop().


    def set_server_url(self, url: str):
        """Update TPS Server URL dynamically"""
        with self.lock:
            if url and url != self.server_url:
                self.server_url = url.rstrip('/') # Normalize
                self.server_alive = True # Reset status to try new URL
                self.logged_server_error = False
                logger.debug(f"[RateLimiter] Server URL updated to: {self.server_url}")

    def _request_token_from_server(self):
        """Request a token from the centralized server."""
        try:
            headers = {"X-Client-ID": self.client_id}
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
                return False

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if not self.logged_server_error:
                logger.warning(f"[RateLimiter] TPS Server Unreachable ({self.server_url}). Connection unstable. Waiting for reconnection...")
                self.logged_server_error = True
            self.server_alive = False
            return None
        except Exception:
            return None

    def get_server_stats(self) -> Dict[str, Any]:
        """Fetch statistics from TPS Server and combine with local metrics"""
        # Estimate local tokens
        elapsed = time.time() - self.last_call_time
        estimated_tokens = min(self.tps_limit, elapsed * self.tps_limit)

        stats = {
            "pending": self.pending_count,
            "processed_1min": 0,
            "current_tps": self.tps_limit,
            "server_alive": self.server_alive,
            "remaining_tokens": estimated_tokens,
            "active_clients": 1
        }

        # Calculate RPM locally
        now = time.time()
        with self.lock:
            # Clean old history
            while self.request_history and now - self.request_history[0] > 60:
                self.request_history.popleft()
            stats["processed_1min"] = len(self.request_history)

        if not self.use_server and self.server_url == "http://localhost:9000":
             stats["status"] = "local"
             return stats

        try:
            headers = {"X-Client-ID": self.client_id}
            resp = requests.get(f"{self.server_url}/stats", headers=headers, timeout=1.0)
            if resp.status_code == 200:
                server_stats = resp.json() # May contain global stats
                stats.update(server_stats) # Merge (Server authoritative for tokens/clients)
                stats["status"] = "running"
                return stats
            else:
                 stats["status"] = "error"
                 stats["message"] = f"HTTP {resp.status_code}"
                 return stats
        except Exception as e:
            stats["status"] = "offline"
            stats["message"] = str(e)
            return stats

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
        # --- Backtest Bypass ---
        if _backtest_mode:
            # Direct execution without rate limiting in backtest mode
            # But the 'func' passed here is usually ka._url_fetch which does network I/O.
            # We should NOT be calling this 'execute' method at all if we are mocking properly at the wrapper level.
            # However, if some code calls issue_request() directly, we should handle it.
            return None # Or mock response? Better to handle in wrappers.

        max_retries = 3
        attempt = 0
        should_retry = True
        
        # Metric Tracking
        with self.lock:
             self.pending_count += 1
        
        try:
            while should_retry:
                # Phase 1: Acquire Token
                token_granted = False
                while not token_granted:
                    server_status = self._request_token_from_server()
                    if server_status is True:
                        token_granted = True
                    elif server_status is False:
                         time.sleep(0.1)
                    else:
                         if not self.logged_server_error:
                             logger.warning("[RateLimiter] TPS 서버 연결 끊김. 대기 중...")
                             self.logged_server_error = True
                         time.sleep(1.0)

                if self.logged_server_error:
                    logger.info("[RateLimiter] TPS 서버 재연결됨.")
                    self.logged_server_error = False

                # Phase 2: Execute
                result = None
                exception = None
                is_rate_limit = False
                is_expired_token = False

                try:
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
                            is_rate_limit = True 
                    else:
                        raise e
                except Exception as e:
                    raise e

                # Phase 3: Retry Logic
                if is_rate_limit:
                    if attempt >= max_retries:
                        logger.error(f"[RateLimiter] Max retries ({max_retries}) exceeded for Rate Limit (EGW00201). Request dropped.")
                        # Stop the loop, return None or raise
                        # If we return None, the caller gets None.
                        break 
                    
                    attempt += 1
                    backoff_time = 2.0 + random.uniform(0.0, 1.0)
                    logger.debug(f"[RateLimiter] Rate limit exceeded (EGW00201). Backing off {backoff_time:.2f}s and retrying... (Attempt {attempt}/{max_retries})")
                    time.sleep(backoff_time)
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

                # Success - Record Metric
                with self.lock:
                    self.request_history.append(time.time())
                return result
            return None
        finally:
            with self.lock:
                 self.pending_count -= 1

rate_limiter = RateLimiter()

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

    ka.auth(**kwargs)
    if rate_limiter:
        rate_limiter.last_call_time = time.time()

def auth_ws(svr="prod", product=None):
    if _backtest_mode:
        return
    kwargs = {"svr": svr}
    if product is not None:
        kwargs["product"] = product
    ka.auth_ws(**kwargs)

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
        logger.debug(f"[KIS_API Backtest] Blocked request to {api_url}")
        class MockResponse:
            def isOK(self): return True
            def getBody(self): return type('Body', (), {"output": []})()
        return MockResponse()

    return rate_limiter.execute(ka._url_fetch, api_url, ptr_id, tr_cont, params, appendHeaders, postFlag, hashFlag)

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
    res = rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/quotations/inquire-price", tr_id, "", params)
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
    return rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", tr_id, "", params)

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
    return rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice", tr_id, "", params)

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
    return rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice", tr_id, "", params)

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

    return rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/trading/order-cash", tr_id, "", params, postFlag=True)

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

    return rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/trading/inquire-balance", tr_id, "", params)

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
    return rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/trading/inquire-daily-ccld", tr_id, "", params)

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
    return rate_limiter.execute(ka._url_fetch, "/uapi/domestic-stock/v1/trading/inquire-period-profit", tr_id, "", params)
