import logging
import sys
import os
from typing import List, Dict

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import kis_api as ka

logger = logging.getLogger(__name__)

class Scanner:
    def __init__(self):
        pass

    def get_volume_leaders(self, limit: int = 10) -> List[Dict]:
        """
        Get top volume leaders.
        TR_ID: FHPST01710000 (Domestic Stock Volume Rank)
        """
        tr_id = "FHPST01710000"
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "0",
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "000000",
            "FID_INPUT_PRICE_1": "",
            "FID_INPUT_PRICE_2": "",
            "FID_VOL_CNT": "",
            "FID_INPUT_DATE_1": ""
        }
        
        res = ka.issue_request("/uapi/domestic-stock/v1/quotations/volume-rank", tr_id, "", params)
        
        results = []
        if res.isOK():
            body = res.getBody()
            items = getattr(body, 'output', [])
            if not items:
                items = []
                
            for item in items[:limit]:
                try:
                    results.append({
                        "symbol": item.get("mksc_shrn_iscd", ""),
                        "name": item.get("hts_kor_isnm", ""),
                        "price": float(item.get("stck_prpr") or 0),
                        "volume": int(item.get("acml_vol") or 0),
                        "rank": int(item.get("data_rank") or 0)
                    })
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error parsing volume leader item: {e}")
                    continue
        else:
            logger.error(f"Failed to get volume leaders: {res.getErrorMessage()}")
            
        return results

    def get_trading_value_leaders(self, limit: int = 50) -> List[Dict]:
        """
        Get top trading value leaders (Transaction Amount).
        TR_ID: FHPST01710000 (Volume Rank)
        FID_BLNG_CLS_CODE: 3 (Trading Value)
        """
        tr_id = "FHPST01710000"
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "0",
            "FID_BLNG_CLS_CODE": "3", # 3: Trading Value
            "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "000000",
            "FID_INPUT_PRICE_1": "",
            "FID_INPUT_PRICE_2": "",
            "FID_VOL_CNT": "",
            "FID_INPUT_DATE_1": ""
        }
        
        res = ka.issue_request("/uapi/domestic-stock/v1/quotations/volume-rank", tr_id, "", params)
        
        results = []
        if res.isOK():
            body = res.getBody()
            items = getattr(body, 'output', [])
            if not items:
                items = []
            
            # Filter keywords for ETF/SPAC/ETN
            exclusion_keywords = ["스팩", "ETN", "KODEX", "TIGER", "KBSTAR", "ACE", "SOL", "HANARO", "KOSEF", "ARIRANG", "TIMEFOLIO", "WOORI", "HK", "FOCUS", "KTOP", "TREX", "SMART"]
            
            count = 0
            for item in items:
                if count >= limit:
                    break
                    
                name = item.get("hts_kor_isnm", "")
                
                # Check exclusion
                if any(k in name for k in exclusion_keywords):
                    continue
                
                # Additional check: if name ends with '우' (Preferred stock)
                if name.endswith("우") or name.endswith("우B") or name.endswith("우(전환)"):
                    continue

                try:
                    results.append({
                        "symbol": item.get("mksc_shrn_iscd", ""),
                        "name": name,
                        "price": float(item.get("stck_prpr") or 0),
                        "volume": int(item.get("acml_vol") or 0),
                        "rank": int(item.get("data_rank") or 0)
                    })
                    count += 1
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error parsing trading value item: {e}")
                    continue
        else:
            logger.error(f"Failed to get trading value leaders: {res.getErrorMessage()}")
            
        return results

    def get_top_gainers(self, limit: int = 10) -> List[Dict]:
        """
        Get top gainers (Fluctuation Rank).
        TR_ID: FHPST01700000
        """
        tr_id = "FHPST01700000"
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20170",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "0", # 0: Up, 1: Down
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "000000",
            "FID_INPUT_PRICE_1": "",
            "FID_INPUT_PRICE_2": "",
            "FID_VOL_CNT": "",
            "FID_INPUT_DATE_1": ""
        }
        
        res = ka.issue_request("/uapi/domestic-stock/v1/quotations/psearch-result", tr_id, "", params)
        
        results = []
        if res.isOK():
            body = res.getBody()
            items = getattr(body, 'output', [])
            if not items:
                items = []
                
            for item in items[:limit]:
                try:
                    results.append({
                        "symbol": item.get("mksc_shrn_iscd", ""),
                        "name": item.get("hts_kor_isnm", ""),
                        "price": float(item.get("stck_prpr") or 0),
                        "change_rate": float(item.get("prdy_ctrt") or 0),
                        "rank": int(item.get("data_rank") or 0)
                    })
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error parsing top gainer item: {e}")
                    continue
        else:
            logger.error(f"Failed to get top gainers: {res.getErrorMessage()}")
            
        return results

    def get_watchlist(self, target_group_code: str = None) -> List[str]:
        """
        Get all stocks from user's interest groups (HTS/MTS Watchlist).
        If target_group_code is provided, only fetch stocks from that group.
        """
        # 1. Get Group List
        # TR_ID: HHKCM113004C7
        # URL: /uapi/domestic-stock/v1/quotations/intstock-grouplist
        
        # Need user_id from config. ka.getTREnv() might have it or we need to look it up.
        # ka._cfg has 'my_htsid'
        user_id = ka.get_env().get("my_htsid", "")
        if not user_id:
            logger.error("HTS ID (my_htsid) not found in config. Cannot fetch watchlist.")
            return []

        tr_id_group = "HHKCM113004C7"
        params_group = {
            "TYPE": "1",
            "FID_ETC_CLS_CODE": "00",
            "USER_ID": user_id
        }
        
        res_group = ka.issue_request("/uapi/domestic-stock/v1/quotations/intstock-grouplist", tr_id_group, "", params_group)
        
        watchlist_symbols = set()
        
        if res_group.isOK():
            groups = res_group.getBody().output2
            # groups is a list of dicts: {'inter_grp_code': '001', 'inter_grp_name': 'MyGroup', ...}
            
            # 2. Get Stocks for each group
            # TR_ID: HHKCM113004C6
            # URL: /uapi/domestic-stock/v1/quotations/intstock-stocklist-by-group
            
            tr_id_stock = "HHKCM113004C6"
            
            for group in groups:
                grp_code = group["inter_grp_code"]
                grp_name = group["inter_grp_name"]
                
                # Filter by Group Code if specified
                if target_group_code and grp_code != target_group_code:
                    continue
                    
                logger.debug(f"Fetching watchlist group: {grp_name} ({grp_code})")
                
                params_stock = {
                    "TYPE": "1",
                    "USER_ID": user_id,
                    "INTER_GRP_CODE": grp_code,
                    "FID_ETC_CLS_CODE": "4",
                    "DATA_RANK": "",
                    "INTER_GRP_NAME": "",
                    "HTS_KOR_ISNM": "",
                    "CNTG_CLS_CODE": ""
                }
                
                res_stock = ka.issue_request("/uapi/domestic-stock/v1/quotations/intstock-stocklist-by-group", tr_id_stock, "", params_stock)
                
                if res_stock.isOK():
                    stocks = res_stock.getBody().output2
                    # stocks is list of dicts: {'jong_code': '005930', ...}
                    for stock in stocks:
                        # jong_code might be empty for empty slots
                        code = stock.get("jong_code")
                        if code:
                            watchlist_symbols.add(code)
                else:
                    logger.error(f"Failed to fetch stocks for group {grp_code}")
                    
        else:
            logger.error(f"Failed to fetch interest groups: {res_group.getErrorMessage()}")
            
        return list(watchlist_symbols)
