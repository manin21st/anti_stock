
import os

log_path = r"c:\DigitalTwin\anti_stock\logs\anti_stock.log"

try:
    with open(log_path, 'r', encoding='utf-8') as f:
        # seek to end and read back some bytes? or just readlines if 3MB is okay.
        # 3MB is small enough to readlines in memory.
        lines = f.readlines()
        
    # Get last 500 lines first
    recent_lines = lines[-500:]
    
    # Filter for Samsung Elec (005930) or general errors
    target_logs = [l for l in recent_lines if "005930" in l or "ERROR" in l]
    
    print(f"Total Lines found: {len(target_logs)}")
    for line in target_logs[-30:]: # Print last 30 related lines
        print(line.strip())
        
except Exception as e:
    print(f"Error reading logs: {e}")
