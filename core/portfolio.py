from dataclasses import dataclass
from typing import Dict, Optional, Any
import json
import os
import time
import logging
from datetime import datetime
from core.dao import TradeDAO

logger = logging.getLogger(__name__)

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
    first_acquired_at: float = 0.0 # Timestamp of first acquisition

class Portfolio:
    def __init__(self, state_file: Optional[str] = "portfolio_state.json"):
        """
        Initialize Portfolio.
        state_file: Path to save state. If None, persistence is disabled (for Backtesting).
        """
        self.positions: Dict[str, Position] = {}
        self.cash: float = 0.0
        self.deposit_d1: float = 0.0 # Next Day Deposit
        self.deposit_d2: float = 0.0 # D+2 Deposit
        self.total_asset: float = 0.0
        self.on_position_change = [] # List of callbacks (change_info: dict)
        
        # Optimistic Update Tracking
        self.pending_buy_amount: float = 0.0 # Amount reserved for pending orders
        
        self.state_file = state_file

        # State Cache (In-Memory)
        self._state_cache = {}
        self._load_state_to_cache() # Initial Load

        # Backfill check cache
        self._checked_backfill = set()
        
        if not self.state_file:
            logger.info("Portfolio initialized in NON-PERSISTENT mode.")

    def update_position(self, symbol: str, qty: int, price: float, tag: str = ""):
        """Update position from order execution"""
        if symbol not in self.positions:
            if qty > 0:
                self.positions[symbol] = Position(symbol, symbol, qty, price, price, tag, max_price=price, first_acquired_at=time.time())
        else:
            pos = self.positions[symbol]
            if qty > 0: # Buy more
                total_cost = (pos.qty * pos.avg_price) + (qty * price)
                pos.qty += qty
                pos.avg_price = total_cost / pos.qty
                pos.max_price = max(pos.max_price, price)
            else: # Sell
                # qty is negative
                pos.qty += qty
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
        return self.total_asset

    @property
    def buying_power(self) -> float:
        """Calculated Buying Power (Optimistic)"""
        # Ensure we don't go negative
        power = self.deposit_d2 - self.pending_buy_amount
        return max(0.0, power)
    
    def on_order_sent(self, order_info: Dict, market_data: Any):
        """Handle Order Sent Event for Optimistic Update"""
        side = order_info.get("side")
        qty = order_info.get("qty", 0)
        symbol = order_info.get("symbol")
        tag = order_info.get("tag", "")
        price = order_info.get("price", 0)
        
        # 0. Get Current Price if needed (for Market Order or Valuation)
        if price <= 0:
             price = market_data.get_last_price(symbol)
             # If still 0, we can't estimate valuation accurately, but we can still update Qty.
        
        # 1. Optimistic Position Update (Fix for Duplicate Orders)
        # Immediately reflect the change in local state so strategies don't fire duplicates.
        if side == "SELL" and qty > 0:
            # Deduct quantity immediately
            # Note: update_position handles removal if qty <= 0
            self.update_position(symbol, -qty, price, tag)
            logger.info(f"[Optimistic] SELL {symbol}: -{qty} (Prevents Dup)")
            
        elif side == "BUY" and qty > 0:
            # Add quantity immediately (Assuming fill)
            # This prevents firing multiple buys if strategy checks position count
            if price > 0:
                self.update_position(symbol, qty, price, tag)
                logger.info(f"[Optimistic] BUY {symbol}: +{qty}")
        
        # 2. Buying Power Management (Cash Reservation)
        if side == "BUY" and qty > 0:
            if price > 0:
                # Estimate cost with fee/tax (BUY: 0.015% fee approx, no tax)
                # Let's use 100.25% safely
                 cost = qty * price * 1.0025
                 self.pending_buy_amount += cost
                 logger.info(f"[Optimistic] Pending Buy Amount: +{int(cost):,} (Total: {int(self.pending_buy_amount):,})")
            else:
                 logger.warning(f"Optimistic Update: No price for {symbol}, cannot estimate pending cash.")

    def sync_with_broker(self, broker_balance: Dict, notify: bool = True, tag_lookup_fn=None, allow_clear: bool = False):
        """Sync internal state with actual broker balance"""
        if not broker_balance:
            return

        self._update_balance(broker_balance.get("summary", []))
        # Handle dict or list for holdings/summary to be safe? Broker ensures it's list.
        self._sync_positions(broker_balance.get("holdings", []), notify, tag_lookup_fn, allow_clear)
        self.save_state()

    def _update_balance(self, summary: list):
        if summary:
            # Safely handle if summary is missing keys (e.g. unexpected API change or mock deficiency)
            # Default to 0
            def get_float(d, k): return float(d.get(k, 0))
            
            s = summary[0]
            self.cash = get_float(s, "dnca_tot_amt")
            self.deposit_d1 = get_float(s, "nxdy_excc_amt")
            self.deposit_d2 = get_float(s, "prvs_rcdl_excc_amt")
            self.total_asset = get_float(s, "tot_evlu_amt")
            
            # Reset Pending Amount on Sync (Assume Broker Balance is authoritative)
            if self.pending_buy_amount > 0:
                 logger.debug(f"Resetting Pending Buy Amount (Prev: {int(self.pending_buy_amount):,}) due to Sync.")
            self.pending_buy_amount = 0.0
            
            # Fallback for Backtest Mock if deposit fields are missing
            if self.deposit_d2 == 0 and self.cash > 0 and not self.state_file:
                 # In backtest mode (inferred by no state_file), treat cash as buying power
                 self.deposit_d2 = self.cash
                 self.deposit_d1 = self.cash

    def _sync_positions(self, holdings: list, notify: bool, tag_lookup_fn, allow_clear: bool):
        if not holdings and self.positions and not allow_clear:
            logger.warning(f"Broker returned 0 holdings while local has {len(self.positions)}. Ignoring sync to prevent data loss.")
            # In backtest, allow_clear should be True if we want to confirm clearing? 
            # Or if broker intentionally returns empty.
            # Usually keep this safety.
            return

        current_symbols = set()
        for h in holdings:
            symbol = h["pdno"]
            name = h.get("prdt_name", symbol)
            qty = int(h["hldg_qty"])
            avg_price = float(h["pchs_avg_pric"])
            current_price = float(h["prpr"])

            current_symbols.add(symbol)

            saved_data = self._state_cache.get(symbol, {})
            saved_tag = saved_data.get("tag", "")
            if not saved_tag and tag_lookup_fn:
                saved_tag = tag_lookup_fn(symbol) or ""

            # Only check backfill in Real Mode (Persistence enabled)
            if self.state_file:
                self._check_backfill_acquired_time(symbol, saved_data.get("first_acquired_at", 0.0))

            if symbol in self.positions:
                self._update_existing_position(symbol, name, qty, avg_price, current_price, saved_tag, notify)
            else:
                self._create_new_position(symbol, name, qty, avg_price, current_price, saved_data, saved_tag, notify)

        self._remove_closed_positions(current_symbols, notify)

    def _check_backfill_acquired_time(self, symbol: str, saved_acquired_at: float):
        if symbol not in self._checked_backfill:
             try:
                 last_entry = TradeDAO.get_last_entry_date(symbol)
                 if last_entry:
                     ft_ts = last_entry.timestamp()
                     if saved_acquired_at == 0.0 or abs(ft_ts - saved_acquired_at) > 10.0:
                         logger.debug(f"Correction: Backfilling acquired time for {symbol}: {saved_acquired_at} -> {ft_ts}")
                 self._checked_backfill.add(symbol)
             except Exception as e:
                 logger.warning(f"Failed to backfill acquired time for {symbol}: {e}")

    def _update_existing_position(self, symbol, name, qty, avg_price, current_price, tag, notify):
        pos = self.positions[symbol]
        old_avg_price = pos.avg_price

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
                    "price": avg_price if diff > 0 else current_price,
                    "tag": tag,
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

        if time.time() - pos.last_update > 10:
            pos.current_price = current_price

        if pos.qty <= 0:
            del self.positions[symbol]

    def _create_new_position(self, symbol, name, qty, avg_price, current_price, saved_data, tag, notify):
        if qty > 0:
             self.positions[symbol] = Position(
                 symbol=symbol,
                 name=name,
                 qty=qty,
                 avg_price=avg_price,
                 current_price=current_price,
                 tag=tag,
                 partial_taken=saved_data.get("partial_taken", False),
                 max_price=saved_data.get("max_price", current_price),
                 first_acquired_at=saved_data.get("first_acquired_at", 0.0) or time.time()
             )

             if notify:
                 self._notify_change({
                    "type": "BUY_FILLED",
                    "symbol": symbol,
                    "qty": qty,
                    "price": avg_price,
                    "tag": tag,
                    "exec_qty": qty,
                    "exec_price": avg_price,
                    "new_qty": qty,
                    "new_avg_price": avg_price,
                    "old_avg_price": 0.0,
                    "total_asset": self.total_asset
                 })

    def _remove_closed_positions(self, current_symbols: set, notify: bool):
        for sym in list(self.positions.keys()):
            if sym not in current_symbols:
                old_pos = self.positions[sym]
                if notify:
                    self._notify_change({
                        "type": "POSITION_CLOSED",
                        "symbol": sym,
                        "qty": old_pos.qty,
                        "price": old_pos.current_price,
                        "tag": old_pos.tag,
                        "exec_qty": old_pos.qty,
                        "exec_price": old_pos.current_price,
                        "new_qty": 0,
                        "new_avg_price": 0.0,
                        "old_avg_price": old_pos.avg_price,
                        "total_asset": self.total_asset
                    })
                del self.positions[sym]

    def _notify_change(self, info: Dict):
        for callback in self.on_position_change:
            try:
                callback(info)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def save_state(self):
        """Save portfolio state to file and memory"""
        if not self.state_file:
            return

        state = {}
        for symbol, pos in self.positions.items():
            state[symbol] = {
                "partial_taken": pos.partial_taken,
                "max_price": pos.max_price,
                "tag": pos.tag,
                "first_acquired_at": pos.first_acquired_at
            }

        if state == self._state_cache:
            return

        self._state_cache = state

        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save portfolio state: {e}")

    def _load_state_to_cache(self):
        """Load portfolio state into memory cache once"""
        if not self.state_file or not os.path.exists(self.state_file):
            self._state_cache = {}
            return

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                self._state_cache = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load portfolio state: {e}")
            self._state_cache = {}

    def load_state(self):
        pass
