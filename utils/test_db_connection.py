import sys
import os
import yaml
from sqlalchemy import create_engine, text

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_connection():
    # Load Config
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'secrets.yaml')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            db_url = config.get('database', {}).get('url')
            
        if not db_url:
            print("❌ Error: 'database.url' not found in config/secrets.yaml")
            return

        print(f"Connecting to: {db_url.split('@')[-1]} ...") # Hide credentials
        
        # Connect
        engine = create_engine(db_url)
        with engine.connect() as connection:
            result = connection.execute(text("SELECT version();"))
            version = result.fetchone()[0]
            print(f"Connection Successful!")
            print(f"Database Version: {version}")
            
    except Exception as e:
        print(f"Connection Failed: {e}")

if __name__ == "__main__":
    test_connection()
