import sys
import os
import time

print("Starting debug_import.py")
sys.stdout.flush()

# Add project root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
print("Added project root to path")
sys.stdout.flush()

try:
    print("Importing utils.kis_auth...")
    sys.stdout.flush()
    import utils.kis_auth
    print("Successfully imported utils.kis_auth")
    sys.stdout.flush()
except Exception as e:
    print(f"Failed to import utils.kis_auth: {e}")
    sys.stdout.flush()

try:
    print("Importing core.market_data...")
    sys.stdout.flush()
    from core.market_data import MarketData
    print("Successfully imported core.market_data")
    sys.stdout.flush()
except Exception as e:
    print(f"Failed to import core.market_data: {e}")
    sys.stdout.flush()

print("Debug import finished")
