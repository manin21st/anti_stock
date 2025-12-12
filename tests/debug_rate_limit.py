import logging
import sys
import os
import time
import threading

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import kis_api as ka

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("debug_rate_limit.log", encoding='utf-8')
    ]
)
logger = logging.getLogger("DebugRateLimit")

def test_auth_and_call():
    logger.info("1. Starting Auth...")
    start_time = time.time()
    ka.auth()
    logger.info(f"Auth completed in {time.time() - start_time:.4f}s")
    
    # Check if RateLimiter tracked this? (We suspect it didn't)
    logger.info(f"RateLimiter Last Call Time: {ka.rate_limiter.last_call_time}")
    
    logger.info("2. Attempting Immediate API Call (Volume Rank)...")
    # Simulate Scanner call
    tr_id = "FHPST01710000"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_COND_SCR_DIV_CODE": "20171",
        "FID_INPUT_ISCD": "0000",
        "FID_DIV_CLS_CODE": "0",
        "FID_BLNG_CLS_CODE": "0",
        "FID_TRGT_CLS_CODE": "111111111",
        "FID_TRGT_EXLS_CLS_CODE": "000000",
        "FID_INPUT_PRICE_1": "",
        "FID_INPUT_PRICE_2": "",
        "FID_VOL_CNT": "",
        "FID_INPUT_DATE_1": ""
    }
    
    try:
        res = ka.issue_request("/uapi/domestic-stock/v1/quotations/volume-rank", tr_id, "", params)
        if res.isOK():
            logger.info("API Call SUCCESS")
        else:
            logger.error(f"API Call FAILED: {res.getErrorMessage()}")
            logger.error(f"Error Code: {res.getErrorCode()}")
            if hasattr(res, 'getBody'):
                 logger.error(f"Body: {res.getBody()}")
                 
    except Exception as e:
        logger.error(f"Exception during API call: {e}")

def test_rapid_calls():
    logger.info("3. Testing Rapid Calls (Rate Limiter Check)...")
    symbols = ["005930", "000660", "035420"]
    
    for sym in symbols:
        logger.info(f"Requesting {sym}...")
        res = ka.fetch_price(sym)
        if res:
            logger.info(f"Success {sym}: {res.get('stck_prpr')}")
        else:
            logger.error(f"Fail {sym}")

if __name__ == "__main__":
    test_auth_and_call()
    time.sleep(2)
    test_rapid_calls()
