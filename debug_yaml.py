import os
import yaml
import sys

# Standard path from kis_auth
config_root = os.path.join(os.path.expanduser("~"), "KIS", "config")
yaml_path = os.path.join(config_root, "kis_devlp.yaml")

print(f"Reading YAML from: {yaml_path}")

try:
    with open(yaml_path, encoding="UTF-8") as f:
        _cfg = yaml.load(f, Loader=yaml.FullLoader)
        
    print(f"Keys in YAML: {list(_cfg.keys())}")
    print(f"my_prod: '{_cfg.get('my_prod')}'")
    print(f"my_acct_stock: {'YES' if 'my_acct_stock' in _cfg else 'NO'}")
    print(f"my_paper_stock: {'YES' if 'my_paper_stock' in _cfg else 'NO'}")
    
except Exception as e:
    print(f"Error: {e}")
