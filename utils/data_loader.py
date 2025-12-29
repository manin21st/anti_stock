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
            
            # Sort by date and time (if available) to ensure chronological order
            sort_cols = ['date', 'time'] if 'time' in df.columns else ['date']
            df = df.sort_values(sort_cols).reset_index(drop=True)
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
        
        try:
            s_dt = datetime.strptime(start_date, "%Y%m%d")
            e_dt = datetime.strptime(end_date, "%Y%m%d")
        except:
            return pd.DataFrame()
             
        current_date_obj = e_dt
        
        # Retry Configuration
        max_retries = 3
        
        while current_date_obj >= s_dt:
            target_date = current_date_obj.strftime("%Y%m%d")
            
            if current_date_obj.weekday() >= 5:
                current_date_obj -= timedelta(days=1)
                continue

            logger.info(f"Fetching minute data for {target_date}...")
            
            target_time = "153000" 
            day_df_list = []
            
            while True:
                # Retry Loop
                retry_count = 0
                res = None
                
                while retry_count < max_retries:
                    res = ka.fetch_past_minute_chart(symbol, target_date, target_time)
                    if res.isOK():
                        break
                    else:
                        msg = res.getErrorMessage()
                        if "EGW00201" in msg or "초과" in msg:
                            logger.warning(f"TPS Limit Exceeded. Retrying ({retry_count+1}/{max_retries})...")
                            time.sleep(1.0 * (retry_count + 1)) # Backoff
                            retry_count += 1
                        else:
                            # Other error
                            break
                            
                if not res or not res.isOK():
                     logger.error(f"Minute API Error after retries: {res.getErrorMessage() if res else 'No Response'}")
                     break

                o2 = res.getBody().output2
                if not o2: break # No more data
                
                chunk = pd.DataFrame(o2)
                chunk = chunk.rename(columns={
                    "stck_bsop_date": "date",
                    "stck_cntg_hour": "time",
                    "stck_prpr": "close", "stck_oprc": "open", "stck_hgpr": "high", "stck_lwpr": "low", "cntg_vol": "volume"
                })
                
                chunk = chunk[["date", "time", "open", "high", "low", "close", "volume"]]
                cols = ["open", "high", "low", "close", "volume"]
                chunk[cols] = chunk[cols].apply(pd.to_numeric)
                
                day_df_list.append(chunk)
                
                oldest_time = chunk['time'].min() # e.g. "150000"
                
                if oldest_time <= "090000":
                    break
                    
                t_obj = datetime.strptime(oldest_time, "%H%M%S")
                next_t_obj = t_obj - timedelta(minutes=1)
                target_time = next_t_obj.strftime("%H%M%S")
                
                if target_time < "090000":
                    break
                    
                # Strict TPS Control: Minimum 0.2s sleep between calls
                time.sleep(0.3) 
            
            if day_df_list:
                day_all = pd.concat(day_df_list)
                all_df_list.append(day_all)
            
            current_date_obj -= timedelta(days=1)
            time.sleep(0.1) # Day boundary breathing room
            
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


    def check_availability(self, symbol: str, start_date: str, end_date: str, timeframe: str = "D") -> bool:
        """Check if local data covers the requested range"""
        df = self.load_data(symbol, start_date, end_date, timeframe=timeframe)
        if df.empty:
            return False
        
        # Check start and end coverage (approximate)
        # It's trading days, so exact match might happen, but if df min <= start and df max >= end...
        # Actually start_date provided might be a holiday.
        # We just check if we have some data in the range.
        # A stricter check would be to see if the first date in df is close to start_date.
        
        return len(df) > 0 # Simple check for now
