import json
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def backfill_pnl():
    path = "data/trade_history.json"
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return

    print(f"Loading {path}...")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Convert timestamps and sort
    # Assuming string or loaded as dicts
    events = []
    for item in data:
        # Normalize timestamp for sorting
        ts = item.get("timestamp")
        dt = None
        if ts:
            try:
                dt = datetime.fromisoformat(ts)
            except:
                pass
        item["_dt"] = dt if dt else datetime.min
        events.append(item)
    
    # Sort chronologically
    events.sort(key=lambda x: x["_dt"])
    
    # Virtual Portfolio State: { symbol: { qty, avg_price } }
    portfolio = {}
    
    updated_count = 0
    
    for event in events:
        symbol = event.get("symbol")
        side = event.get("side") # BUY / SELL
        qty = int(event.get("qty", 0))
        price = float(event.get("price", 0))
        event_type = event.get("event_type", "")
        
        if qty <= 0 or price <= 0:
            continue
            
        # Initialize position if needed
        if symbol not in portfolio:
            portfolio[symbol] = {"qty": 0, "avg_price": 0.0}
            
        pos = portfolio[symbol]
        
        if side == "BUY":
            # Update Avg Price
            # Formula: (OldQty * OldAvg + NewQty * Price) / (OldQty + NewQty)
            total_val = (pos["qty"] * pos["avg_price"]) + (qty * price)
            new_qty = pos["qty"] + qty
            pos["qty"] = new_qty
            pos["avg_price"] = total_val / new_qty if new_qty > 0 else 0
            
        elif side == "SELL":
            # Calculate PnL (Force Update to ensure meta is populated)
            # if event.get("pnl") is None: 
            if True: 
                current_avg = pos["avg_price"]
                
                # If we have a valid avg price from history
                if current_avg > 0:
                    exec_qty = qty
                    exec_price = price
                    
                    # Fee Calculation (Conservative 0.25%)
                    total_sell_amt = exec_price * exec_qty
                    fees = total_sell_amt * 0.0025
                    
                    pnl = (exec_price - current_avg) * exec_qty - fees
                    pnl_pct = ((exec_price - current_avg) / current_avg) * 100
                    
                    event["pnl"] = round(pnl, 0)
                    event["pnl_pct"] = round(pnl_pct, 2)
                    
                    # [NEW] Store Fee and Cost Basis in meta for UI
                    if "meta" not in event or event["meta"] is None:
                        event["meta"] = {}
                    
                    event["meta"]["fees"] = round(fees, 0)
                    event["meta"]["old_avg_price"] = round(current_avg, 2)
                    
                    updated_count += 1
                    # print(f"Update: {symbol} Sell {qty} @ {price} (Avg: {current_avg:.0f}) -> PnL: {event['pnl']}")
            
            # Update Qty
            pos["qty"] -= qty
            if pos["qty"] < 0: pos["qty"] = 0 # Prevent negative in replay
            
            # If closed, reset avg price? 
            # Standard accounting: Avg Price remains until position closed? 
            # Yes, standard implementation keeps avg price. 
            # If Qty=0, next buy resets it.
            if pos["qty"] == 0:
                pos["avg_price"] = 0 

    # cleanup temp key
    for event in events:
        if "_dt" in event:
            del event["_dt"]
            
    # Save back
    # But wait, 'data' list might be out of order vs 'events' list.
    # We should save the sorted 'events' list? 
    # Usually history is appended, so sorting shouldn't change much unless multiple sources.
    # Let's save the 'events' list to enforce chronological order.
    
    print(f"Backfill Complete. Updated {updated_count} trades.")
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)
        
if __name__ == "__main__":
    backfill_pnl()
