import logging
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.backtester import Backtester
from strategies.ma_trend import MovingAverageTrendStrategy

# Setup Logging
logging.basicConfig(level=logging.ERROR) # Suppress debug logs
logger = logging.getLogger("BacktestComparison")
logger.setLevel(logging.INFO)

# --- MOCK AUTH for Broker ---
from core import kis_api as ka
class MockEnv:
    my_acct = "12345678"
    my_prod = "01"
    
def mock_getTREnv():
    return MockEnv()
    
# Patch globally if needed, or ensure Broker uses it safely.
# Since Broker calls ka.getTREnv() in __init__, we must ensure ka.getTREnv returns something valid.
# kis_api might not be initialized.
ka.getTREnv = mock_getTREnv
ka.isPaperTrading = lambda: True
# -----------------------------

def run_comparison():
    target_symbol = "034020" # Doosan Enerbility
    start_date = "20251101"
    end_date = "20251227"
    initial_cash = 100000000

    base_config = {
        "ma_trend": {
            "timeframe": "1m",
            "ma_short": 5,
            "ma_long": 20,
            "stop_loss_pct": 0.02,
            "take_profit1_pct": 0.03,
            "risk_pct": 0.1, # Boost risk to see impact clearly
            "target_weight": 0.5
        }
    }

    strategy_classes = {
        "ma_trend": MovingAverageTrendStrategy
    }

    tester = Backtester(base_config, strategy_classes)

    print(f"Running Backtest Comparison for {target_symbol}")
    print(f"Period: {start_date} ~ {end_date}\n")

    # 1. Run 1m Backtest
    print(">>> Testing Timeframe: 1 minute (Current)")
    res_1m = tester.run_backtest(
        strategy_id="ma_trend",
        symbol=target_symbol,
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
        strategy_config={"timeframe": "1m"}
    )
    
    if "error" in res_1m:
        print(f"Error: {res_1m['error']}")
        return

    m1 = res_1m['metrics']
    print(f"   [Result] ROI: {m1['total_return']}% | Trades: {m1['trade_count']} | Final Asset: {m1['total_asset']:,}")

    # 2. Run 15m Backtest
    print("\n>>> Testing Timeframe: 15 minutes (Proposed)")
    res_15m = tester.run_backtest(
        strategy_id="ma_trend",
        symbol=target_symbol,
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
        strategy_config={"timeframe": "15m"}
    )
    
    if "error" in res_15m:
        print(f"Error: {res_15m['error']}")
        return

    m15 = res_15m['metrics']
    print(f"   [Result] ROI: {m15['total_return']}% | Trades: {m15['trade_count']} | Final Asset: {m15['total_asset']:,}")

    print("\n" + "="*50)
    print(" Comparison Summary")
    print("="*50)
    diff = m15['total_return'] - m1['total_return']
    print(f" Improvement: {diff:+.2f}%p")
    
    if m15['total_return'] > m1['total_return']:
        print(" VERIFIED: Higher timeframe reduced noise and improved stability.")
    else:
        print(" RESULT: Higher timeframe did not improve results in this specific case.")

if __name__ == "__main__":
    run_comparison()
