import logging
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.data_loader import DataLoader
from core import kis_api as ka

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DataDownload")

def download_data():
    # 1. Auth is required for download
    # Since we are running standalone, we need to auth manually.
    # Assumption: User has valid secrets.yaml
    try:
        print("Authenticating for download...")
        ka.auth(svr="vps") 
    except Exception as e:
        print(f"Auth failed: {e}")
        # Proceeding? download_data inside DataLoader has extra auth check but might fail if secrets are missing
        return

    dl = DataLoader()
    symbol = "034020" # Doosan Enerbility
    start_date = "20251101"
    end_date = "20251227"

    print(f"Downloading minute data for {symbol} ({start_date} ~ {end_date})...")
    # By default, downloading '1m' is enough, Backtester will resample to 15m
    dl.download_data(symbol, start_date, end_date, timeframe="1m")
    
    # Also download Daily data just in case
    print(f"Downloading daily data for {symbol}...")
    dl.download_data(symbol, start_date, end_date, timeframe="D")
    
    print("Download complete.")

if __name__ == "__main__":
    download_data()
