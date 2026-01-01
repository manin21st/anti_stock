import requests
try:
    print(requests.get('http://tps.bhsong.org', timeout=5).text)
except Exception as e:
    print(f"Error: {e}")
