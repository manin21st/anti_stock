import sys
import os
import logging
import pandas as pd
from datetime import datetime

# Setup Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.data_loader import DataLoader
from strategies.ma_trend import MovingAverageTrendStrategy
from core.market_data import MarketData
from core.portfolio import Portfolio
from core.broker import Broker
from core.risk_manager import RiskManager

# Mock classes to run strategy in isolation
class MockBroker(Broker):
    def __init__(self):
        self.orders = []
    def buy_market(self, symbol, qty, tag=""):
        print(f"✅ BUY ORDER TRIGGERED: {symbol} {qty} ({tag})")
        self.orders.append("BUY")

class MockPortfolio(Portfolio):
    def get_account_value(self):
        return 100000000
    def get_position(self, symbol):
        return None 
    def save_state(self): pass

# Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("StrategyDebug")

def debug_strategy():
    symbol = "005930"
    start_date = "20241129" # Exists in CSV
    end_date = "20241129"
    
    loader = DataLoader()
    
    # 1. Load Daily Data (Check Trend Filter)
    daily_df = loader.load_data(symbol, timeframe="D")
    logger.info(f"Loaded Daily Data: {len(daily_df)} rows")
    
    # 2. Load Intraday Data
    intraday_df = loader.load_data(symbol, start_date, end_date, timeframe="1m")
    logger.info(f"Loaded Intraday Data: {len(intraday_df)} rows")
    
    # Setup Strategy environment
    market_data = MarketData(is_simulation=True)
    # Be sure to preload data into market_data internal cache if needed, 
    # but base class uses loader directly.
    
    portfolio = MockPortfolio()
    broker = MockBroker()
    risk = RiskManager(portfolio)
    
    config = {
        "id": "test_ma",
        "symbol": symbol,
        "timeframe": "1m",
        "stop_loss_pct": 0.02,
        "take_profit1_pct": 0.03,
        "target_weight": 0.1,
        "risk_per_trade_pct": 0.03,
        "vol_k": 1.5,
        "enabled": True
    }
    
    strategy = MovingAverageTrendStrategy(config, broker, risk, portfolio, market_data)
    
    # Run Step-by-Step
    print("\n--- Starting Simulation ---")
    
    # Filter daily up to simulation point? 
    # Strategy does: get_bars(1d).
    # MarketData filters by simulation_date.
    
    triggered = False
    
    for i in range(20, len(intraday_df)):
        row = intraday_df.iloc[i]
        curr_date = str(row['date'])
        curr_time = str(row['time'])
        
        sim_dt_str = f"{curr_date}{curr_time}"
        market_data.set_simulation_date(sim_dt_str)
        
        # Manually create bar dict
        bar = row.to_dict()
        
        # Check WHY strategy might return early
        # Logic 1: Rate limit (Mock handles)
        # Logic 2: Daily Trend
        
        # We need to peek logic. 
        # Calling strategy.on_bar(symbol, bar)
        
        # Capture logs
        broker.orders = []
        strategy.on_bar(symbol, bar)
        
        if broker.orders:
            triggered = True
            print(f"Triggered at {curr_time}")
            break
            
    if not triggered:
        print("\n[FAIL] No Trades Triggered.")
        
        # Diagnostics
        print("\n--- Diagnostics ---")
        # Check Daily Trend
        market_data.set_simulation_date(f"{start_date}153000") # End of day context
        daily = market_data.get_bars(symbol, timeframe="1d")
        if daily is not None and len(daily) > 20:
            ma20 = daily['close'].rolling(20).mean().iloc[-1]
            ma20_prev = daily['close'].rolling(20).mean().iloc[-2]
            close = daily['close'].iloc[-1]
            print(f"Daily Close: {close}")
            print(f"Daily MA20: {ma20}")
            print(f"Daily MA20 Prev: {ma20_prev}")
            
            if close < ma20:
                print("FAILURE REASON: Daily Close < MA20 (Downtrend)")
            elif ma20 < ma20_prev:
                 print("FAILURE REASON: MA20 is declining (Downtrend)")
            else:
                print("Daily Logic PASS (Uptrend)")
        else:
            print("FAILURE REASON: Insufficient Daily Data")

if __name__ == "__main__":
    debug_strategy()
