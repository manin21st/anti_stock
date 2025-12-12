import pandas as pd
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
import sys
import os
import urllib.request
import ssl
import zipfile

# Add project root to path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import kis_api as ka
from utils.data_loader import DataLoader

logger = logging.getLogger(__name__)

# Debug logging to file
if not os.path.exists("logs"):
    os.makedirs("logs")

debug_handler = logging.FileHandler(os.path.join("logs", "api_debug.log"))
debug_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
debug_handler.setFormatter(formatter)
logger.addHandler(debug_handler)

class MarketData:
    def __init__(self):
        self.bars: Dict[str, pd.DataFrame] = {} # symbol -> DataFrame (OHLCV)
        self._daily_cache: Dict[str, Dict] = {} # symbol -> {'data': df, 'timestamp': time}
        self._name_cache: Dict[str, str] = {} # symbol -> name
        self.subscribers: List[Callable] = []
        self.ws = None
        self.simulation_date = None
        self.data_loader = DataLoader()
        self._initialize_api()
        
        # Initialize Stock Master Data (Async to not block startup too long?)
        # Better to block briefly or do it in background. 
        # Since it's critical for UI/Logs, let's do it here but handle errors gracefully.
        try:
            self._load_master_files()
        except Exception as e:
            logger.error(f"Failed to load master files: {e}")

    def _initialize_api(self):
        """Initialize KIS API authentication"""
        # Authentication is handled centrally by Engine/Main to ensure consistency (Token/Env)
        # ka.auth() 
        # ka.auth_ws() 
        self.ws = ka.KISWebSocket(api_url="/tryitout")
        
    def _load_master_files(self):
        """Download and Parse KOSPI/KOSDAQ Master Files"""
        base_dir = os.path.dirname(os.path.abspath(__file__)) # core/
        data_dir = os.path.join(base_dir, "..", "data", "master") # data/master/
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
            
        # 1. Download
        self._download_file("https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip", data_dir, "kospi_code.zip")
        self._download_file("https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip", data_dir, "kosdaq_code.zip")
        
        # 2. Parse KOSPI
        cnt_kospi = self._parse_kospi_master(data_dir)
        
        # 3. Parse KOSDAQ
        cnt_kosdaq = self._parse_kosdaq_master(data_dir)
        
        logger.info(f"Loaded Master Files: KOSPI({cnt_kospi}), KOSDAQ({cnt_kosdaq})")

    def _download_file(self, url, save_dir, filename):
        ssl._create_default_https_context = ssl._create_unverified_context
        file_path = os.path.join(save_dir, filename)
        
        # Check if file exists and is recent (e.g., today)
        # If exists, skip download to start faster? 
        # Or always download to get latest? Master file updates daily in morning.
        # Let's download if not exists or if old.
        should_download = True
        if os.path.exists(file_path):
            created = datetime.fromtimestamp(os.path.getmtime(file_path))
            if created.date() == datetime.now().date():
                should_download = False
                
        if should_download:
            logger.info(f"Downloading {filename}...")
            urllib.request.urlretrieve(url, file_path)
            
            # Extract
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(save_dir)
                
    def _parse_kospi_master(self, base_dir):
        file_path = os.path.join(base_dir, "kospi_code.mst")
        if not os.path.exists(file_path): return 0
        
        count = 0
        with open(file_path, mode="r", encoding="cp949") as f:
            for row in f:
                # Based on kis_kospi_code_mst.py
                # Short Code(9), Standard Code(12), Name(Remaining)
                # But actually the parsing logic in example was:
                # rf1 = row[0:len(row) - 228]
                # rf1_1 = rf1[0:9].rstrip() (Short)
                # rf1_2 = rf1[9:21].rstrip() (Standard)
                # rf1_3 = rf1[21:].strip() (Name)
                
                # We only need Short Code and Name
                try:
                    # The example logic splits strictly by length from end.
                    # Let's trust the logic: row[:-228] contains the name part.
                    # But if row length is small?
                    part1 = row[:-228]
                    code = part1[0:9].strip()
                    name = part1[21:].strip()
                    
                    if code and name:
                        self._name_cache[code] = name
                        count += 1
                except Exception:
                    continue
        return count

    def _parse_kosdaq_master(self, base_dir):
        file_path = os.path.join(base_dir, "kosdaq_code.mst")
        if not os.path.exists(file_path): return 0
        
        count = 0
        with open(file_path, mode="r", encoding="cp949") as f:
            for row in f:
                # KOSDAQ: row[:-222]
                try:
                    part1 = row[:-222]
                    code = part1[0:9].strip()
                    name = part1[21:].strip()
                    
                    if code and name:
                        self._name_cache[code] = name
                        count += 1
                except Exception:
                    continue
        return count

    def get_bars(self, symbol: str, timeframe: str = "1m", lookback: int = 100) -> pd.DataFrame:
        """
        Get historical bars.
        timeframe: "1m", "3m", "5m", "1d"
        """
        if self.simulation_date:
            # Simulation Mode
            # TODO: caching for performance
            df = self.data_loader.load_data(symbol)
            if df.empty:
                return pd.DataFrame()
            
            # Filter up to simulation_date
            df = df[df['date'] <= self.simulation_date]
            
            # If minute timeframe requested but we only have daily...
            # For now, just return daily if timeframe='1d' or 'D', else... we might return empty or daily?
            # Let's assume if they ask for minute in backtest, we might not support it yet unless we have minute data.
            # But the user asked for simple backtest first.
            
            return df.tail(lookback)

        env_dv = "demo" if ka.isPaperTrading() else "real"
        
        if timeframe == "1d":
            # Daily bars
            end_dt = datetime.now().strftime("%Y%m%d")
            # Increase lookback multiplier to account for weekends/holidays (approx 1.5x trading days + buffer)
            start_dt = (datetime.now() - timedelta(days=int(lookback * 3))).strftime("%Y%m%d") 
            
            # Check Cache (TTL: 60 seconds)
            cache_key = f"{symbol}_1d_{lookback}"
            cached = self._daily_cache.get(cache_key)
            if cached:
                # If cache is fresh (within 60s) AND date matches
                if (time.time() - cached['timestamp'] < 60) and (cached['date'] == end_dt):
                    # logger.debug(f"Using cached daily bars for {symbol}")
                    return cached['data']
 
            logger.debug(f"Fetching daily bars for {symbol}: {start_dt} ~ {end_dt} (lookback={lookback})")
            
            # API FETCH LOGIC (Same as before)
            tr_id = "FHKST03010100" # Daily chart
            
            all_df_list = []
            fetched_count = 0
            current_end_dt = end_dt
            
            while fetched_count < lookback:
                
                params = {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": symbol,
                    "FID_INPUT_DATE_1": start_dt,
                    "FID_INPUT_DATE_2": current_end_dt,
                    "FID_PERIOD_DIV_CODE": "D",
                    "FID_ORG_ADJ_PRC": "1"
                }
                
                res = ka.fetch_daily_chart(symbol, start_dt, current_end_dt)
                
                if res.isOK():
                    chunk_df = pd.DataFrame(res.getBody().output2)
                    if chunk_df.empty:
                        break
                        
                    # Rename columns
                    chunk_df = chunk_df.rename(columns={
                        "stck_bsop_date": "date",
                        "stck_oprc": "open",
                        "stck_hgpr": "high",
                        "stck_lwpr": "low",
                        "stck_clpr": "close",
                        "acml_vol": "volume"
                    })
                    
                    # Convert types
                    cols = ["open", "high", "low", "close", "volume"]
                    chunk_df[cols] = chunk_df[cols].apply(pd.to_numeric)
                    
                    all_df_list.append(chunk_df)
                    fetched_count += len(chunk_df)
                    
                    if len(chunk_df) < 100:
                        pass
                        
                    oldest_date = chunk_df['date'].min()
                    oldest_dt_obj = datetime.strptime(oldest_date, "%Y%m%d")
                    current_end_dt = (oldest_dt_obj - timedelta(days=1)).strftime("%Y%m%d")
                    
                    if current_end_dt < start_dt:
                        break
                else:
                    logger.error(f"Failed to fetch chunk: {res.getErrorMessage()}")
                    break
            
            if all_df_list:
                df = pd.concat(all_df_list).drop_duplicates(subset=['date'])
                df = df.sort_values("date").reset_index(drop=True)
                
                self._daily_cache[cache_key] = {
                    'data': df.tail(lookback),
                    'date': end_dt, 
                    'timestamp': time.time()
                }

                return df.tail(lookback)
            else:
                logger.warning(f"API returned no data for {symbol}. Attempting to load from local storage.")
                df = self.data_loader.load_data(symbol)
                if not df.empty:
                    logger.info(f"Loaded {len(df)} bars from local storage.")
                    return df.tail(lookback)
                return pd.DataFrame()

        elif timeframe in ["1m", "3m", "5m", "10m", "15m", "30m", "60m"]:
            # Minute bars (Intraday)
            all_dfs = []
            
            # Constraint: Domestic Market Closes at 15:30
            # If we request data at night (e.g. 23:00) in VPS, it might return ghost bars (future time with 0 vol).
            # We must clamp the request time to 15:30:00 to get valid historical data.
            now_str = datetime.now().strftime("%H%M%S")
            
            # Fix: If currently night/pre-market (e.g. 00:00 ~ 08:30), 
            # we should fetch from Market Close (15:30) of the previous valid day.
            # KIS API 'inquire-time-itemchartprice' usually gives the latest available intraday data 
            # if we request 153000, even if it's technically 'tomorrow' morning.
            if now_str < "083000":
                target_time = "153000"
            else:
                target_time = min(now_str, "153000")
            
            # Fix 8: Robust Pagination for Large Lookback
            # KIS API typically returns 30 bars per page for minute data.
            # We need to loop until we have enough data or hit a limit.
            
            collected_count = 0
            # Safety limit: 100 pages * 30 = 3000 bars max to prevent infinite loops
            max_pages = 100 
            page_count = 0
            
            while collected_count < lookback and page_count < max_pages:
                res = ka.fetch_minute_chart(symbol, target_time)
                if not res.isOK():
                    logger.warning(f"Failed to fetch minute chart for {symbol} at {target_time}: {res.getErrorMessage()}")
                    break
                    
                df_page = pd.DataFrame(res.getBody().output2)
                if df_page.empty:
                    break
                
                df_page = df_page.rename(columns={
                    "stck_cntg_hour": "time",
                    "stck_oprc": "open",
                    "stck_hgpr": "high",
                    "stck_lwpr": "low",
                    "stck_prpr": "close",
                    "cntg_vol": "volume"
                })
                
                # Check if we got valid data
                if len(df_page) == 0:
                    break
                    
                all_dfs.append(df_page)
                collected_count += len(df_page)
                page_count += 1
                
                # Prepare for next page (older data)
                df_page = df_page.sort_values("time") # Ascending in page to find oldest? 
                # API usually gives descending or we sort it?
                # output2 is typically time descending (newest first). 
                # So last item in list (or first if we didn't sort) is the oldest.
                # Let's check logic: cached logic sorted by time ascending.
                # df_page.iloc[0]["time"] would be the oldest if sorted ascending.
                
                # Prepare for next page (older data)
                df_page = df_page.sort_values("time")
                oldest_time = df_page.iloc[0]["time"]
                
                # Decrement time by 1 minute to avoid overlap/stall
                # Format: HHMMSS
                try:
                    dt = datetime.strptime(oldest_time, "%H%M%S")
                    dt = dt - timedelta(minutes=1)
                    next_target = dt.strftime("%H%M%S")
                except ValueError:
                    # Fallback if time parsing fails
                    break
                
                if next_target >= target_time:
                     # Should not happen with minus 1 min, unless cross day boundary (e.g. 000000 -> 235900)
                     # Since we are Intraday, if we go back past 090000, we stop?
                     break
                
                target_time = next_target
                
                # Check for Market Open (09:00:00)
                # If target < 090000, we can stop for domestic stock
                if target_time < "090000":
                    break
                    
                # Rate Limit
                time.sleep(0.1)

            if not all_dfs:
                 return pd.DataFrame()

            df = pd.concat(all_dfs).drop_duplicates(subset=['time'])
            cols = ["open", "high", "low", "close", "volume"]
            df[cols] = df[cols].apply(pd.to_numeric)
            df = df.sort_values("time").reset_index(drop=True)
            
            if timeframe != "1m":
                today = datetime.now().strftime("%Y%m%d")
                df['datetime'] = pd.to_datetime(today + df['time'], format='%Y%m%d%H%M%S')
                df = df.set_index('datetime')
                
                rule = timeframe.replace('m', 'min')
                df_resampled = df.resample(rule).agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }).dropna()
                return df_resampled.tail(lookback)
            
            return df.tail(lookback)
        
        return pd.DataFrame()

    def subscribe_market_data(self, symbols: List[str]):
        """Register symbols for polling"""
        current_symbols = set(self.polling_symbols if hasattr(self, 'polling_symbols') else [])
        current_symbols.update(symbols)
        self.polling_symbols = list(current_symbols)
        logger.info(f"Updated polling list: {len(self.polling_symbols)} symbols")

    def start_polling(self):
        """Start the polling loop in a background thread"""
        self.is_polling = True
        if not hasattr(self, 'polling_symbols'):
             self.polling_symbols = [] 
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()
        logger.info("Market Data Polling Started")

    def stop_polling(self):
        self.is_polling = False
        if hasattr(self, 'poll_thread'):
            self.poll_thread.join(timeout=2)

    def _poll_loop(self):
        """Round-robin polling loop"""
        while self.is_polling:
            if not self.polling_symbols:
                time.sleep(1)
                continue

            symbols_to_poll = list(self.polling_symbols)
            
            for symbol in symbols_to_poll:
                if not self.is_polling:
                    break
                
                try:
                    self._fetch_and_publish(symbol)
                except Exception as e:
                    logger.error(f"Polling error for {symbol}: {e}")
                
                # time.sleep(1.0) 

    def _fetch_and_publish(self, symbol: str):
        """Fetch current price via REST API and publish to subscribers"""
        # Use FHKST01010100 (Current Price)
        data = ka.fetch_price(symbol)
        
        if data:
            current_price = float(data.get('stck_prpr', 0))
            
            bar_data = {
                "symbol": symbol,
                "price": current_price,
                "volume": int(data.get('acml_vol', 0)),
                "time": datetime.now().strftime("%H%M%S"), 
                "open": float(data.get('stck_oprc', current_price)),
                "high": float(data.get('stck_hgpr', current_price)),
                "low": float(data.get('stck_lwpr', current_price)),
                "close": current_price
            }
            
            self.on_realtime_data(bar_data)

    def on_realtime_data(self, data):
        """Callback for real-time data"""
        for callback in self.subscribers:
            callback(data)
    
    def set_simulation_date(self, date_str: Optional[str]):
        """Set current simulation date (YYYYMMDD) or None to disable"""
        self.simulation_date = date_str
        logger.debug(f"MarketData simulation date set to: {date_str}")

    def get_last_price(self, symbol: str) -> float:
        """Get the latest price for a symbol"""
        if self.simulation_date:
            df = self.get_bars(symbol, timeframe="1d", lookback=1)
            if not df.empty:
                return float(df.iloc[-1]['close'])
            return 0.0

        data = ka.fetch_price(symbol)
        if data:
            return float(data.get("stck_prpr", 0))
        else:
            logger.error(f"Failed to get last price for {symbol}")
            return 0.0

    def get_stock_name(self, symbol: str) -> str:
        """Get stock name from Master File Cache"""
        # 1. Check Cache (Populated from Master File)
        if symbol in self._name_cache:
            return self._name_cache[symbol]
            
        # If not in cache, returning symbol is the safest bet (or 'Unknown')
        return symbol
