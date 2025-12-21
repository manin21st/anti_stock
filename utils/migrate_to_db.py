import sys
import os
import json
import logging
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db_manager
from core.models import Trade, Watchlist

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger()

def migrate_trades():
    json_path = os.path.join("data", "trade_history.json")
    if not os.path.exists(json_path):
        logger.warning("No trade_history.json found. Skipping.")
        return

    session = db_manager.get_session()
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            trades_data = json.load(f)
            
        logger.info(f"Found {len(trades_data)} trades in JSON.")
        
        count = 0
        for item in trades_data:
            # Parse Timestamp
            try:
                ts = datetime.fromisoformat(item['timestamp'])
            except ValueError:
                ts = datetime.now() # Fallback
                
            # Check if exists (by event_id)
            exists = session.query(Trade).filter_by(event_id=item['event_id']).first()
            if exists:
                continue
                
            trade = Trade(
                event_id=item['event_id'],
                timestamp=ts,
                symbol=item['symbol'],
                strategy_id=item.get('strategy_id', 'manual'),
                side=item['side'],
                price=float(item['price']),
                qty=int(item['qty']),
                exec_amt=float(item['price']) * int(item['qty']),
                pnl=item.get('pnl'),
                pnl_pct=item.get('pnl_pct'),
                order_id=item.get('order_id'),
                meta=item.get('meta', {})
            )
            session.add(trade)
            count += 1
            
        session.commit()
        logger.info(f"Successfully migrated {count} new trades to Database.")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Trade Migration Failed: {e}")
    finally:
        session.close()

def migrate_watchlist():
    json_path = os.path.join("data", "watchlist.json")
    if not os.path.exists(json_path):
        logger.warning("No watchlist.json found. Skipping.")
        return

    session = db_manager.get_session()
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            watchlist_data = json.load(f)
            
        logger.info(f"Found {len(watchlist_data)} items in Watchlist JSON.")
        
        count = 0
        for item in watchlist_data:
            symbol = item if isinstance(item, str) else item.get('symbol')
            if not symbol: continue
            
            exists = session.query(Watchlist).filter_by(symbol=symbol).first()
            if exists:
                continue
                
            wl = Watchlist(symbol=symbol)
            session.add(wl)
            count += 1
            
        session.commit()
        logger.info(f"Successfully migrated {count} watchlist items to Database.")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Watchlist Migration Failed: {e}")
    finally:
        session.close()

def main():
    logger.info("Starting Migration to Server DB...")
    
    # 1. Create Tables
    db_manager.create_tables()
    
    # 2. Migrate Data
    migrate_trades()
    migrate_watchlist()
    
    logger.info("Migration Completed.")

if __name__ == "__main__":
    main()
