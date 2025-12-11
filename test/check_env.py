import os
import sys

log_file = "c:\\DigitalTwin\\anti_stock\\env_check.log"

def log(msg):
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg)

if os.path.exists(log_file):
    os.remove(log_file)

log("Checking environment...")

# Check imports
try:
    import pandas
    log("pandas: OK")
except ImportError as e:
    log(f"pandas: MISSING ({e})")

try:
    import requests
    log("requests: OK")
except ImportError as e:
    log(f"requests: MISSING ({e})")

try:
    import yaml
    log("yaml: OK")
except ImportError as e:
    log(f"yaml: MISSING ({e})")

try:
    import websockets
    log("websockets: OK")
except ImportError as e:
    log(f"websockets: MISSING ({e})")

try:
    from Crypto.Cipher import AES
    log("pycryptodome: OK")
except ImportError as e:
    log(f"pycryptodome: MISSING ({e})")

# Check config file
config_path = os.path.join(os.path.expanduser("~"), "KIS", "config", "kis_devlp.yaml")
if os.path.exists(config_path):
    log(f"Config file found at: {config_path}")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)
            if "my_app" in content:
                log("Config content looks valid (has my_app)")
            else:
                log("Config content might be invalid (missing my_app)")
    except Exception as e:
        log(f"Error reading config: {e}")
else:
    log(f"Config file NOT found at: {config_path}")

log("Environment check complete.")
