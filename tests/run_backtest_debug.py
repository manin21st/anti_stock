
import sys
import os
import traceback

# Add project root to path
sys.path.append(os.getcwd())

try:
    from core.engine import Engine
    from strategies.ma_trend import MovingAverageTrendStrategy
except ImportError as e:
    with open("debug_error.txt", "w") as f:
        f.write(f"ImportError: {e}\n{traceback.format_exc()}")
    sys.exit(1)

def main():
    try:
        with open("debug_status.txt", "w") as f:
            f.write("Starting...\n")
            
        engine = Engine()
        engine.register_strategy(MovingAverageTrendStrategy, "ma_trend")
        
        with open("debug_status.txt", "a") as f:
            f.write("Engine Initialized. Running Backtest...\n")
            
        result = engine.run_backtest(
            strategy_id="ma_trend",
            symbol="005930",
            start_date="20251209", # recent dates
            end_date="20251211",
            initial_cash=100000000,
            strategy_config={"timeframe": "3m"}
        )
        
        with open("debug_result.txt", "w") as f:
            f.write(str(result))
            
    except Exception as e:
        with open("debug_error.txt", "w") as f:
            f.write(f"Exception: {str(e)}\n{traceback.format_exc()}")

if __name__ == "__main__":
    main()
