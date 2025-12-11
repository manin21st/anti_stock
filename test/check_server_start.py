import sys
import os
sys.path.append(os.getcwd())
try:
    from web.server import app
    print("Server import successful")
except Exception as e:
    print(f"Server import failed: {e}")
    import traceback
    traceback.print_exc()
