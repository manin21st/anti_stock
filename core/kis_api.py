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
        """
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
            finally:
                # 3. Update Timestamp (after execution start, or before? 
                # Updating here means interval starts AFTER call returns. 
                # This is safer but slower. 
                # If we want interval between REQUESTS, update before call.
                # Let's update before call to maximize throughput while respecting rate limit.
                pass
            
            self.last_call_time = time.time()
            return result

# Global Instance
rate_limiter = RateLimiter()

def auth(svr="prod", product=None, url=None):
    """Wrapper for kis_auth.auth"""
    kwargs = {"svr": svr}
    if product is not None:
        kwargs["product"] = product
    if url is not None:
        kwargs["url"] = url
        
    # Auth probably doesn't need strict rate limiting but good to be safe if it calls API
    ka.auth(**kwargs)

def is_paper_trading():
    return ka.isPaperTrading()

def get_tr_env():
    return ka.getTREnv()

def get_env():
    return ka.getEnv()

# Aliases for compatibility
getTREnv = get_tr_env
isPaperTrading = is_paper_trading

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
