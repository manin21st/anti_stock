import sys
import os
import time
from datetime import datetime

# Add project root to path
sys.path.append(os.getcwd())

from core.dao import TradeDAO, db_manager
from core.models import Trade

def check_trade_data(symbol):
    print(f"--- Checking Trades for {symbol} ---")
    session = db_manager.get_session()
    try:
        trades = session.query(Trade).filter(Trade.symbol == symbol).all()
        print(f"Total trades found: {len(trades)}")
        for t in trades:
            print(f"  [{t.timestamp}] {t.side} {t.qty} @ {t.price}")
            
        # first_buy = TradeDAO.get_first_trade(symbol, "BUY")
        last_entry = TradeDAO.get_last_entry_date(symbol)
        
        if last_entry:
            print(f"SUCCESS: Found LAST entry: {last_entry} (ts: {last_entry.timestamp()})")
            days = int((datetime.now().timestamp() - last_entry.timestamp()) / 86400)
            print(f"Calculated Holding Days: {days}")
        else:
            print("FAILURE: No entry date found")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    # Check for Samsung Electronics as seen in screenshot
    check_trade_data("005930")
    check_trade_data("039490") # Kiwoom
    check_trade_data("066570") # LG Elec
