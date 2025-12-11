import sys
import os
import logging
import pandas as pd
from unittest.mock import MagicMock

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from strategies.ma_trend import MovingAverageTrendStrategy

def verify_sell_priority():
    logger.info("--- Verifying Sell Logic Priority ---")
    
    # Mock dependencies
    broker = MagicMock()
    risk = MagicMock()
    portfolio = MagicMock()
    md = MagicMock()
    
    # Scenario:
    # 1. We have a position in '005930'
    # 2. Market Data API is broken/rate-limited (returns empty bars)
    # 3. Current Price is high enough to trigger Take Profit (>3%)
    
    # Setup Position: Avg Price 100, Current Price 105 (5% profit)
    position_mock = MagicMock()
    position_mock.avg_price = 100.0
    position_mock.qty = 10
    position_mock.max_price = 105.0
    position_mock.partial_taken = False
    
    portfolio.get_position.return_value = position_mock
    
    # Setup Market Data: Empty history (Simulating Rate Limit)
    md.get_bars.return_value = pd.DataFrame() 
    
    config = {
        "id": "test_strat",
        "timeframe": "5m",
        "stop_loss_pct": 2.0,
        "take_profit1_pct": 3.0,
        "trail_stop_pct": 1.5,
        "vol_k": 1.5
    }
    
    strategy = MovingAverageTrendStrategy(config, broker, risk, portfolio, md)
    
    # Trigger on_bar with current price 105
    logger.info("Triggering on_bar with Price=105 (5% Profit)...")
    # Note: History is empty, so if logic is wrong, it will return early.
    strategy.on_bar('005930', {'close': 105.0, 'high': 105.0, 'low': 104.0, 'open': 104.0, 'volume': 100})
    
    # Check if Sell was called
    if broker.sell_market.called:
        logger.info("PASS: Broker.sell_market was called!")
        args = broker.sell_market.call_args
        logger.info(f"Sell Args: {args}")
    else:
        logger.error("FAIL: Broker.sell_market was NOT called. Logic is still blocked by missing history.")

if __name__ == "__main__":
    verify_sell_priority()
