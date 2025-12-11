import requests
import json

url = "http://localhost:8000/api/config"
data = {
    "breakout": {
        "enabled": True,
        "gap_pct": 2.5
    }
}

try:
    res = requests.post(url, json=data)
    print(f"Status: {res.status_code}")
    print(f"Response: {res.json()}")
except Exception as e:
    print(f"Error: {e}")
