
import re

LOG_FILE = "logs/anti_stock.log"
TARGET_DATE = "2025-12-16"

def analyze_logs():
    print(f"Analyzing {LOG_FILE} for {TARGET_DATE} Afternoon (12:00+)...")
    
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    captured_lines = []
    
    # Dump to file for inspection
    with open("tests/debug_log_dump.txt", "w", encoding="utf-8") as f:
        count = 0
        for line in lines:
            if TARGET_DATE in line:
                f.write(line)
                count += 1
                
    print(f"Dumped {count} lines to tests/debug_log_dump.txt")

if __name__ == "__main__":
    analyze_logs()
