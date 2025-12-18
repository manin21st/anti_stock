import sys
import os
import logging
import json

# Add project root
sys.path.append(os.getcwd())

from core import kis_api as ka

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_period_pnl():
    print("Initializing KIS API...")
    
    # Init Engine to handle Config/Auth
    from core.engine import Engine
    engine = Engine()
    
    # Auth is handled in Engine init
    # if not ka.is_ok():
    #     print("Auth failed (kis_api status is bad)")
        # return

    # Define parameters for Period PnL
    # TR ID: TTTC8780R (Period Profit Analysis)
    # URL: /uapi/domestic-stock/v1/trading/inquire-period-ccld-pnl (Guessing based on pattern)
    # Or /uapi/domestic-stock/v1/trading/inquire-period-balance?
    
    # Official Docs usually say:
    # URL: /uapi/domestic-stock/v1/trading/inquire-period-ccld-pnl
    # TR_ID: TTTC8780R
    
    # Try VTTC8708R for Paper Trading (if applicable)
    import kis_auth as ka_module
    _url_fetch = ka_module._url_fetch
    
    is_paper = ka.isPaperTrading()
    tr_id = "VTTC8708R" if is_paper else "TTTC8708R"
    print(f"Using TR_ID: {tr_id} (Paper: {is_paper})")
    
    start_dt = "20241201"
    end_dt = "20241219"
    
    
    print(f"Fetching PnL from {start_dt} to {end_dt}...")
    try:
        # Use the newly added function in kis_api
        res = ka.fetch_period_profit(start_dt, end_dt)
        
        if res and res.isOK():
            print("Response OK!")
            body = res.getBody()
            
            # Print output1 (List) and output2 (Summary)
            # Inspect structure
            print(f"Output1 Type: {type(getattr(body, 'output1', None))}")
            print(f"Output2 Type: {type(getattr(body, 'output2', None))}")
            
            if hasattr(body, "output1"):
                 print("Output1 (First 3 items):", getattr(body, "output1", [])[:3])
            
            if hasattr(body, "output2"):
                 print("Output2 (Summary):", getattr(body, "output2", {}))
                 
        else:
            print(f"Error: {res.getErrorMessage() if res else 'None'}")
            print(f"Code: {res.getErrorCode() if res else 'None'}")
            
    except Exception as e:
        print(f"Exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_period_pnl()
