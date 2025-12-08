import pandas as pd
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
import sys
import os

# Add project root to path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import kis_api as ka
from utils.data_loader import DataLoader

logger = logging.getLogger(__name__)

# Debug logging to file
debug_handler = logging.FileHandler("api_debug.log")
debug_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
debug_handler.setFormatter(formatter)
logger.addHandler(debug_handler)

class MarketData:
    def __init__(self):
        self.bars: Dict[str, pd.DataFrame] = {} # symbol -> DataFrame (OHLCV)
        self.subscribers: List[Callable] = []
        self.ws = None
        self.simulation_date = None
        self.data_loader = DataLoader()
        self._initialize_api()

    def _initialize_api(self):
        """Initialize KIS API authentication"""
        ka.auth() # REST API auth
        ka.auth_ws() # WebSocket auth
        self.ws = ka.KISWebSocket(api_url="/tryitout")

    def get_bars(self, symbol: str, timeframe: str = "1m", lookback: int = 100) -> pd.DataFrame:
        """
        Get historical bars.
        timeframe: "1m", "3m", "5m", "1d"
        """
        logger.info(f"DEBUG: get_bars called for {symbol}, timeframe={timeframe}, lookback={lookback}")
        
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
            
            logger.info(f"Fetching daily bars for {symbol}: {start_dt} ~ {end_dt} (lookback={lookback})")
            
            tr_id = "FHKST03010100" # Daily chart
            
            # KIS API has a limit of 100 records per request.
            # We need to fetch in chunks if lookback > 100.
            
            all_df_list = []
            fetched_count = 0
            current_end_dt = end_dt
            
            while fetched_count < lookback:
                # Calculate start_dt for this chunk (not strictly needed as API limits by count/date, but good for context)
                # We just ask for a wide range ending at current_end_dt
                # But to be safe, we keep the original start_dt as the floor
                
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
                    logger.info(f"DEBUG: Fetched chunk {len(chunk_df)} rows. Range: {start_dt} ~ {current_end_dt}")

                    if chunk_df.empty:
                        logger.info("DEBUG: Chunk empty, breaking.")
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
                        # Less than limit returned, means no more data
                        logger.info(f"DEBUG: Chunk size {len(chunk_df)} < 100. Continuing to fetch until empty or date limit.")
                        # break # REMOVED: Premature break causing issues?
                        
                    # Prepare for next chunk
                    # Oldest date in this chunk
                    oldest_date = chunk_df['date'].min() # String YYYYMMDD
                    
                    # Next end_dt should be oldest_date - 1 day
                    oldest_dt_obj = datetime.strptime(oldest_date, "%Y%m%d")
                    current_end_dt = (oldest_dt_obj - timedelta(days=1)).strftime("%Y%m%d")
                    
                    if current_end_dt < start_dt:
                        logger.info(f"DEBUG: Next end_dt {current_end_dt} < start_dt {start_dt}, breaking.")
                        break
                        
                    # time.sleep(0.25) # Rate limit handled by kis_api
                else:
                    logger.error(f"Failed to fetch chunk: {res.getErrorMessage()}")
                    break
            
            if all_df_list:
                df = pd.concat(all_df_list).drop_duplicates(subset=['date'])
                df = df.sort_values("date").reset_index(drop=True)
                logger.info(f"Successfully fetched {len(df)} daily bars for {symbol} (requested {lookback})")
                return df.tail(lookback)
            else:
                logger.warning(f"API returned no data for {symbol}. Attempting to load from local storage.")
                df = self.data_loader.load_data(symbol)
                if not df.empty:
                    logger.info(f"Loaded {len(df)} bars from local storage.")
                    return df.tail(lookback)
                return pd.DataFrame()

        elif timeframe in ["1m", "3m", "5m"]:
            # Minute bars (Intraday)
            # Note: KIS API 'inquire-time-itemchartprice' only provides TODAY's data.
            # For 5m, we might need to resample 1m data or use specific 30-min API if available, but usually it's 1m.
            # KIS API for minute chart usually returns 1-minute data which we can resample.
            
            tr_id = "FHKST03010200" # Time chart
            current_time = datetime.now().strftime("%H%M%S")
            
            params = {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_HOUR_1": current_time,
                "FID_PW_DATA_INCU_YN": "Y", # Include past data (today)
                "FID_ETC_CLS_CODE": ""
            }
            
            res = ka.fetch_minute_chart(symbol, current_time)
            
            if res.isOK():
                df = pd.DataFrame(res.getBody().output2)
                # Columns: stck_cntg_hour, stck_prpr, stck_oprc, stck_hgpr, stck_lwpr, cntg_vol, ...
                df = df.rename(columns={
                    "stck_cntg_hour": "time",
                    "stck_oprc": "open",
                    "stck_hgpr": "high",
                    "stck_lwpr": "low",
                    "stck_prpr": "close",
                    "cntg_vol": "volume"
                })
                cols = ["open", "high", "low", "close", "volume"]
                df[cols] = df[cols].apply(pd.to_numeric)
                df = df.sort_values("time").reset_index(drop=True)
                
                # Resample if needed
                if timeframe != "1m":
                    # Need datetime index for resampling
                    # Construct dummy date (today)
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
            else:
                logger.error(f"Failed to get minute bars for {symbol}: {res.getErrorMessage()}")
                return pd.DataFrame()
        
        return pd.DataFrame()

    def _initialize_api(self):
        """Initialize API components"""
        # No WebSocket initialization needed for polling
        pass



    def subscribe_market_data(self, symbols: List[str]):
        """Register symbols for polling"""
        # Just update the list of subscribers (symbols to poll)
        # We can use a set to avoid duplicates
        current_symbols = set(self.polling_symbols if hasattr(self, 'polling_symbols') else [])
        current_symbols.update(symbols)
        self.polling_symbols = list(current_symbols)
        logger.info(f"Updated polling list: {len(self.polling_symbols)} symbols")

    def start_polling(self):
        """Start the polling loop in a background thread"""
        self.is_polling = True
        self.polling_symbols = [] # Initialize list
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

            # Snapshot of symbols to iterate safely
            symbols_to_poll = list(self.polling_symbols)
            
            for symbol in symbols_to_poll:
                if not self.is_polling:
                    break
                
                try:
                    self._fetch_and_publish(symbol)
                except Exception as e:
                    logger.error(f"Polling error for {symbol}: {e}")
                
                # Rate limiting: 20 req/s max.
                # With multiple symbols, 0.2s is too fast (5 calls/sec * N symbols).
                # Increased to 1.0s to be safe.
                # Rate limiting is handled by core.kis_api
                # time.sleep(1.0) 

    def _fetch_and_publish(self, symbol: str):
        """Fetch current price via REST API and publish to subscribers"""
        # Use FHKST01010100 (Current Price)
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol
        }
        # Use wrapper for REST API call
        data = ka.fetch_price(symbol)
        
        if data:
            # API returns strings, need to convert
            current_price = float(data.get('stck_prpr', 0))
            
            bar_data = {
                "symbol": symbol,
                "price": current_price,
                "volume": int(data.get('acml_vol', 0)),
                "time": datetime.now().strftime("%H%M%S"), # API doesn't give time in this TR, use local time
                "open": float(data.get('stck_oprc', current_price)),
                "high": float(data.get('stck_hgpr', current_price)),
                "low": float(data.get('stck_lwpr', current_price)),
                "close": current_price
            }
            
            self.on_realtime_data(bar_data)

    def on_realtime_data(self, data):
        """Callback for real-time data"""
        # Notify subscribers
        for callback in self.subscribers:
            callback(data)

    
    def set_simulation_date(self, date_str: Optional[str]):
        """Set current simulation date (YYYYMMDD) or None to disable"""
        self.simulation_date = date_str
        logger.debug(f"MarketData simulation date set to: {date_str}")

    def get_last_price(self, symbol: str) -> float:
        """Get the latest price for a symbol"""
        if self.simulation_date:
            # In simulation, use the Close price of the current simulation date
            df = self.get_bars(symbol, timeframe="1d", lookback=1)
            if not df.empty:
                return float(df.iloc[-1]['close'])
            return 0.0

        # Use inquire-price API
        env_dv = "demo" if ka.isPaperTrading() else "real"
        tr_id = "FHKST01010100"
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol
        }
        
        # Use wrapper
        data = ka.fetch_price(symbol)
        if data:
            # output: stck_prpr (Current Price)
            return float(data.get("stck_prpr", 0))
        else:
            logger.error(f"Failed to get last price for {symbol}")
            return 0.0

