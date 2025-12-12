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

def test_scanner():
    print("--- Starting Scanner Test ---")
    
    # Auth
    print("Authenticating (Paper)...")
    ka.auth(svr="vps")
    
    scanner = Scanner()
    
    print("\nTesting Volume Leaders...")
    try:
        items = scanner.get_volume_leaders(limit=5)
        print(f"Volume Leaders Found: {len(items)}")
        for item in items:
            print(item)
    except Exception as e:
        print(f"Volume Leaders Failed: {e}")
        
    print("\nTesting Top Gainers...")
    try:
        items = scanner.get_top_gainers(limit=5)
        print(f"Top Gainers Found: {len(items)}")
        for item in items:
            print(item)
    except Exception as e:
        print(f"Top Gainers Failed: {e}")
        
    print("\n--- Test Finished ---")

if __name__ == "__main__":
    test_scanner()
