import sys
import os
import logging
from datetime import datetime, timedelta
import calendar

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import Engine

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

def get_month_ranges(start_year=2025, start_month=1):
    now = datetime.now()
    current_year = now.year
    current_month = now.month
    
    ranges = []
    
    y = start_year
    m = start_month
    
    while True:
        if y > current_year or (y == current_year and m > current_month):
            break
            
        # Last day of month
        last_day = calendar.monthrange(y, m)[1]
        
        start_date = datetime(y, m, 1)
        end_date = datetime(y, m, last_day)
        
        # Cap at today
        if end_date > now:
            end_date = now
        
        s_str = start_date.strftime("%Y%m%d")
        e_str = end_date.strftime("%Y%m%d")
        
        ranges.append((s_str, e_str))
        
        # Next month
        m += 1
        if m > 12:
            m = 1
            y += 1
            
    return ranges

def main():
    logger.info("Starting Safe Chunked Backfill for 2025...")
    
    # Initialize Engine (config load & auth)
    try:
        engine = Engine()
    except Exception as e:
        logger.error(f"Engine Initialization Failed: {e}")
        return

    ranges = get_month_ranges()
    total_new = 0
    
    for s_date, e_date in ranges:
        logger.info(f"Processing Period: {s_date} ~ {e_date}")
        try:
            # Sync Trade History (Trades + PnL)
            count = engine.sync_trade_history(s_date, e_date)
            total_new += count
            logger.info(f" -> Completed. New Trades: {count}")
        except Exception as e:
            logger.error(f"Failed to sync period {s_date}~{e_date}: {e}")
            import traceback
            traceback.print_exc()
            # Continue to next month?
            # Yes, try to salvage other months
        
        # Sleep slightly to reuse connection/token or just be nice
        import time
        time.sleep(1)

    logger.info(f"All chunks processed. Total New Trades: {total_new}")
    
    # Final Verify
    logger.info("Verifying local storage...")
    engine.load_trade_history()
    logger.info(f"Total Trade Events in Local DB: {len(engine.trade_history)}")

if __name__ == "__main__":
    main()
