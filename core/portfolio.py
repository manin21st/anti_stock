from dataclasses import dataclass
from typing import Dict, Optional
import json
import os
import time

@dataclass
class Position:
    symbol: str
    name: str # Stock Name
    qty: int
    avg_price: float
    current_price: float = 0.0
    tag: str = "" # Strategy ID
    partial_taken: bool = False # For partial profit taking
    max_price: float = 0.0 # For trailing stop
    last_update: float = 0.0 # Timestamp of last price update

class Portfolio:
    def __init__(self):
        self.positions: Dict[str, Position] = {}
        self.cash: float = 0.0
        self.deposit_d1: float = 0.0 # Next Day Deposit
        self.deposit_d2: float = 0.0 # D+2 Deposit
        self.total_asset: float = 0.0
        self.on_position_change = [] # List of callbacks (change_info: dict)

    def update_position(self, symbol: str, qty: int, price: float, tag: str = ""):
        """Update position from order execution"""
        if symbol not in self.positions:
            if qty > 0:
                # Name will be updated on next sync or we can fetch it if needed.
                # For now, use symbol as placeholder if name is unknown.
                self.positions[symbol] = Position(symbol, symbol, qty, price, price, tag, max_price=price)
        else:
            pos = self.positions[symbol]
            if qty > 0: # Buy more
                total_cost = (pos.qty * pos.avg_price) + (qty * price)
                pos.qty += qty
                pos.avg_price = total_cost / pos.qty
                pos.max_price = max(pos.max_price, price) # Reset max price on add? Or keep?
            else: # Sell
                # qty is negative
                pos.qty += qty # Decrease qty
                if pos.qty <= 0:
                    del self.positions[symbol]

    def update_market_price(self, symbol: str, price: float):
        """Update current price for a position"""
        if symbol in self.positions:
            pos = self.positions[symbol]
            pos.current_price = price
            pos.max_price = max(pos.max_price, price)
            pos.last_update = time.time()

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def get_account_value(self) -> float:
        # This should be synced with Broker's balance
        return self.total_asset
    
    def sync_with_broker(self, broker_balance: Dict, notify: bool = True):
        """Sync internal state with actual broker balance"""
        if not broker_balance:
            return
            
        # Update Cash & Asset
        summary = broker_balance.get("summary", [])
        if summary:
            # dnca_tot_amt: Deposit
            # nxdy_excc_amt: Next Day Deposit
            # prvs_rcdl_excc_amt: D+2 Deposit
            # tot_evlu_amt: Total Eval Amount
            self.cash = float(summary[0].get("dnca_tot_amt", 0))
            self.deposit_d1 = float(summary[0].get("nxdy_excc_amt", 0))
            self.deposit_d2 = float(summary[0].get("prvs_rcdl_excc_amt", 0))
            self.total_asset = float(summary[0].get("tot_evlu_amt", 0))

        # Load saved state to preserve metadata (partial_taken, max_price)
        saved_state = {}
        if os.path.exists("portfolio_state.json"):
            try:
                with open("portfolio_state.json", "r", encoding="utf-8") as f:
                    saved_state = json.load(f)
                # print(f"DEBUG: Loaded saved state for sync: {saved_state.keys()}")
            except Exception as e:
                print(f"Failed to load portfolio state during sync: {e}")

        # Update Positions
        holdings = broker_balance.get("holdings", [])
        
        current_symbols = set()
        for h in holdings:
            symbol = h["pdno"]
            name = h.get("prdt_name", symbol)
            qty = int(h["hldg_qty"])
            avg_price = float(h["pchs_avg_pric"])
            current_price = float(h["prpr"])
            
            current_symbols.add(symbol)
            
            # Restore metadata from saved state if available
            saved_data = saved_state.get(symbol, {})
            saved_partial = saved_data.get("partial_taken", False)
            saved_max = saved_data.get("max_price", current_price)
            saved_tag = saved_data.get("tag", "unknown")

            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # Capture pre-update state for PnL calculation
                old_avg_price = pos.avg_price

                # Detect Change
                if qty != pos.qty:
                    diff = qty - pos.qty
                    change_type = "BUY_FILLED" if diff > 0 else "SELL_FILLED"
                    
                    if qty == 0 and diff < 0:
                        change_type = "POSITION_CLOSED"

                    if notify:
                        self._notify_change({
                            "type": change_type,
                            "symbol": symbol,
                            "qty": abs(diff),
                            "price": avg_price if diff > 0 else current_price, # Approx price
                            "tag": saved_tag,
                            # [NEW] Enhanced Data
                            "exec_qty": abs(diff),
                            "exec_price": avg_price if diff > 0 else current_price,
                            "new_qty": qty,
                            "new_avg_price": avg_price,
                            "old_avg_price": old_avg_price,
                            "total_asset": self.total_asset
                        })

                pos.name = name
                pos.qty = qty
                pos.avg_price = avg_price
                
                # Only update price if we haven't received real-time updates recently (e.g. 10s)
                # This prevents overwriting accurate real-time price with potentially evaluated price from broker sync
                if time.time() - pos.last_update > 10:
                    pos.current_price = current_price
                
                if pos.qty <= 0:
                    # If sync returns 0 qty, treat as closed immediately?
                    # But notify_change above already sent "SELL_FILLED".
                    # Let's clean it up so we don't get "POSITION_CLOSED" on next sync when it disappears from list.
                    # Or should we send "POSITION_CLOSED" here instead of "SELL_FILLED" if qty is 0?
                    del self.positions[symbol]
                    # print(f"DEBUG: Removed {symbol} due to 0 qty in sync")
                
                pass 
            else:
                if qty > 0:
                     # [FIXED] Notify for New Position
                     self.positions[symbol] = Position(
                         symbol=symbol, 
                         name=name, 
                         qty=qty, 
                         avg_price=avg_price, 
                         current_price=current_price, 
                         tag=saved_tag, 
                         partial_taken=saved_partial,
                         max_price=saved_max
                     )
                     
                     if notify:
                         self._notify_change({
                            "type": "BUY_FILLED",
                            "symbol": symbol,
                            "qty": qty,
                            "price": avg_price,
                            "tag": saved_tag,
                            # [NEW] Enhanced Data
                            "exec_qty": qty,
                            "exec_price": avg_price,
                            "new_qty": qty,
                            "new_avg_price": avg_price,
                            "old_avg_price": 0.0,
                            "total_asset": self.total_asset
                         })
                else:
                     # Ignore 0 qty positions if they don't exist
                     pass
        
        # Remove positions that are no longer in broker
        for sym in list(self.positions.keys()):
            if sym not in current_symbols:
                # Position Closed
                old_pos = self.positions[sym]
                # Notify
                if notify:
                    self._notify_change({
                        "type": "POSITION_CLOSED",
                        "symbol": sym,
                        "qty": old_pos.qty, # Closed qty
                        "price": old_pos.current_price, # Approx exit price
                        "tag": old_pos.tag,
                        # [NEW] Enhanced Data
                        "exec_qty": old_pos.qty,
                        "exec_price": old_pos.current_price,
                        "new_qty": 0,
                        "new_avg_price": 0.0,
                        "old_avg_price": old_pos.avg_price,
                        "total_asset": self.total_asset
                    })
                del self.positions[sym]
        
        self.save_state()

    def _notify_change(self, info: Dict):
        for callback in self.on_position_change:
            try:
                callback(info)
            except Exception as e:
                print(f"Callback error: {e}")

    def save_state(self):
        """Save portfolio state (partial_taken, max_price) to file"""
        state = {}
        for symbol, pos in self.positions.items():
            state[symbol] = {
                "partial_taken": pos.partial_taken,
                "max_price": pos.max_price,
                "tag": pos.tag
            }
        
        try:
            with open("portfolio_state.json", "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4)
            # print(f"DEBUG: Saved portfolio state: {state}")
        except Exception as e:
            print(f"Failed to save portfolio state: {e}")

    def load_state(self):
        """Load portfolio state and apply to existing positions"""
        if not os.path.exists("portfolio_state.json"):
            print("DEBUG: portfolio_state.json not found.")
            return

        try:
            with open("portfolio_state.json", "r", encoding="utf-8") as f:
                state = json.load(f)
            
            # print(f"DEBUG: Loading portfolio state: {state}")
            for symbol, data in state.items():
                if symbol in self.positions:
                    pos = self.positions[symbol]
                    pos.partial_taken = data.get("partial_taken", False)
                    pos.max_price = data.get("max_price", pos.current_price)
                    pos.tag = data.get("tag", "")
                    pos.tag = data.get("tag", "")
                    # print(f"DEBUG: Restored state for {symbol}: Partial={pos.partial_taken}, Max={pos.max_price}")
        except Exception as e:
            print(f"Failed to load portfolio state: {e}")
