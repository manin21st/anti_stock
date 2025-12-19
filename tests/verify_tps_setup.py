
import sys
import os
import time

# Add project root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core import kis_api as ka

def dummy_func():
    return "success"

def test_tps_integration():
    print("Testing TPS Integration...")
    rl = ka.rate_limiter
    
    # 1. Test Server Connection
    print(f"Server URL: {rl.server_url}")
    token_status = rl._request_token_from_server()
    print(f"Token Status (Should be True if server up): {token_status}")
    
    # 2. Test Execute
    start = time.time()
    res = rl.execute(dummy_func)
    end = time.time()
    print(f"Execute Result: {res} (Time: {end-start:.4f}s)")
    
    if token_status is True:
        print("PASS: Server Mode works.")
    elif token_status is None:
        print("PASS: Local Mode works (Failover active).")
    else:
        print("FAIL: Limit exceeded or unknown state.")

if __name__ == "__main__":
    test_tps_integration()
