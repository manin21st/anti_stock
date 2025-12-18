import sys
import os
import logging

# Add project root
sys.path.append(os.getcwd())

from core.market_data import MarketData

# Setup logging to console
logging.basicConfig(level=logging.INFO)

print("Initializing MarketData (Simulation Mode to skip API auth)...")
md = MarketData(is_simulation=True)

print("Forcing master file load...")
try:
    md._load_master_files()
    print(f"Name Cache Size: {len(md._name_cache)}")
    
    # Test specific symbols
    
    # Debug specific symbol in KOSPI file
    print("Searching for 005930 raw bytes...")
    k_path = os.path.join(os.getcwd(), "core", "..", "data", "master", "kospi_code.mst")
    with open(k_path, "rb") as f:
        for row in f:
             if row.startswith(b"005930"):
                 print(f"FOUND 005930: {row}")
                 try:
                     print(f"Decoded: {row.decode('cp949', errors='replace')}")
                     # Debug specific slice
                     name_part = row[21:-228]
                     print(f"Name Slice: {name_part}")
                     print(f"Name Decoded: {name_part.decode('cp949', errors='replace')}")
                 except: pass
                 break
        
    if len(md._name_cache) < 100:
        print("WARNING: Cache size is suspiciously small.")
except Exception as e:
    print(f"Error loading master files: {e}")
