import requests
import os

def download_lib():
    url = 'https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js'
    output_path = 'web/static/lightweight-charts.js'
    
    print(f"Downloading {url} to {output_path}...")
    try:
        r = requests.get(url)
        r.raise_for_status()
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'wb') as f:
            f.write(r.content)
        print("Download successful.")
        print(f"File size: {len(r.content)} bytes")
    except Exception as e:
        print(f"Download failed: {e}")

if __name__ == "__main__":
    download_lib()
