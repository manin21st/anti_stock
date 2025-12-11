import requests
import json

try:
    # First inject trades to ensure data exists
    requests.post('http://localhost:8000/api/debug/inject_trades')
    
    # Then fetch chart data
    response = requests.get('http://localhost:8000/api/chart/data?symbol=005930&timeframe=D&lookback=100')
    data = response.json()
    
    # Print markers
    print("MARKERS DATA:")
    if 'markers' in data:
        for m in data['markers']:
            print(f"Timestamp: {m['timestamp']} (Type: {type(m['timestamp'])})")
    else:
        print("No markers found")
        
except Exception as e:
    print(f"Error: {e}")
