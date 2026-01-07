import os
import sys

# Ensure core is imported if required by policy (though mainly for output encoding fix which we need)
# But since this is a temp debug script, we just need to read the file safely.
# We will force stdout to utf-8 just in case.
sys.stdout.reconfigure(encoding='utf-8')

log_path = 'logs/anti_stock.log'
if os.path.exists(log_path):
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
            print("--- LOG START ---")
            print("".join(lines[-100:])) # Read last 100 lines to see if there was a crash before the stop
            print("--- LOG END ---")
    except Exception as e:
        print(f"Error reading log: {e}")
else:
    print(f"Log file not found: {log_path}")
