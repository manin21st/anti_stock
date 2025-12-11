import pandas as pd
import os
import sys
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import kis_api as ka

logger = logging.getLogger(__name__)

class DataLoader:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), data_dir)
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        
        # Ensure auth is done if not already
        # We assume ka.auth() is called by the main application or we call it here lazily if needed
        # But usually better to rely on global auth state or check it.
        # For standalone script usage, we might need to init auth.
        pass



    def load_data(self, symbol: str, start_date: str = None, end_date: str = None, timeframe: str = "D") -> pd.DataFrame:
        """
        Load data from local CSV.
        start_date, end_date: YYYYMMDD string
        """
        file_path = self._get_file_path(symbol, timeframe)
        if not os.path.exists(file_path):
            logger.warning(f"Data file for {symbol} (TF: {timeframe}) not found.")
            return pd.DataFrame()

        try:
            df = pd.read_csv(file_path, dtype={'date': str, 'time': str})
            # Filter by date
            if start_date:
                df = df[df['date'] >= start_date]
            if end_date:
                df = df[df['date'] <= end_date]
            
            # Sort just in case
            df = df.sort_values('date').reset_index(drop=True)
            return df
        except Exception as e:
            logger.error(f"Failed to load data for {symbol}: {e}")
            return pd.DataFrame()

    def download_data(self, symbol: str, start_date: str, end_date: str, timeframe: str = "D") -> pd.DataFrame:
        """
        Download data from KIS API and save to CSV (append/update).
        timeframe: "D", "1m", "3m", etc.
        """
        logger.info(f"Downloading data for {symbol} ({start_date} ~ {end_date}, TF: {timeframe})")
        
        # Ensure auth
        try:
            env = ka.getTREnv()
            if env is None or isinstance(env, tuple):
                 # Default to paper for safety if not set, or try prod if configured
                 # But safer to just expect auth to be done. 
                 # Let's try to auth if not ready, defaulting to paper for safety
                 ka.auth(svr="vps") 
        except:
             pass

        if timeframe == "D":
            return self._download_daily_data(symbol, start_date, end_date)
        else:
            # Minute data (fetch 1m base)
            return self._download_minute_data(symbol, start_date, end_date)

    def _get_file_path(self, symbol: str, timeframe: str = "D") -> str:
        suffix = "daily" if timeframe == "D" else "1min" # Base is 1min for all intraday
        return os.path.join(self.data_dir, f"{symbol}_{suffix}.csv")

    def _download_daily_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        existing_df = self.load_data(symbol, timeframe="D")
        
        all_df_list = []
        current_end_dt = end_date
        
        while True:
            # Existing Daily Logic ...
            res = ka.fetch_daily_chart(symbol, start_date, current_end_dt)
            if res.isOK():
                chunk_df = pd.DataFrame(res.getBody().output2)
                if chunk_df.empty: break
                    
                chunk_df = chunk_df.rename(columns={
                    "stck_bsop_date": "date",
                    "stck_oprc": "open", "stck_hgpr": "high", "stck_lwpr": "low", "stck_clpr": "close", "acml_vol": "volume"
                })
                cols = ["open", "high", "low", "close", "volume"]
                chunk_df[cols] = chunk_df[cols].apply(pd.to_numeric)
                all_df_list.append(chunk_df)
                
                oldest_date = chunk_df['date'].min()
                if oldest_date <= start_date: break
                    
                oldest_dt_obj = datetime.strptime(oldest_date, "%Y%m%d")
                current_end_dt = (oldest_dt_obj - timedelta(days=1)).strftime("%Y%m%d")
                if current_end_dt < start_date: break
            else:
                logger.error(f"API Error: {res.getErrorMessage()}")
                break
        
        return self._save_and_merge(symbol, existing_df, all_df_list, "D", start_date, end_date)

    def _download_minute_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        existing_df = self.load_data(symbol, timeframe="1m")
        all_df_list = []
        
        # We need to iterate day by day or optimize range
        # inquire-time-dailychartprice takes Date + Hour
        # It returns 30 (or 120) bars backwards from the specified time.
        # Efficient strategy: Iterate DAYS from end_date down to start_date.
        # For each day, request from 153000 backwards until 090000.
        
        try:
            s_dt = datetime.strptime(start_date, "%Y%m%d")
            e_dt = datetime.strptime(end_date, "%Y%m%d")
        except:
             return pd.DataFrame()
             
        current_date_obj = e_dt
        
        while current_date_obj >= s_dt:
            target_date = current_date_obj.strftime("%Y%m%d")
            
            # Skip weekends (Simple check, API handles it but saves calls)
            if current_date_obj.weekday() >= 5:
                current_date_obj -= timedelta(days=1)
                continue

            logger.info(f"Fetching minute data for {target_date}...")
            
            # Fetch full day (Start from Market Close 15:30:00)
            target_time = "153000" 
            
            # We might need multiple calls per day if response limit is small
            # Docs say max 120 count for Real env. 
            # Trading day 9:00~15:30 is 6.5 hours = 390 minutes.
            # So we need ~4 calls per day.
            
            day_df_list = []
            
            while True:
                res = ka.fetch_past_minute_chart(symbol, target_date, target_time)
                
                if res.isOK():
                    o2 = res.getBody().output2
                    if not o2: break # No more data
                    
                    chunk = pd.DataFrame(o2)
                    chunk = chunk.rename(columns={
                        "stck_bsop_date": "date",
                        "stck_cntg_hour": "time",
                        "stck_prpr": "close", "stck_oprc": "open", "stck_hgpr": "high", "stck_lwpr": "low", "cntg_vol": "volume"
                    })
                    
                    # Filter invalid time/dates just in case
                    # Fix time format HHMMSS
                    
                    chunk = chunk[["date", "time", "open", "high", "low", "close", "volume"]]
                    cols = ["open", "high", "low", "close", "volume"]
                    chunk[cols] = chunk[cols].apply(pd.to_numeric)
                    
                    day_df_list.append(chunk)
                    
                    # Next request time = oldest time in this chunk - 1 minute?
                    # API logic: Returns N records BEFORE input time.
                    oldest_time = chunk['time'].min() # e.g. "150000"
                    
                    # Setup next target time
                    if oldest_time <= "090000":
                        break
                        
                    # Decrement 1 minute from oldest_time to avoid duplicate? 
                    # Or does API exclude the input time? 
                    # Usually "Included" or "Excluded". Let's try passing oldest_time.
                    # If we get duplicate, we drop it.
                    # Safest is to subtract 1 minute.
                    # But string math is hard. 
                    # Actually, if we pass 150000, and it returns 150000~..., 
                    # we should pass 145959? 
                    # Let's assume input is inclusive limit. 
                    
                    # Simple time decrement logic
                    t_obj = datetime.strptime(oldest_time, "%H%M%S")
                    next_t_obj = t_obj - timedelta(minutes=1)
                    target_time = next_t_obj.strftime("%H%M%S")
                    
                    if target_time < "090000":
                        break
                        
                    time.sleep(0.05) # Small buffer
                else:
                    logger.error(f"Minute API Error: {res.getErrorMessage()}")
                    break
            
            if day_df_list:
                day_all = pd.concat(day_df_list)
                all_df_list.append(day_all)
            
            current_date_obj -= timedelta(days=1)
            
        return self._save_and_merge(symbol, existing_df, all_df_list, "1m", start_date, end_date)

    def _save_and_merge(self, symbol, existing_df, new_dfs, timeframe, start, end):
        if new_dfs:
            new_df = pd.concat(new_dfs)
            if not existing_df.empty:
                full_df = pd.concat([existing_df, new_df])
            else:
                full_df = new_df
                
            # Deduplicate
            unique_cols = ['date'] if timeframe=="D" else ['date', 'time']
            full_df = full_df.drop_duplicates(subset=unique_cols).sort_values(unique_cols).reset_index(drop=True)
            
            file_path = self._get_file_path(symbol, timeframe)
            full_df.to_csv(file_path, index=False)
            logger.info(f"Saved {len(full_df)} rows to {file_path}")
            
            # Return slice
            if timeframe == "D":
                return full_df[(full_df['date'] >= start) & (full_df['date'] <= end)]
            else:
                return full_df[(full_df['date'] >= start) & (full_df['date'] <= end)]
        return pd.DataFrame()


    def check_availability(self, symbol: str, start_date: str, end_date: str) -> bool:
        """Check if local data covers the requested range"""
        df = self.load_data(symbol, start_date, end_date)
        if df.empty:
            return False
        
        # Check start and end coverage (approximate)
        # It's trading days, so exact match might happen, but if df min <= start and df max >= end...
        # Actually start_date provided might be a holiday.
        # We just check if we have some data in the range.
        # A stricter check would be to see if the first date in df is close to start_date.
        
        return len(df) > 0 # Simple check for now
