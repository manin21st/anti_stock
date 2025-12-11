
import sys
import os
import logging
import json

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import kis_api as ka

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    # Monkeypatch read_token to force fresh token
    ka.ka.read_token = lambda: None
    
    ka.auth()
    
    symbol = "005930" # Samsung Electronics
    logger.info(f"Fetching info for {symbol}...")
    
    # TR_ID: CTPF1604R (Product Info)
    # URL might be /uapi/domestic-stock/v1/quotations/search-stock-info
    # Correct URL for CTPF1604R is usually /uapi/domestic-stock/v1/quotations/search-stock-info
    # Let's try /uapi/domestic-stock/v1/quotations/search-info or similar.
    # Actually, KIS API doc: /uapi/domestic-stock/v1/quotations/search-info -> CTPF1604R ?
    
    # Common endpoint: /uapi/domestic-stock/v1/quotations/search-stock-info
    # TR_ID: CTPF1002R
    
    # Let's try CTPF1002R
    tr_id = "CTPF1002R"
    params = {
        "PRDT_TYPE_CD": "300",
        "PDNO": symbol
    }
    
    res = ka.issue_request("/uapi/domestic-stock/v1/quotations/search-stock-info", tr_id, "", params)
    
    if res.isOK():
        logger.info("Data received:")
        data = res.getBody().output
        for k, v in data.items():
            print(f"{k}: {v}")
            
        if "prdt_name" in data:
            logger.info(f"Name: {data['prdt_name']}")
        if "kor_name" in data: # sometimes CTPF1002R returns kor_name?
             logger.info(f"Kor Name: {data['kor_name']}")
             
    else:
        logger.error(f"Failed: {res.getErrorMessage()}")
        logger.error(f"Code: {res.getErrorCode()}")

if __name__ == "__main__":
    main()
