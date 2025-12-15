import sys
import os
import logging

# Setup Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import Engine
from strategies.ma_trend import MovingAverageTrendStrategy

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_offline_backtest():
    logger.info("Initializing Engine...")
    # NOTE: Engine init tries to auth. This will succeed locally or fail but catch exception.
    # We want to verified run_backtest uses ISOLATED MarketData.
    
    engine = Engine()
    engine.register_strategy(MovingAverageTrendStrategy, "ma_trend")
    
    # Mock MarketData in Engine to be sure? 
    # No, run_backtest creates its OWN instance. 
    # "sim_market = MarketData(is_simulation=True)"
    
    symbol = "005930" # Samsung Electronics (Exists)
    start_date = "20241202"
    end_date = "20241202"
    strategy_id = "ma_trend"
    
    logger.info(f"Running Backtest for {symbol}...")
    try:
        result = engine.run_backtest(strategy_id, symbol, start_date, end_date, initial_cash=100000000)
        
        if "error" in result:
            logger.error(f"Backtest returned error: {result['error']}")
            sys.exit(1)
            
        logger.info("Backtest Completed Successfully.")
        logger.info(f"Trade Count: {result['metrics']['trade_count']}")
        logger.info(f"Total Return: {result['metrics']['total_return']}%")
        
        # Verify Daily Stats populated
        stats = result.get('daily_stats', [])
        logger.info(f"Daily Stats Count: {len(stats)}")
        
    except Exception as e:
        logger.error(f"Backtest Crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    test_offline_backtest()
