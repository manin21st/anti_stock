import sys
import os
import pandas as pd
import numpy as np
import logging

# Configure Logging to ignore actual logs during test
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(message)s')

# Add project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from strategies.ma_trend import MovingAverageTrendStrategy
from core.portfolio import Portfolio
from core.risk_manager import RiskManager

# Mocks
class MockBroker:
    def __init__(self):
        self.orders = []
    def buy_market(self, symbol, qty, tag=""):
        self.orders.append({"symbol": symbol, "qty": qty, "tag": tag})
        print(f"[MockBroker] BUY {symbol} {qty}")

class MockMarketData:
    def __init__(self):
        self.bars = {}
        self.daily = {}
    def get_bars(self, symbol, timeframe):
        if timeframe == "1d": return self.daily.get(symbol)
        
        # In strategies/ma_trend.py, it calls get_bars(symbol, timeframe=self.config["timeframe"])
        # We assume timeframe matches what we set
        return self.bars.get(symbol)
        
    def get_stock_name(self, symbol):
        return "TestStock"

class MockRiskManager:
    def can_open_new_position(self, symbol, qty, price):
        return True

class MockStrategy(MovingAverageTrendStrategy):
    def __init__(self, config):
        self.config = config
        self.config.setdefault("timeframe", "1m")
        self.config.setdefault("ma_short", 5)
        self.config.setdefault("ma_long", 20)
        self.config.setdefault("whipsaw_threshold", 0.0) # default logic
        self.config.setdefault("cross_lookback", 1) # default logic
        self.config.setdefault("vol_k", 1.5)
        self.config.setdefault("target_weight", 0.1)
        self.config.setdefault("risk_pct", 0.03)
        self.config.setdefault("id", "test_ma")
        
        self.broker = MockBroker()
        self.market_data = MockMarketData()
        self.risk = MockRiskManager()
        self.portfolio = Portfolio() 
        self.portfolio.cash = 10000000
        self.portfolio.deposit_d2 = 10000000
        self.logger = logging.getLogger("Test")

    def calculate_buy_quantity(self, symbol, price):
        return 10 # Fixed qty for test

    def check_rate_limit(self, symbol, interval_seconds=60):
        return True # Always allow for tests

# Helper to create bars
def create_bars(prices, volumes):
    df = pd.DataFrame({
        'close': prices,
        'volume': volumes
    })
    return df

def run_tests():
    print("=== Starting Simulation Tests for Whipsaw & Persistent Cross ===")
    
    # 1. Test Persistent Cross (Delayed Volume)
    # Scenario: 
    # T-3: MA5 < MA20
    # T-2 (Cross): MA5 > MA20 (Golden Cross), BUT Volume Low (Entry Fail in old logic)
    # T-1: MA5 > MA20 (Uptrend), Volume Low
    # T-0: MA5 > MA20 (Uptrend), Volume Explosion! -> SHOULD BUY with cross_lookback=3
    
    print("\n[Test 1] Persistent Cross (Delayed Volume)")
    strategy = MockStrategy({
        "whipsaw_threshold": 0.0,
        "cross_lookback": 3,
        "ma_short": 2, # Use small MAs for easy manual calc
        "ma_long": 5
    })
    
    # Setup Daily (Bullish) to pass filter
    daily_prices = [1000] * 30
    strategy.market_data.daily["TEST"] = create_bars(daily_prices, [1000]*30)
    
    # Intraday Data Construction
    # We need enough history for MA calculation (20 bars min)
    # Prices: 100 steady, then jump to cross
    prices = [100] * 20 
    volumes = [100] * 20
    
    # T-2: Price Jump 110 -> MA2=[105, 110], MA5=[100*4+110/5] = 102. Cross!
    # Volume 100 (Avg 100) -> Ratio 1.0 < 1.5 (Fail)
    prices.append(110) 
    volumes.append(100)
    
    # T-1: Price 110 -> MA2=110, MA5=[100*3+110*2/5] = 104. Uptrend.
    # Volume 100 -> Fail
    prices.append(110)
    volumes.append(100)
    
    # T-0: Price 110 -> Uptrend.
    # Volume 1000 -> Ratio 10.0 > 1.5 -> Success!
    prices.append(110)
    volumes.append(1000)
    
    strategy.market_data.bars["TEST"] = create_bars(prices, volumes)
    
    # Run
    strategy.on_bar("TEST", {})
    
    if len(strategy.broker.orders) == 1:
        print("PASS: Order placed on delayed volume.")
    else:
        print(f"FAIL: Expected 1 order, got {len(strategy.broker.orders)}")

    # 2. Test Whipsaw Filter
    # Scenario: Golden Cross + Volume OK, BUT Price is only 0.1% above MA20 (Threshold 0.2%)
    print("\n[Test 2] Whipsaw Filter (Weak Breakout)")
    strategy2 = MockStrategy({
        "whipsaw_threshold": 0.002, # 0.2%
        "cross_lookback": 1,
        "ma_short": 2,
        "ma_long": 5
    })
    strategy2.market_data.daily["TEST"] = create_bars([1000]*30, [1000]*30)
    
    prices = [10000] * 20
    volumes = [100] * 20
    
    # T-0: Breakout
    # MA Long (5) roughly 10000
    # Price needs to be 10020 for 0.2%
    # We set price to 10010 (0.1%)
    prices.append(10010)
    volumes.append(1000) # Volume OK
    
    strategy2.market_data.bars["TEST"] = create_bars(prices, volumes)
    
    strategy2.on_bar("TEST", {})
    
    if len(strategy2.broker.orders) == 0:
        print("PASS: Order blocked by Whipsaw Filter (0.1% < 0.2%).")
    else:
        print("FAIL: Order was placed despite weak breakout.")

    # 3. Test Whipsaw Filter Success
    # Scenario: Price 10030 (0.3% > 0.2%)
    print("\n[Test 3] Whipsaw Filter (Strong Breakout)")
    
    # Clear orders
    strategy2.broker.orders = []
    
    # Reuse config but new data
    prices = [10000] * 20
    volumes = [100] * 20
    prices.append(10030) # 0.3% > 0.2%
    volumes.append(1000)
    
    strategy2.market_data.bars["TEST"] = create_bars(prices, volumes)
    strategy2.on_bar("TEST", {})
    
    if len(strategy2.broker.orders) == 1:
        print("PASS: Order placed on strong breakout.")
    else:
        print(f"FAIL: Order blocked/not placed. Orders: {len(strategy2.broker.orders)}")

if __name__ == "__main__":
    run_tests()
