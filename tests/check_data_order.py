import sys
import os
import logging
import pandas as pd

# Setup Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.data_loader import DataLoader

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_order():
    loader = DataLoader()
    symbol = "005930"
    # Use the date range we know exists and was problematic
    start = "20241129" 
    end = "20241129"
    
    logger.info(f"Loading data for {symbol} ({start} ~ {end})...")
    df = loader.load_data(symbol, start, end, timeframe="1m")
    
    if df.empty:
        logger.error("No data loaded.")
        return

    logger.info(f"Loaded {len(df)} rows.")
    
    # Check strict monotonicity
    df['datetime'] = pd.to_datetime(df['date'] + df['time'], format='%Y%m%d%H%M%S')
    
    is_sorted = df['datetime'].is_monotonic_increasing
    
    if is_sorted:
        logger.info("✅ Data is correctly sorted.")
        # Print first few rows to confirm visual check
        print(df[['date', 'time', 'close']].head(10))
    else:
        logger.error("❌ Data is NOT sorted!")
        # Find where it breaks
        for i in range(1, len(df)):
            if df.iloc[i]['datetime'] < df.iloc[i-1]['datetime']:
                logger.error(f"Order break at index {i}:")
                logger.error(f"Prev: {df.iloc[i-1]['date']} {df.iloc[i-1]['time']}")
                logger.error(f"Curr: {df.iloc[i]['date']} {df.iloc[i]['time']}")
                break

if __name__ == "__main__":
    check_order()
