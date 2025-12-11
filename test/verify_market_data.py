import logging
import sys
import os

# Setup logging to file
log_file = "verify_log.txt"
if os.path.exists(log_file):
    os.remove(log_file)

logging.basicConfig(filename=log_file, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Also write to stdout just in case
console = logging.StreamHandler(sys.stdout)
logger.addHandler(console)

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def log(msg):
    print(msg)
    logging.info(msg)

try:
    log("Importing MarketData...")
    from core.market_data import MarketData
except Exception as e:
    log(f"Failed to import MarketData: {e}")
    sys.exit(1)

def test_market_data():
    log("Initializing MarketData...")
    try:
        md = MarketData()
    except Exception as e:
        log(f"Failed to initialize MarketData: {e}")
        return

    symbol = "005930" # Samsung Electronics

    log(f"\nFetching daily bars for {symbol}...")
    try:
        daily_bars = md.get_bars(symbol, "1d", limit=10)
        log(f"Daily bars result: {len(daily_bars)} bars")
        if not daily_bars.empty:
            log(f"Sample:\n{daily_bars.head(1)}")
        else:
            log("No daily bars returned.")
    except Exception as e:
        log(f"Error fetching daily bars: {e}")

    log(f"\nFetching 1m bars for {symbol}...")
    try:
        min_bars = md.get_bars(symbol, "1m", limit=10)
        log(f"Minute bars result: {len(min_bars)} bars")
        if not min_bars.empty:
            log(f"Sample:\n{min_bars.head(1)}")
        else:
            log("No minute bars returned.")
    except Exception as e:
        log(f"Error fetching minute bars: {e}")

if __name__ == "__main__":
    try:
        test_market_data()
    except Exception as e:
        log(f"Test failed with exception: {e}")
        import traceback
        traceback.print_exc(file=open(log_file, "a"))
