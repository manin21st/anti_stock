import sys
import os
import pandas as pd
import numpy as np

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from strategies.ma_trend import MovingAverageTrendStrategy
from core.portfolio import Portfolio
from core.risk_manager import RiskManager

# Mock Classes
class MockBroker:
    def buy_market(self, symbol, qty, tag=""):
        print(f"broker.buy_market called: {symbol} Qty:{qty}")

class MockConfig:
    def __init__(self, config_dict):
        self.config = config_dict
    
    def get(self, key, default=None):
        return self.config.get(key, default)
    
    # Allow dictionary-like access
    def __getitem__(self, key):
        return self.config[key]

# Setup Strategy wrapper to test on_bar logic
# We need to mock the 'bars' and 'calculate_buy_quantity' 
# Since on_bar in real code fetches data via self.data_loader or broker, 
# wait, ma_trend.py on_bar gets 'bars' passed to it or fetches it?
# Let's check ma_trend.py structure again.
# It uses self.get_bars(symbol, timeframe) usually or similar.
# Wait, I need to see how ma_trend logic gets bars.
