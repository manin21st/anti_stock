import pandas as pd
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any, Union
import sys
import os
import urllib.request
import ssl
import zipfile

# Add project root to path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import interface as ka
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
        self.data_loader = DataLoader() # Still used for local fallback in real mode? Or explicit use?
        self.is_polling = False
        self.polling_symbols = []

        # Initialize API (Token) only if NOT in backtest mode (handled by engine/main usually, but safe to call)
        # Ideally, Ka initialization handles itself.
        self._initialize_api()

        # Initialize Stock Master Data in background
        # In Backtest mode, we might skip this or do it synchronously if needed.
        # But since we removed 'is_simulation' flag, we just do it.
        # If network is mocked, this might fail, so we wrap in try-except.
        threading.Thread(target=self._load_master_files, daemon=True).start()

    def _initialize_api(self):
        """Initialize KIS API authentication"""
        # In backtest mode (detected inside kis_api), this mock-class returns immediately.
        self.ws = ka.KISWebSocket(api_url="/tryitout")

    def _load_master_files(self):
        """Download and Parse KOSPI/KOSDAQ Master Files"""
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__)) # core/
            data_dir = os.path.join(base_dir, "..", "data", "master") # data/master/
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)

            # 1. Download (Only if not in backtest... but here we don't know backtest mode easily)
            # kis_api has 'is_paper_trading', but not 'is_backtest' exposed directly via getter?
            # We assume if network fails, we just skip.
            try:
                self._download_file("https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip", data_dir, "kospi_code.zip")
                self._download_file("https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip", data_dir, "kosdaq_code.zip")
            except Exception as e:
                logger.warning(f"Skipping master file download (Network offline/Backtest?): {e}")

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
        if timeframe == "1d":
            # Daily bars
            now = datetime.now()
            is_weekend = now.weekday() >= 5
            
            # 주말인 경우 end_dt를 금요일로 조정하여 불필요한 API 오류 방지
            if is_weekend:
                if now.weekday() == 5: # 토요일 -> 금요일
                    effective_now = now - timedelta(days=1)
                else: # 일요일 -> 금요일
                    effective_now = now - timedelta(days=2)
                end_dt = effective_now.strftime("%Y%m%d")
            else:
                end_dt = now.strftime("%Y%m%d")
                
            start_dt = (datetime.now() - timedelta(days=int(lookback * 3))).strftime("%Y%m%d")

            # Check Cache (TTL: Weekends=1 hour, Weekdays=1 minute)
            cache_ttl = 3600 if is_weekend else 60
            cache_key = f"{symbol}_1d_{lookback}"
            cached = self._daily_cache.get(cache_key)
            if cached:
                if (time.time() - cached['timestamp'] < cache_ttl) and (cached['date'] == end_dt):
                    return cached['data']

            logger.debug(f"Fetching daily bars for {symbol}: {start_dt} ~ {end_dt} (lookback={lookback})")

            all_df_list = []
            fetched_count = 0
            current_end_dt = end_dt

            api_failed = False
            while fetched_count < lookback:
                res = ka.fetch_daily_chart(symbol, start_dt, current_end_dt)
                
                chunk_df = pd.DataFrame()
                
                # Retrieve Data from Response (Real vs Mock)
                if isinstance(res, list): # Mock Return Type
                     chunk_df = pd.DataFrame(res)
                elif hasattr(res, 'isOK') and res.isOK(): # Real API
                     chunk_df = pd.DataFrame(res.getBody().output2)
                else:
                    err_msg = res.getErrorMessage() if hasattr(res, 'getErrorMessage') else 'Unknown error'
                    err_code = res.getErrorCode() if hasattr(res, 'getErrorCode') else 'Unknown code'
                    status_code = getattr(res, '_rescode', 200)
                    
                    # 주말 500 에러는 WARNING으로 처리 (서버 점검 가능성 높음)
                    log_fn = logger.warning if (is_weekend or status_code == 500) else logger.error
                    log_fn(f"Failed to fetch daily chunk for {symbol}: [{err_code}] {err_msg}")
                    api_failed = True
                    break

                if chunk_df.empty:
                    break

                # Rename columns if needed
                if 'stck_bsop_date' in chunk_df.columns:
                    chunk_df = chunk_df.rename(columns={
                        "stck_bsop_date": "date",
                        "stck_oprc": "open",
                        "stck_hgpr": "high",
                        "stck_lwpr": "low",
                        "stck_clpr": "close",
                        "acml_vol": "volume"
                    })
                
                # Type Conversion
                cols = ["open", "high", "low", "close", "volume"]
                existing_cols = [c for c in cols if c in chunk_df.columns]
                if existing_cols:
                    chunk_df[existing_cols] = chunk_df[existing_cols].apply(pd.to_numeric)

                all_df_list.append(chunk_df)
                fetched_count += len(chunk_df)

                # Pagination Logic updates current_end_dt
                if 'date' in chunk_df.columns and not chunk_df.empty:
                    oldest_date = chunk_df['date'].min()
                    try:
                        oldest_dt_obj = datetime.strptime(str(oldest_date), "%Y%m%d")
                        current_end_dt = (oldest_dt_obj - timedelta(days=1)).strftime("%Y%m%d")
                    except ValueError:
                         break
                else:
                    break
                
                if current_end_dt < start_dt:
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
            
            # API 실패 시 로컬 데이터 폴백 시도
            if api_failed or not all_df_list:
                logger.debug(f"Attempting local fallback for {symbol} (Daily)")
                local_df = self.data_loader.load_data(symbol, start_dt, end_dt, timeframe="D")
                if not local_df.empty:
                    logger.info(f"Loaded local fallback data for {symbol} ({len(local_df)} bars)")
                    return local_df.tail(lookback)

            # 최후의 수단으로 빈 프레임 반환
            return pd.DataFrame()

        elif timeframe in ["1m", "3m", "5m", "10m", "15m", "30m", "60m"]:
            # Minute bars (Intraday)
            all_dfs = []
            now_str = datetime.now().strftime("%H%M%S")
            # In backtest mode, ka.fetch_minute_chart checks mock time, but we call it with now_str here?
            # Wait, fetch_minute_chart internal logic relies on 'current_time' arg.
            # In existing code, it passed '153000' or now_str.
            # For backtest, we might want to respect the 'simulated now'.
            # But MarketData doesn't know simulation state anymore.
            # The 'ka.fetch_minute_chart' wrapper receives 'current_time'.
            # If it's real time passed, the mock wrapper should ignore it or use it as 'to_time'.
            # My 'kis_api' wrapper uses the argument passed.
            
            target_time = "153000" if now_str < "083000" else min(now_str, "153000")
            
            collected_count = 0
            max_pages = 100
            page_count = 0

            while collected_count < lookback and page_count < max_pages:
                res = ka.fetch_minute_chart(symbol, target_time)
                
                df_page = pd.DataFrame()
                if isinstance(res, list):
                     df_page = pd.DataFrame(res)
                elif hasattr(res, 'isOK') and res.isOK():
                     df_page = pd.DataFrame(res.getBody().output2)
                else:
                    err_msg = res.getErrorMessage() if hasattr(res, 'getErrorMessage') else 'Unknown error'
                    err_code = res.getErrorCode() if hasattr(res, 'getErrorCode') else 'Unknown code'
                    logger.warning(f"Failed to fetch minute chart for {symbol}: [{err_code}] {err_msg}")
                    break

                if df_page.empty:
                    break

                if 'stck_cntg_hour' in df_page.columns:
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
                
                # Pagination
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
                
                if hasattr(res, 'isOK'): # Only sleep for real API
                     time.sleep(0.1)

            if not all_dfs:
                 return pd.DataFrame()

            df = pd.concat(all_dfs).drop_duplicates(subset=['time'])
            
            cols = ["open", "high", "low", "close", "volume"]
            existing_cols = [c for c in cols if c in df.columns]
            if existing_cols:
                df[existing_cols] = df[existing_cols].apply(pd.to_numeric)
                
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

    def start(self):
        """Start the polling loop in a background thread"""
        if hasattr(self, 'poll_thread') and self.poll_thread.is_alive():
            logger.warning("MarketData polling thread is already running. Skipping start.")
            return

        self.is_polling = True
        if not hasattr(self, 'polling_symbols'):
             self.polling_symbols = []
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()
        logger.info("MarketData Polling Started")

    def stop(self):
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
            safe_interval = 0.5

            for symbol in symbols_to_poll:
                if not self.is_polling:
                    break
                try:
                    self._fetch_and_publish(symbol)
                except Exception as e:
                    logger.error(f"Polling error for {symbol}: {e}")
                
                 # Yield to other threads, but rely on RateLimiter for pacing
                time.sleep(0.01)

    def _fetch_and_publish(self, symbol: str):
        """Fetch current price via REST API and publish to subscribers"""
        data = ka.fetch_price(symbol)
        # ka.fetch_price returns dict (real or mock)
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

    def get_last_price(self, symbol: str) -> float:
        """Get the latest price for a symbol"""
        data = ka.fetch_price(symbol)
        if data:
            return float(data.get("stck_prpr", 0))
        else:
            logger.error(f"Failed to get last price for {symbol}")
            return 0.0

    def get_stock_name(self, symbol: str) -> str:
        """Get stock name from Master File Cache"""
        if symbol in self._name_cache:
            return self._name_cache[symbol]
        return symbol

    def get_master_list(self) -> List[Dict]:
        """Return full list of stocks from master files (KOSPI + KOSDAQ)"""
        return [{"code": code, "name": name} for code, name in self._name_cache.items()]
