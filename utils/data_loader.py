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

    def _get_file_path(self, symbol: str) -> str:
        return os.path.join(self.data_dir, f"{symbol}_daily.csv")

    def load_data(self, symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        Load data from local CSV.
        start_date, end_date: YYYYMMDD string
        """
        file_path = self._get_file_path(symbol)
        if not os.path.exists(file_path):
            logger.warning(f"Data file for {symbol} not found.")
            return pd.DataFrame()

        try:
            df = pd.read_csv(file_path, dtype={'date': str})
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

    def download_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Download data from KIS API and save to CSV (append/update).
        Refactored chunking logic from MarketData.
        """
        logger.info(f"Downloading data for {symbol} ({start_date} ~ {end_date})")
        
        # Ensure auth
        try:
            if ka.getTREnv() is None:
                 # Default to paper for safety if not set, or try prod if configured
                 # But safer to just expect auth to be done. 
                 # Let's try to auth if not ready, defaulting to paper for safety
                 ka.auth(svr="vps") 
        except:
             pass

        # We need to fetch data in reverse chronological order usually (API provides that way?)
        # inquire-daily-itemchartprice takes start/end date and returns list.
        # Logic: 
        # 1. Fetch range.
        # 2. Merge with existing data if any.
        # 3. Save.
        
        # Existing data
        existing_df = self.load_data(symbol)
        
        # Fetch new data
        # To simplify, we might fetch the requested range and merge.
        # Or better, just fetch the missing parts? 
        # For simplicity in this version, we will fetch the requested range and upsert.

        tr_id = "FHKST03010100" # Daily chart
        
        all_df_list = []
        current_end_dt = end_date
        
        # Loop until we cover the start_date
        while True:
            params = {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_DATE_1": start_date,
                "FID_INPUT_DATE_2": current_end_dt,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "1"
            }
            
            res = ka.fetch_daily_chart(symbol, start_date, current_end_dt)
            
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
                
                # Check oldest date in this chunk
                oldest_date = chunk_df['date'].min()
                
                if oldest_date <= start_date:
                    break
                    
                # Prepare next chunk
                oldest_dt_obj = datetime.strptime(oldest_date, "%Y%m%d")
                current_end_dt = (oldest_dt_obj - timedelta(days=1)).strftime("%Y%m%d")
                
                if current_end_dt < start_date:
                    break
                    
                # time.sleep(0.3) # Rate limit handled by kis_api
            else:
                logger.error(f"API Error: {res.getErrorMessage()}")
                break
                
        if all_df_list:
            new_df = pd.concat(all_df_list)
            
            # Merge with existing
            if not existing_df.empty:
                full_df = pd.concat([existing_df, new_df])
            else:
                full_df = new_df
            
            # Deduplicate and sort
            full_df = full_df.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
            
            # Save
            file_path = self._get_file_path(symbol)
            full_df.to_csv(file_path, index=False)
            logger.info(f"Saved {len(full_df)} rows to {file_path}")
            
            # Return requested slice
            return full_df[(full_df['date'] >= start_date) & (full_df['date'] <= end_date)]
        else:
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
