import unittest
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from unittest.mock import MagicMock
from strategies.ma_trend import MovingAverageTrendStrategy
from core.portfolio import Position

class TestTrailingStop(unittest.TestCase):
    def setUp(self):
        # Mock Dependencies
        self.market_data = MagicMock()
        self.market_data.get_stock_name.return_value = "삼성전자"
        self.market_data.simulation_date = None # Real-time mode equivalent
        
        self.broker = MagicMock()
        self.portfolio = MagicMock()
        self.risk = MagicMock()
        
        self.config = {
            "id": "ma_trend",
            "trail_activation_pct": 0.03, # 3% Activation
            "trail_stop_pct": 0.015,      # 1.5% Callback
            "stop_loss_pct": 0.02,
            "take_profit1_pct": 0.20,
            "target_weight": 0.1,
            "timeframe": "1m"
        }
        
        self.strategy = MovingAverageTrendStrategy(
            self.config, self.broker, self.risk, self.portfolio, self.market_data
        )
        self.strategy.logger = MagicMock() # Capture logs

    def test_trailing_stop_normal_profit(self):
        """Scenario 1: Buy 100k -> Peak 110k -> Drop 106k (Profit) -> SELL"""
        print("\n--- Test Scenario 1: Normal Profit Trailing Stop ---")
        symbol = "005930"
        
        # Setup Position: Buy @ 100,000, Peak @ 110,000
        # Setup trailing stop activation: 100k * 1.03 = 103k. 110k > 103k. OK.
        pos = Position(symbol, "삼성전자", 10, 100000, 100000, max_price=110000)
        self.portfolio.get_position.return_value = pos
        
        # Current Price: 106,000
        # Drawdown: (106k - 110k) / 110k = -3.6% < -1.5%. Trigger condition met.
        # Check Safety: 106k > 100k. OK.
        
        bar = {'close': 106000, 'volume': 100000}
        self.strategy.on_bar(symbol, bar)
        
        # Verify Sell
        self.broker.sell_market.assert_called_once()
        print("[OK] Trailing Stop Triggered correctly (Profit secured).")
        args = self.strategy.logger.info.call_args[0][0]
        # print(f"Log: {args}")

    def test_trailing_stop_loss_prevention(self):
        """Scenario 2: Buy 100k -> Peak 104k -> Gap Down 99k (Loss) -> NO SELL"""
        print("\n--- Test Scenario 2: Loss Prevention Safety Check ---")
        symbol = "005930"
        
        # Setup Position: Buy @ 100,000, Peak @ 104,000
        # Activation: 103k. Peak 104k > 103k. Activated.
        pos = Position(symbol, "삼성전자", 10, 100000, 100000, max_price=104000)
        self.portfolio.get_position.return_value = pos
        self.broker.reset_mock()
        
        # Current Price: 99,000 (Gap Down)
        # Drawdown: (99k - 104k) / 104k = -4.8% < -1.5%. Trigger condition met.
        # Check Safety: 99k < 100k. FAIL safety check.
        
        bar = {'close': 99000, 'volume': 100000}
        self.strategy.on_bar(symbol, bar)
        
        # Verify NO Sell
        self.broker.sell_market.assert_not_called()
        print("[OK] Trailing Stop BLOCKED correctly (Loss prevention).")
        # Ensure log explains? Or silent return?
        # Current logic returns silently. 
        # print("No log expected.")

if __name__ == '__main__':
    unittest.main()
