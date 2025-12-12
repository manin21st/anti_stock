import shutil
import os

src = "logs/anti_stock.log"
dst = "debug_log_copy.txt"

if os.path.exists(src):
    try:
        shutil.copy2(src, dst)
        print(f"Successfully copied {src} to {dst}")
    except Exception as e:
        print(f"Failed to copy: {e}")
else:
    print(f"Source file {src} not found")
