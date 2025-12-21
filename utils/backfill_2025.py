import sys
import os
import logging
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import Engine

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

def main():
    logger.info("Starting Backfill for 2025...")
    
    # Initialize Engine (config load & auth)
    engine = Engine()
    
    # Define Period (2025-11-01 ~ Today)
    start_date = "20251101"
    end_date = datetime.now().strftime("%Y%m%d")
    
    logger.info(f"Syncing Trade History: {start_date} ~ {end_date}")
    
    # Run Sync
    try:
        count = engine.sync_trade_history(start_date, end_date)
        logger.info(f"Backfill Complete. Processed {count} new trades/updates.")
        
        # Reload to verify
        logger.info("Verifying local storage...")
        engine.load_trade_history()
        logger.info(f"Total Trade Events in Local DB: {len(engine.trade_history)}")
        
    except KeyboardInterrupt:
        logger.warning("\n[!] Operation Cancelled by User (KeyboardInterrupt).")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Backfill Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
