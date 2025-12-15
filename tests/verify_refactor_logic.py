import unittest
from unittest.mock import MagicMock
import sys
import os
import logging

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.base import BaseStrategy
from strategies.ma_trend import MovingAverageTrendStrategy
from core.portfolio import Position

# Mock Logger to capture output
logging.basicConfig(level=logging.INFO)

class TestRefactoring(unittest.TestCase):
    def setUp(self):
        self.broker = MagicMock()
        self.risk = MagicMock()
        self.portfolio = MagicMock()
        self.portfolio.get_account_value.return_value = 100000000 # 1 Billion KRW (1억)
        self.portfolio.get_position.return_value = None
        
        self.market_data = MagicMock()
        self.market_data.get_last_price.return_value = 10000.0
        self.market_data.get_stock_name.return_value = "TestStock"
        
        # Risk returns True by default
        self.risk.can_open_new_position.return_value = True

    def test_calculate_buy_quantity_new_entry(self):
        """TC1: New Entry (0 holdings) -> Should buy Risk %"""
        print("\n[TC1] New Entry Test")
        config = {"risk_pct": 0.03, "target_weight": 0.10, "enabled": True}
        
        # We can use a dummy strategy that inherits BaseStrategy
        class DummyStrategy(BaseStrategy):
            def on_bar(self, s, b): pass
            
        strategy = DummyStrategy(config, self.broker, self.risk, self.portfolio, self.market_data)
        
        # Price 10,000
        # Equity 100,000,000
        # Risk 3% -> 3,000,000
        # Qty -> 300
        
        qty = strategy.calculate_buy_quantity("005930", 10000.0)
        print(f"Calculated Qty: {qty}")
        
        self.assertEqual(qty, 300)
        print(">> PASS: Correctly calculated initial risk quantity")

    def test_calculate_buy_quantity_addon_normal(self):
        """TC2: Add-on (Hold 3%, Target 10%) -> Should buy Risk % (Step)"""
        print("\n[TC2] Add-on Normal Test")
        config = {"risk_pct": 0.03, "target_weight": 0.10, "enabled": True}
        strategy = MovingAverageTrendStrategy(config, self.broker, self.risk, self.portfolio, self.market_data)
        
        # Position: 300 shares * 10,000 = 3,000,000 (3%)
        pos = Position("005930", "Samsung", 300, 10000.0, 10000.0)
        self.portfolio.get_position.return_value = pos
        
        # Target: 10,000,000
        # Current: 3,000,000
        # Deficit: 7,000,000 (700 shares)
        # Risk Step: 3,000,000 (300 shares)
        # Min(700, 300) = 300
        
        qty = strategy.calculate_buy_quantity("005930", 10000.0)
        print(f"Calculated Qty: {qty} (Expected 300)")
        
        self.assertEqual(qty, 300)
        print(">> PASS: Add-on limited by Risk Step")

    def test_calculate_buy_quantity_addon_capped(self):
        """TC3: Add-on Capped (Hold 8%, Target 10%) -> Should buy Deficit"""
        print("\n[TC3] Add-on Capped Test")
        config = {"risk_pct": 0.03, "target_weight": 0.10, "enabled": True}
        class DummyStrategy(BaseStrategy):
            def on_bar(self, s, b): pass
        strategy = DummyStrategy(config, self.broker, self.risk, self.portfolio, self.market_data)
        
        # Position: 800 shares * 10,000 = 8,000,000 (8%)
        pos = Position("005930", "Samsung", 800, 10000.0, 10000.0)
        self.portfolio.get_position.return_value = pos
        
        # Target: 10,000,000
        # Current: 8,000,000
        # Deficit: 2,000,000 (200 shares)
        # Risk Step: 3,000,000 (300 shares)
        # Min(200, 300) = 200
        
        qty = strategy.calculate_buy_quantity("005930", 10000.0)
        print(f"Calculated Qty: {qty} (Expected 200)")
        
        self.assertEqual(qty, 200)
        print(">> PASS: Add-on limited by Deficit (Target Weight)")

    def test_ma_trend_integration_signal(self):
        """TC4: Integration Test - MA Trend Logic Ordering"""
        print("\n[TC4] MA Trend Logic Integration")
        # Ensure buy is called ONLY when signal is True
        config = {
            "id": "ma_trend", "enabled": True, "timeframe": "1m",
            "target_weight": 0.10, "risk_pct": 0.03, "vol_k": 1.0
        }
        strategy = MovingAverageTrendStrategy(config, self.broker, self.risk, self.portfolio, self.market_data)
        
        # 1. No Signal Case
        # Mock Data: Flat line, no cross
        import pandas as pd
        bars = pd.DataFrame({'close': [10000]*30, 'volume': [1000]*30})
        self.market_data.get_bars.return_value = bars
        self.market_data.check_rate_limit.return_value = True
        
        strategy.on_bar("005930", {'close': 10000})
        self.broker.buy_market.assert_not_called()
        print(">> PASS: No buy when no signal")
        
        # 2. Signal Case
        # GOLDEN CROSS: MA5 > MA20
        # Create bars where last 5 avg > last 20 avg
        # and prev 5 avg <= prev 20 avg
        closes = [10000.0] * 30
        closes[-1] = 10500.0 # Jump to cross
        # Vol boost
        vols = [1000] * 30
        vols[-1] = 2000
        
        bars = pd.DataFrame({'close': closes, 'volume': vols})
        self.market_data.get_bars.side_effect = [
            bars, # 1m
            pd.DataFrame({'close': [10000]*30}) # 1d (Trend UP)
        ]
        
        # Reset Mock
        self.portfolio.get_position.return_value = None # New Entry
        
        strategy.on_bar("005930", {'close': 10500.0})
        
        # Should buy 300 shares (Risk 3%)? 
        # Price is 10500. Equity 100M. 3% = 3M. 
        # 3,000,000 / 10,500 = 285 shares
        
        self.broker.buy_market.assert_called()
        args, _ = self.broker.buy_market.call_args
        qty = args[1]
        print(f"Signal Triggered Buy Qty: {qty}")
        self.assertTrue(qty > 0)
        print(">> PASS: Buy triggered on signal")

if __name__ == '__main__':
    unittest.main()
