import sys
import os
import logging

# Add project root to path
sys.path.append(os.getcwd())

from utils import kis_auth as ka
from core.scanner import Scanner

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_watchlist():
    print("--- Starting Watchlist Test ---")
    
    # Ask user which environment to test
    env = input("Check Paper(vps) or Real(prod)? [vps/prod]: ").strip() or "vps"
    
    # Auth
    print(f"Authenticating ({env})...")
    ka.auth(svr=env)
    
    scanner = Scanner()
    
    # Debug: Print User ID
    user_id = ka.getEnv().get("my_htsid", "")
    print(f"DEBUG: Using HTS ID: {user_id}")
    
    # Test: Fetch All Groups to see what's available
    print("\nFetching ALL Interest Groups (Scanning FID_ETC_CLS_CODE 00-05)...")
    
    found_any = False
    for code_idx in range(6):
        fid_code = f"{code_idx:02d}"
        # print(f"Checking FID_ETC_CLS_CODE: {fid_code}...")
        
        tr_id_group = "HHKCM113004C7"
        params_group = {
            "TYPE": "1",
            "FID_ETC_CLS_CODE": fid_code,
            "USER_ID": user_id
        }
        
        import time
        time.sleep(0.5) # Prevent rate limit
        res_group = ka._url_fetch("/uapi/domestic-stock/v1/quotations/intstock-grouplist", tr_id_group, "", params_group)
        
        if res_group.isOK():
            body = res_group.getBody()
            if not hasattr(body, 'output2'):
                # print(f"   [Info] No 'output2' in response for code {fid_code}. Skipping.")
                continue
                
            groups = body.output2
            if groups:
                found_any = True
                print(f"\n[FID_ETC_CLS_CODE {fid_code}] Found {len(groups)} groups:")
                for g in groups:
                    print(f" - Group Code: '{g['inter_grp_code']}', Name: '{g['inter_grp_name']}'")
                    
                    # If this is the group the user mentioned (Auto Trading Target), fetch it
                    if "자동" in g['inter_grp_name'] or "Auto" in g['inter_grp_name']:
                        print(f"   !!! FOUND MATCHING NAME: {g['inter_grp_name']} !!!")
                        target = g['inter_grp_code']
                        print(f"   Fetching stocks for this group...")
                        watchlist = scanner.get_watchlist(target_group_code=target)
                        print(f"   Stocks: {watchlist}")

    if not found_any:
        print("\nNo groups found in any classification code.")
        print("Possible reasons: 1. Server Sync needed (HTS -> Server Save). 2. Wrong Account (Paper vs Real).")

    print("\n--- Test Finished ---")

if __name__ == "__main__":
    test_watchlist()
