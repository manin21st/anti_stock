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
        self.max_calls = 10  # Max calls per window
        self.window = 1.0    # Window size in seconds
        self.calls = []      # List of timestamps
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            
            # Remove calls older than window
            self.calls = [t for t in self.calls if now - t < self.window]
            
            if len(self.calls) >= self.max_calls:
                # Calculate sleep time to wait until the current window theoretically ends
                # or just wait for the full window duration to be safe if we want to "reset"
                # Strategy: Wait until the oldest call expires, or force a small sleep?
                # User requested: "Window가 초기화될 때까지 강제 지연"
                
                # Option 1: Sliding Window (Strict) - Wait until separate calls expire
                # sleep_time = self.window - (now - self.calls[0])
                
                # Option 2: Bucket Reset (Simpler/User's preference?) - Wait remainder of window
                # If we hit 10 calls in 0.1s, we wait 0.9s.
                
                # Let's use a safe logic:
                earliest_call = self.calls[0]
                sleep_time = self.window - (now - earliest_call)
                
                if sleep_time < 0.05:
                    sleep_time = 0.05 # Minimum penalty
                
                logger.debug(f"Rate Limit Hit ({len(self.calls)} reqs). Sleeping {sleep_time:.3f}s")
                time.sleep(sleep_time)
                
                # After sleep, we can clear calls or re-evaluate.
                # If we clear, we allow a fresh burst.
                self.calls = [] 
                now = time.time() # Update now

            self.calls.append(now)

# Global Instance
rate_limiter = RateLimiter()

def auth():
    """Wrapper for kis_auth.auth"""
    ka.auth()

def is_paper_trading():
    return ka.isPaperTrading()

def get_tr_env():
    return ka.getTREnv()

def fetch_price(symbol: str) -> Dict[str, Any]:
    """
    Wrapper for inquire-price (Current Price)
    TR_ID: FHKST01010100
    """
    rate_limiter.wait()
    
    tr_id = "FHKST01010100"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": symbol
    }
    
    res = ka._url_fetch("/uapi/domestic-stock/v1/quotations/inquire-price", tr_id, "", params)
    
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
    rate_limiter.wait()
    
    tr_id = "FHKST03010100"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": symbol,
        "FID_INPUT_DATE_1": start_dt,
        "FID_INPUT_DATE_2": end_dt,
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "1"
    }
    
    res = ka._url_fetch("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", tr_id, "", params)
    return res

def fetch_minute_chart(symbol: str, current_time: str) -> Any:
    """
    Wrapper for inquire-time-itemchartprice
    TR_ID: FHKST03010200
    """
    rate_limiter.wait()
    
    tr_id = "FHKST03010200"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": symbol,
        "FID_INPUT_HOUR_1": current_time,
        "FID_PW_DATA_INCU_YN": "Y",
        "FID_ETC_CLS_CODE": ""
    }
    
    res = ka._url_fetch("/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice", tr_id, "", params)
    return res

def send_order(tr_id: str, params: Dict[str, str]) -> Any:
    """
    Wrapper for order-cash
    """
    rate_limiter.wait()
    
    # postFlag=True is standard for orders
    res = ka._url_fetch("/uapi/domestic-stock/v1/trading/order-cash", tr_id, "", params, postFlag=True)
    return res

def get_balance(tr_id: str, params: Dict[str, str]) -> Any:
    """
    Wrapper for inquire-balance
    """
    rate_limiter.wait()
    
    res = ka._url_fetch("/uapi/domestic-stock/v1/trading/inquire-balance", tr_id, "", params)
    return res
