
import sys
import os
import logging
import pandas as pd

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import kis_api as ka
from core.market_data import MarketData
from core.broker import Broker
import kis_auth

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    # 1. Inspect Account Info for VPS
    logger.info("--- Inspecting Account Info ---")
    ka.auth(svr="vps")
    env = ka.getTREnv()
    logger.info(f"Environment: VPS")
    logger.info(f"App Key (masked): {env.my_app[:4]}****")
    logger.info(f"Account No (masked): {env.my_acct[:4]}****")
    logger.info(f"Product Code: {env.my_prod}")
    
    # Check if Account No looks like valid 8 digits
    if len(env.my_acct) != 8:
        logger.error(f"Account Number length seems wrong: {len(env.my_acct)}")

    # 2. Inspect Market Data (Volume Issue)
    logger.info("\n--- Inspecting Market Data (Volume) ---")
    md = MarketData()
    symbol = "005930" # Samsung Electronics
    
    logger.info(f"Fetching 1m bars for {symbol}...")
    bars = md.get_bars(symbol, timeframe="1m", lookback=20)
    
    if bars.empty:
        logger.error("No bars returned!")
    else:
        logger.info(f"Returned {len(bars)} bars.")
        logger.info("Last 20 bars Volume:")
        print(bars[['time', 'close', 'volume']].tail(20))
        
        # Calculate Logic
        vol_now = bars['volume'].iloc[-1]
        vol_mean_20 = bars['volume'].iloc[-20:].mean()
        
        logger.info(f"Vol Now: {vol_now}")
        logger.info(f"Vol Mean(20): {vol_mean_20}")
        if vol_mean_20 > 0:
            logger.info(f"Ratio: {vol_now / vol_mean_20}")
        else:
            logger.info("Ratio: Inf (Mean=0)")

if __name__ == "__main__":
    main()
