import unittest
from unittest.mock import MagicMock
from datetime import datetime
import pandas as pd
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.visualization import TradeVisualizationService, TradeEvent

class TestTradeVisualization(unittest.TestCase):
    def setUp(self):
        self.engine = MagicMock()
        self.service = TradeVisualizationService(self.engine)

    def test_get_chart_data_structure(self):
        # Mock MarketData
        self.engine.market_data = MagicMock()
        
        # Mock get_bars return value
        mock_df = pd.DataFrame({
            'date': ['20250101', '20250102'],
            'open': [100, 102],
            'high': [105, 106],
            'low': [99, 101],
            'close': [102, 104],
            'volume': [1000, 1200]
        })
        self.engine.market_data.get_bars.return_value = mock_df

        # Mock Trade History
        event = TradeEvent(
            event_id="test_event",
            timestamp=datetime.now(),
            symbol="005930",
            strategy_id="test_strat",
            event_type="ORDER_FILLED",
            side="BUY",
            price=100.0,
            qty=10,
            order_id="ord1"
        )
        self.engine.trade_history = [event]

        # Call method
        data = self.service.get_chart_data("005930", "D")

        # Assertions
        self.assertEqual(data["symbol"], "005930")
        self.assertEqual(data["timeframe"], "D")
        self.assertEqual(len(data["candles"]), 2)
        self.assertEqual(len(data["markers"]), 1)
        
        # Check Candle Structure
        candle = data["candles"][0]
        self.assertIn("time", candle)
        self.assertIn("open", candle)
        self.assertEqual(candle["open"], 100)
        
        # Check Marker Structure
        marker = data["markers"][0]
        self.assertEqual(marker["event_id"], "test_event")
        self.assertEqual(marker["side"], "BUY")

if __name__ == '__main__':
    unittest.main()
