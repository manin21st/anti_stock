import requests
import json

def test_api():
    url = "http://localhost:8000/api/chart/data?symbol=005930&timeframe=1m"
    try:
        print(f"Requesting {url}...")
        response = requests.get(url)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print("Response JSON:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            
            if 'candles' in data:
                print(f"Candle count: {len(data['candles'])}")
            else:
                print("No 'candles' key in response")
        else:
            print("Error response:", response.text)
    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    test_api()
