import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import Engine
import logging

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sync_2025():
    engine = Engine()
    # Check if loaded
    logger.info("Engine initialized. Starting Sync for 2025...")
    
    start_date = "20250101"
    end_date = "20251221"
    
    # Run Sync
    engine.sync_trade_history(start_date, end_date)
    
    # Save automatically happens in sync_trade_history
    logger.info("Sync Complete.")

if __name__ == "__main__":
    sync_2025()
