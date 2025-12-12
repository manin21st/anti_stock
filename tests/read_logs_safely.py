
import os

def read_tail(filepath, n=100):
    print(f"--- Reading tail of {filepath} ---")
    if not os.path.exists(filepath):
        print("File not found.")
        return

    try:
        with open(filepath, 'rb') as f:
            # seek to end
            f.seek(0, 2)
            fsize = f.tell()
            f.seek(max(fsize - 10000, 0), 0) # Read last 10KB
            lines = f.readlines()
            # decode safely
            last_lines = lines[-n:]
            for line in last_lines:
                print(line.decode('utf-8', errors='replace').rstrip())
    except Exception as e:
        print(f"Error reading file: {e}")

read_tail("c:\\DigitalTwin\\anti_stock\\logs\\api_debug.log", n=300)
read_tail("c:\\DigitalTwin\\anti_stock\\logs\\anti_stock.log", n=300)
