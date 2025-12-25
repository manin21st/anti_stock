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
    def __init__(self, is_simulation: bool = False):
        self.bars: Dict[str, pd.DataFrame] = {} # symbol -> DataFrame (OHLCV)
        self._daily_cache: Dict[str, Dict] = {} # symbol -> {'data': df, 'timestamp': time}
        self._name_cache: Dict[str, str] = {} # symbol -> name
        self.subscribers: List[Callable] = []
        self.ws = None
        self.simulation_date = None
        self.data_loader = DataLoader()
        self.is_polling = False # Initialize polling state
        self.polling_symbols = [] # Initialize list

        # Skip API/WS initialization in simulation mode
        if not is_simulation:
            self._initialize_api()

        # Initialize Stock Master Data in background to avoid blocking
        if not is_simulation:
             threading.Thread(target=self._load_master_files, daemon=True).start()
        else:
             # In simulation, we might still need names, but blocking is less critical.
             # Or just load it.
             try:
                 self._load_master_files()
             except Exception:
                 pass

    def _initialize_api(self):
        """Initialize KIS API authentication"""
        # Authentication is handled centrally by Engine/Main to ensure consistency (Token/Env)
        # ka.auth()
        # ka.auth_ws()
        self.ws = ka.KISWebSocket(api_url="/tryitout")

    def _load_master_files(self):
        """Download and Parse KOSPI/KOSDAQ Master Files"""
        try:
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

            logger.debug(f"Loaded Master Files: KOSPI({cnt_kospi}), KOSDAQ({cnt_kosdaq})")
        except Exception as e:
            logger.error(f"Failed to load master files: {e}")

    def _download_file(self, url, save_dir, filename):
        ssl._create_default_https_context = ssl._create_unverified_context
        file_path = os.path.join(save_dir, filename)

        should_download = True
        if os.path.exists(file_path):
            created = datetime.fromtimestamp(os.path.getmtime(file_path))
            if created.date() == datetime.now().date():
                should_download = False

        if should_download:
            logger.debug(f"Downloading {filename}...")
            urllib.request.urlretrieve(url, file_path)

            # Extract
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(save_dir)

    def _parse_kospi_master(self, base_dir):
        file_path = os.path.join(base_dir, "kospi_code.mst")
        if not os.path.exists(file_path): return 0

        count = 0
        with open(file_path, mode="rb") as f:
            for row in f:
                try:
                    if len(row) < 50: continue

                    upper_bound = len(row) - 228
                    if upper_bound <= 21: continue

                    code_bytes = row[0:9]
                    name_bytes = row[21:upper_bound]

                    code = code_bytes.decode('ascii', errors='ignore').strip()
                    name = name_bytes.decode('cp949', errors='ignore').strip()

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
        with open(file_path, mode="rb") as f:
            for row in f:
                try:
                    # KOSDAQ: Last 222 bytes are tail
                    if len(row) < 50: continue

                    upper_bound = len(row) - 222
                    if upper_bound <= 21: continue

                    code_bytes = row[0:9]
                    name_bytes = row[21:upper_bound]

                    code = code_bytes.decode('ascii', errors='ignore').strip()
                    name = name_bytes.decode('cp949', errors='ignore').strip()

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
            df = self.data_loader.load_data(symbol, timeframe=timeframe)
            if df.empty:
                return pd.DataFrame()

            # Filter up to simulation_date
            if len(self.simulation_date) > 8 and 'time' in df.columns:
                # Intraday Simulation (YYYYMMDDHHMMSS)
                sim_dt = int(self.simulation_date) # YYYYMMDDHHMMSS
                # Create integer datetime for comparison (faster than pd.to_datetime)
                df['dt_int'] = (df['date'].astype(str) + df['time'].astype(str)).astype(int)
                df = df[df['dt_int'] <= sim_dt].drop(columns=['dt_int'])
            else:
                df = df[df['date'] <= self.simulation_date[:8]]

            return df.tail(lookback)

        env_dv = "demo" if ka.isPaperTrading() else "real"

        if timeframe == "1d":
            # Daily bars
            end_dt = datetime.now().strftime("%Y%m%d")
            start_dt = (datetime.now() - timedelta(days=int(lookback * 3))).strftime("%Y%m%d")

            # Check Cache (TTL: 60 seconds)
            cache_key = f"{symbol}_1d_{lookback}"
            cached = self._daily_cache.get(cache_key)
            if cached:
                if (time.time() - cached['timestamp'] < 60) and (cached['date'] == end_dt):
                    return cached['data']

            logger.debug(f"Fetching daily bars for {symbol}: {start_dt} ~ {end_dt} (lookback={lookback})")

            # API FETCH LOGIC
            all_df_list = []
            fetched_count = 0
            current_end_dt = end_dt

            while fetched_count < lookback:
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
            now_str = datetime.now().strftime("%H%M%S")
            if now_str < "083000":
                target_time = "153000"
            else:
                target_time = min(now_str, "153000")

            collected_count = 0
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

                if len(df_page) == 0:
                    break

                all_dfs.append(df_page)
                collected_count += len(df_page)
                page_count += 1

                df_page = df_page.sort_values("time")
                oldest_time = df_page.iloc[0]["time"]

                try:
                    dt = datetime.strptime(oldest_time, "%H%M%S")
                    dt = dt - timedelta(minutes=1)
                    next_target = dt.strftime("%H%M%S")
                except ValueError:
                    break

                if next_target >= target_time:
                     break

                target_time = next_target

                if target_time < "090000":
                    break

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
        """Round-robin polling loop with smart throttling"""
        while self.is_polling:
            if not self.polling_symbols:
                time.sleep(1)
                continue

            symbols_to_poll = list(self.polling_symbols)

            # Default Sleep
            safe_interval = 0.5

            for symbol in symbols_to_poll:
                if not self.is_polling:
                    break

                try:
                    self._fetch_and_publish(symbol)
                except Exception as e:
                    # Detect Rate Limit Error from Exception message if raised
                    # But RateLimiter usually suppresses exception and returns None/Error Object
                    # In _fetch_and_publish, we use fetch_price which uses rate_limiter.execute

                    # RateLimiter now logs EGW00201 warning.
                    # We can't easily detect it here unless fetch_price returns a specific error code.
                    # But if RateLimiter is backing off, this loop will naturally slow down because
                    # _fetch_and_publish will block for 2+ seconds inside RateLimiter (sleeping).
                    # Now that RateLimiter sleeps OUTSIDE the lock, it's safe!

                    logger.error(f"Polling error for {symbol}: {e}")

                # Strict sleep to respect rate limits
                time.sleep(safe_interval)


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

        return symbol

    def get_master_list(self) -> List[Dict]:
        """Return full list of stocks from master files (KOSPI + KOSDAQ)"""
        return [{"code": code, "name": name} for code, name in self._name_cache.items()]
