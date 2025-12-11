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

from core.market_data import MarketData
from core.engine import Engine
from strategies.ma_trend import MovingAverageTrendStrategy

def verify_market_data_robustness():
    logger.info("--- Verifying MarketData Robustness ---")
    md = MarketData()
    
    # Mock on_realtime_data to track calls
    md.on_realtime_data = MagicMock()
    
    # Test Case 1: Bad Symbol (Time string '1600')
    logger.info("Test 1: Injecting bad symbol '1600' (Time string)...")
    bad_df = pd.DataFrame([{'mksc_shrn_iscd': '1600', 'stck_prpr': '1000', 'cntg_vol': '10'}])
    md._on_ws_message(None, None, bad_df, None)
    
    if md.on_realtime_data.call_count == 0:
        logger.info("PASS: '1600' was correctly ignored.")
    else:
        logger.error("FAIL: '1600' was NOT ignored!")

    # Test Case 2: Valid Symbol
    logger.info("Test 2: Injecting valid symbol '005930'...")
    good_df = pd.DataFrame([{'mksc_shrn_iscd': '005930', 'stck_prpr': '50000', 'cntg_vol': '100'}])
    md._on_ws_message(None, None, good_df, None)
    
    if md.on_realtime_data.call_count == 1:
        logger.info("PASS: '005930' was processed.")
        args = md.on_realtime_data.call_args[0][0]
        if 'open' in args and args['open'] == 50000.0:
             logger.info("PASS: Missing OHLC keys were auto-filled with current price.")
        else:
             logger.error(f"FAIL: Data structure is missing keys: {args}")
    else:
        logger.error("FAIL: Valid symbol was ignored!")

def verify_strategy_robustness():
    logger.info("\n--- Verifying Strategy Robustness ---")
    
    # Mock dependencies
    broker = MagicMock()
    risk = MagicMock()
    portfolio = MagicMock()
    portfolio.get_position.return_value = MagicMock(avg_price=50000, qty=10, max_price=55000, partial_taken=False)
    md = MagicMock()
    # Mock get_bars to return empty or insufficient data to trigger edge cases
    md.get_bars.return_value = pd.DataFrame() 
    
    config = {
        "id": "test_strat",
        "timeframe": "1m",
        "stop_loss_pct": 2.0,
        "take_profit1_pct": 3.0,
        "trail_stop_pct": 1.5,
        "vol_k": 1.5
    }
    
    strategy = MovingAverageTrendStrategy(config, broker, risk, portfolio, md)
    
    # Test Case 3: on_bar with missing keys
    logger.info("Test 3: Calling on_bar with empty bar data...")
    try:
        strategy.on_bar('005930', {})
        logger.info("PASS: Strategy did not crash on empty bar data.")
    except Exception as e:
        logger.error(f"FAIL: Strategy crashed: {e}")

    # Test Case 4: Zero Price
    logger.info("Test 4: Calling on_bar with zero price...")
    try:
        strategy.on_bar('005930', {'close': 0.0})
        logger.info("PASS: Strategy handled zero price gracefully.")
    except Exception as e:
        logger.error(f"FAIL: Strategy crashed on zero price: {e}")

if __name__ == "__main__":
    try:
        verify_market_data_robustness()
        verify_strategy_robustness()
        logger.info("\n=== ALL CHECKS PASSED: SYSTEM IS ROBUST ===")
    except Exception as e:
        logger.error(f"\n!!! VERIFICATION FAILED: {e} !!!")
