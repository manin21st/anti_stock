import sys
import os
import pandas as pd
import logging

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.market_data import MarketData
from utils import kis_auth as ka

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_trend(symbol="005930"):
    md = MarketData()
    print(f"Fetching daily bars for {symbol}...")
    daily = md.get_bars(symbol, timeframe="1d", lookback=30)
    
    if daily.empty:
        print("Failed to fetch daily bars.")
        return

    print(f"\nData fetched: {len(daily)} bars")
    print(daily.tail())

    if len(daily) < 20:
        print("Not enough data for MA20")
        return

    # MA20 Calculation
    ma20_daily_now = daily.close.iloc[-20:].mean()
    ma20_daily_prev = daily.close.iloc[-21:-1].mean()
    current_close = daily.close.iloc[-1]
    
    print(f"\n--- MA Trend Analysis ---")
    print(f"Current Close: {current_close}")
    print(f"MA20 (Now): {ma20_daily_now:.2f}")
    print(f"MA20 (Prev): {ma20_daily_prev:.2f}")
    
    # Logic
    ma_rising = ma20_daily_now > ma20_daily_prev
    price_above_ma = current_close > ma20_daily_now
    trend_up = ma_rising and price_above_ma
    
    print(f"\nCondition 1: MA20 Rising? {ma_rising}")
    print(f"Condition 2: Price > MA20? {price_above_ma}")
    print(f"FINAL RESULT (trend_up): {trend_up}")

if __name__ == "__main__":
    check_trend()
