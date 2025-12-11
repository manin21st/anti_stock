import time
import threading
import logging
import sys
import os
from typing import Dict, Optional, Any

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Add open-trading-api/examples_user to path to import original kis_auth
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "open-trading-api", "examples_user"))

import kis_auth as ka
import requests
import json

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
        # Target: 2 requests per second (Safe mode for Paper Trading)
        # Interval: 1.0 / 2 = 0.5 seconds
        self.min_interval = 0.5
        self.last_call_time = 0.0
        self.lock = threading.Lock()

    def execute(self, func, *args, **kwargs):
        """
        Executes the function with Rate Limiting Lock held.
        Ensures that no other thread can execute an API call until the interval has passed.
        Includes Adaptive Rate Limiting: Retries on EGW00201.
        """
        max_retries = 3
        
        for attempt in range(max_retries + 1):
            with self.lock:
                # 1. Enforce Interval
                now = time.time()
                elapsed = now - self.last_call_time
                
                if elapsed < self.min_interval:
                    sleep_time = self.min_interval - elapsed
                    # logger.debug(f"Rate Limit Sleep: {sleep_time:.3f}s")
                    time.sleep(sleep_time)
                
                # 2. Execute API Call
                try:
                    result = func(*args, **kwargs)
                    
                    # 3. Check for Rate Limit Error (EGW00201)
                    is_rate_limit = False
                    if hasattr(result, 'getErrorCode') and result.getErrorCode() == "EGW00201":
                        is_rate_limit = True
                    elif hasattr(result, 'getErrorMessage'):
                         # Fallback: Check if error message contains the code (EGW00201)
                         # This handles APIRespError where error code might be HTTP status (e.g. 500)
                         msg = result.getErrorMessage()
                         if msg and "EGW00201" in msg:
                             is_rate_limit = True

                    if is_rate_limit:
                        if attempt < max_retries:
                            logger.warning(f"[RateLimiter] Rate limit exceeded (EGW00201). Backing off 0.5s... (Attempt {attempt+1}/{max_retries})")
                            time.sleep(0.5)
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
                            logger.warning(f"[RateLimiter] Token expired (EGW00123). Re-authenticating... (Attempt {attempt+1}/{max_retries})")
                            # Force Auth logic: Delete token file to ensure fresh token
                            try:
                                if hasattr(ka, 'token_tmp') and os.path.exists(ka.token_tmp):
                                    os.remove(ka.token_tmp)
                                    logger.info(f"[RateLimiter] Deleted token file to force refresh: {ka.token_tmp}")
                            except Exception as e:
                                logger.warning(f"[RateLimiter] Failed to delete token file: {e}")

                            # Force Auth with correct environment
                            svr = "vps" if ka.isPaperTrading() else "prod"
                            ka.auth(svr=svr) # This updates the token
                            
                            # Update timestamp
                            self.last_call_time = time.time()
                            continue # Retry
                        else:
                            logger.error("[RateLimiter] Max retries exceeded for token expiration.")
                    
                    # Update timestamp
                    self.last_call_time = time.time()
                    return result

                except Exception as e:
                    # In case of real exception, update time and raise
                    self.last_call_time = time.time()
                    raise e
                    
# Global Instance
rate_limiter = RateLimiter()

def auth(svr="prod", product=None, url=None, force=False):
    """
    Wrapper for kis_auth.auth
    If force=True, deletes the token file to ensure a fresh token is requested.
    """
    kwargs = {"svr": svr}
    if product is not None:
        kwargs["product"] = product
    if url is not None:
        kwargs["url"] = url
    
    if force:
        # Force refresh by deleting the token file
        try:
            token_file = ka.token_tmp
            if os.path.exists(token_file):
                os.remove(token_file)
                logger.info(f"[RateLimiter] Deleted token file to force refresh: {token_file}")
            else:
                logger.info(f"[RateLimiter] Token file not found (already deleted?): {token_file}")
        except Exception as e:
            logger.warning(f"Failed to delete token file: {e}")
        
    # Auth probably doesn't need strict rate limiting but good to be safe if it calls API
    ka.auth(**kwargs)
    
    # Update RateLimiter timestamp because auth() makes an API call
    if rate_limiter:
        rate_limiter.last_call_time = time.time()
        logger.info(f"[RateLimiter] Auth completed. Timestamp updated to {rate_limiter.last_call_time}")

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

