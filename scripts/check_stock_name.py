
import sys
import os
import logging

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import kis_api as ka

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    # Auth
    # Monkeypatch read_token to force fresh token
    ka.ka.read_token = lambda: None
    
    ka.auth()
    
    symbol = "005930" # Samsung Electronics
    logger.info(f"Fetching price for {symbol}...")
    
    # fetch_price returns dict
    data = ka.fetch_price(symbol)
    
    if data:
        logger.info("Data received:")
        for k, v in data.items():
            print(f"{k}: {v}")
            
        # Check for likely name fields
        candidates = ["rprs_mrkt_kor_name", "hts_kor_isnm", "kor_isnm", "isnm", "stck_shrn_iscd"]
        found = False
        for c in candidates:
            if c in data:
                logger.info(f"Possible name field found: {c} = {data[c]}")
                found = True
        
        if not found:
            logger.warning("No obvious name field found in fetch_price response.")
    else:
        logger.error("No data received.")

if __name__ == "__main__":
    main()
