import shutil
import os

src = r"C:\Users\manin\.gemini\antigravity\brain\4840e784-38ef-49b4-a84f-7509ced2765f\stock_bot_logo_v15_cute_bot_arrow_1767345281314.png"
dst = r"c:\DigitalTwin\anti_stock\web\static\logo.png"

try:
    if os.path.exists(src):
        # Ensure directory exists
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        print(f"Success: Copied to {dst}")
        print(f"File size: {os.path.getsize(dst)} bytes")
    else:
        print(f"Error: Source {src} not found")
except Exception as e:
    print(f"Error: {str(e)}")
