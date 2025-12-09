
import sys
import os
import logging
import time

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import kis_api as ka
from core.market_data import MarketData
import kis_auth

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting verification...")
    
    # 1. Test Auth & Token Refresh
    logger.info("Testing Auth & Token Refresh...")
    try:
        # Initial Auth (Use VPS to match user environment)
        ka.auth(svr="vps")
        logger.info("Initial Auth (VPS) successful.")
        
        # Simulate Token Expiration by corrupting the token file?
        # Or just test that deleting the file works.
        token_file = kis_auth.token_tmp
    except Exception as e:
        logger.error(f"Auth test failed: {e}")

    # 2. Test MarketData Stock Name
    md = MarketData()
    symbols = ["005930", "000660"]
    for symbol in symbols:
        name = md.get_stock_name(symbol)
        logger.info(f"Stock Name Check: {symbol} -> {name}")
        # Debug hex to check encoding
        logger.info(f"Hex: {name.encode('utf-8').hex()}")

if __name__ == "__main__":
    main()
