
import logging
import sys
import os
import pandas as pd
from datetime import datetime, timedelta

# Add project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.data_loader import DataLoader
from core.engine import Engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_data_loader():
    logger.info("Verifying DataLoader minute data fetching...")
    dl = DataLoader()
    
    # Test Parameters
    symbol = "005930" # Samsung Electronics
    today = datetime.now()
    end_date = today.strftime("%Y%m%d")
    start_date = (today - timedelta(days=2)).strftime("%Y%m%d") # Last 3 days
    
    # KIS API limits check? 
    # Just try fetching 1 day.
    # If today is weekend, go back to friday.
    while today.weekday() >= 5:
        today -= timedelta(days=1)
    
    end_date = today.strftime("%Y%m%d")
    start_date = end_date # Just 1 day for test speed
    
    logger.info(f"Target Date: {start_date}")
    
    # 1. Download Minute Data
    df = dl.download_data(symbol, start_date, end_date, timeframe="1m")
    
    if df.empty:
        logger.error("Failed to download minute data. Check API or Date.")
        return
        
    logger.info(f"Downloaded {len(df)} rows.")
    logger.info(f"Head:\n{df.head()}")
    logger.info(f"Tail:\n{df.tail()}")
    
    # Verify Columns
    required = ['date', 'time', 'open', 'high', 'low', 'close', 'volume']
    if not all(col in df.columns for col in required):
        logger.error(f"Missing columns. Found: {df.columns}")
        return
        
    # Verify Time Continuity (Sample)
    # Check if we have 090000 and 153000 roughly
    times = df['time'].sort_values().unique()
    logger.info(f"Time Range: {times[0]} ~ {times[-1]}")
    
    # 2. Test Resampling (Engine Logic Mock)
    logger.info("Testing Resampling to 5m...")
    df['datetime'] = pd.to_datetime(df['date'] + df['time'], format="%Y%m%d%H%M%S")
    df = df.set_index('datetime').sort_index()
    
    metric = "5T"
    resampled = df.resample(metric).agg({
        'date': 'first',
        'time': 'last',
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    
    logger.info(f"Resampled to {len(resampled)} rows.")
    logger.info(f"Resampled Head:\n{resampled.head()}")
    
    # Check a specific bar time
    # 09:00:00 -> 09:05:00 bar should have label 09:00:00 or 09:05:00 depending on "label" and "closed"
    # wrapper uses default.
    # Default: bin 09:00:00 <= t < 09:05:00 has label 09:00:00
    
    logger.info("Verification Complete.")

if __name__ == "__main__":
    verify_data_loader()
