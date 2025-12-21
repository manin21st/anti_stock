import logging
from typing import Dict, Optional, List
import sys
import os
import time

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import kis_api as ka

logger = logging.getLogger(__name__)

class Broker:
    def __init__(self):
        self.account_number = ka.getTREnv().my_acct
        self.account_code = ka.getTREnv().my_prod
        self.env_dv = "demo" if ka.isPaperTrading() else "real"
        self.on_order_sent = [] # List of callbacks (order_info: dict)
        
        # Simulation State
        self.simulation_mode = False
        self.virtual_balance = {'cash': 0}
        self.virtual_positions = {}
        self.pending_orders = []

    def set_simulation_mode(self, mode: bool, initial_cash: int = 100000000):
        self.simulation_mode = mode
        if mode:
            self.virtual_balance = {'cash': initial_cash}
            self.virtual_positions = {}
            self.pending_orders = []
            logger.info(f"Broker switched to SIMULATION mode. Cash: {initial_cash}")

    def buy_market(self, symbol: str, qty: int, tag: str = "") -> bool:
        """Buy at market price"""
        return self._send_order(symbol, qty, "1", "01", tag) # 01: Market Price

    def sell_market(self, symbol: str, qty: int, tag: str = "") -> bool:
        """Sell at market price"""
        return self._send_order(symbol, qty, "2", "01", tag)

    def buy_limit(self, symbol: str, qty: int, price: int, tag: str = "") -> bool:
        """Buy at limit price"""
        return self._send_order(symbol, qty, "1", "00", tag, price) # 00: Limit Price

    def sell_limit(self, symbol: str, qty: int, price: int, tag: str = "") -> bool:
        """Sell at limit price"""
        return self._send_order(symbol, qty, "2", "00", tag, price)

    def _send_order(self, symbol: str, qty: int, buy_sell_gb: str, ord_dv: str, tag: str, price: int = 0) -> bool:
        """
        Send order to KIS API
        buy_sell_gb: 1 (Buy), 2 (Sell)
        ord_dv: 00 (Limit), 01 (Market)
        """
        # TR ID for Order
        # Real: TTTC0802U (Buy), TTTC0801U (Sell)
        # Demo: VTTC0802U (Buy), VTTC0801U (Sell)
        
        tr_id = ""
        
        if self.simulation_mode:
            # Buffer order for simulation
            order = {
                "symbol": symbol,
                "qty": qty,
                "buy_sell_gb": buy_sell_gb,
                "ord_dv": ord_dv,
                "tag": tag,
                "price": price,
                "timestamp": time.time()
            }
            self.pending_orders.append(order)
            logger.info(f"Sim: Order Buffered {buy_sell_gb} {symbol} {qty}")
            return True

        if self.env_dv == "real":
            tr_id = "TTTC0802U" if buy_sell_gb == "1" else "TTTC0801U"
        else:
            tr_id = "VTTC0802U" if buy_sell_gb == "1" else "VTTC0801U"
            
        params = {
            "CANO": self.account_number,
            "ACNT_PRDT_CD": self.account_code,
            "PDNO": symbol,
            "ORD_DVSN": ord_dv,
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price) if price > 0 else "0",
        }
        
        logger.info(f"Sending Order: {buy_sell_gb} {symbol} {qty} @ {ord_dv} (Tag: {tag})")
        
        res = ka.send_order(tr_id, params)
        
        if res.isOK():
            logger.info(f"Order Success: {res.getBody().msg1} (Order No: {res.getBody().output['ODNO']})")
            
            # Notify listeners
            order_info = {
                "symbol": symbol,
                "qty": qty,
                "side": "BUY" if buy_sell_gb == "1" else "SELL",
                "type": "MARKET" if ord_dv == "01" else "LIMIT",
                "price": price,
                "tag": tag,
                "order_no": res.getBody().output['ODNO']
            }
            for callback in self.on_order_sent:
                try:
                    callback(order_info)
                except Exception as e:
                    logger.error(f"Callback error: {e}")
            
            return True
        else:
            logger.error(f"Order Failed: {res.getErrorMessage()}")
            return False

    def get_balance(self) -> Dict:
        """Get account balance"""
        if self.simulation_mode:
            # Return virtual balance in API format
            holdings = []
            total_buy = 0
            for sym, p in self.virtual_positions.items():
                holdings.append({
                    "pdno": sym,
                    "prdt_name": sym,
                    "hldg_qty": str(p['qty']),
                    "pchs_avg_pric": str(p['avg_price']),
                    "prpr": "0", # Unknown here
                    "evlu_amt": "0",
                    "pchs_amt": str(p['amount']),
                    "evlu_pfls_amt": "0",
                    "evlu_pfls_rt": "0"
                })
                total_buy += p['amount']
            
            summary = {
                "dnca_tot_amt": str(self.virtual_balance['cash']),
                "tot_evlu_amt": str(total_buy + self.virtual_balance['cash']),
                "nass_amt": str(total_buy + self.virtual_balance['cash'])
            }
            return {
                "holdings": holdings,
                "summary": [summary]
            }

        # TR ID: TTTC8434R (Real), VTTC8434R (Demo) - Inquire Balance
        tr_id = "TTTC8434R" if self.env_dv == "real" else "VTTC8434R"
        
        params = {
            "CANO": self.account_number,
            "ACNT_PRDT_CD": self.account_code,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "N",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        
        res = ka.get_balance(tr_id, params)
        
        if res is None:
            logger.error("Failed to get balance: Response is None")
            return {}

        if res.isOK():
            # output1: Holdings list
            # output2: Account summary (Total asset, deposit, etc.)
            return {
                "holdings": res.getBody().output1,
                "summary": res.getBody().output2
            }
        else:
            logger.error(f"Failed to get balance: {res.getErrorMessage()}")
            return {}
            return {}

    def process_simulation_orders(self, current_prices: Dict[str, float]):
        """
        Process pending orders in simulation mode.
        current_prices: {symbol: price}
        """
        if not self.simulation_mode:
            return

        executed_orders = []
        for order in self.pending_orders:
            symbol = order['symbol']
            qty = int(order['qty'])
            side = order['buy_sell_gb'] # "1": Buy, "2": Sell
            current_price = current_prices.get(symbol, 0)
            
            if current_price <= 0:
                continue
                
            # Logic for Limit/Market
            exe_price = current_price
            if order['ord_dv'] == "00": # Limit
                limit_price = float(order['price'])
                if side == "1" and current_price > limit_price: continue
                if side == "2" and current_price < limit_price: continue
            
            # Execute
            success = False
            if side == "1": # BUY
                cost = exe_price * qty
                fee = cost * 0.00015
                total_cost = cost + fee
                if self.virtual_balance['cash'] >= total_cost:
                    self.virtual_balance['cash'] -= total_cost
                    if symbol not in self.virtual_positions:
                        self.virtual_positions[symbol] = {'qty': 0, 'avg_price': 0, 'amount': 0}
                    p = self.virtual_positions[symbol]
                    new_qty = p['qty'] + qty
                    new_amt = p['amount'] + cost
                    p['qty'] = new_qty
                    p['amount'] = new_amt
                    p['avg_price'] = new_amt / new_qty
                    success = True
            elif side == "2": # SELL
                if symbol in self.virtual_positions and self.virtual_positions[symbol]['qty'] >= qty:
                    revenue = exe_price * qty
                    fee = revenue * 0.00015 + revenue * 0.002 # Fee+Tax
                    net = revenue - fee
                    self.virtual_balance['cash'] += net
                    p = self.virtual_positions[symbol]
                    p['qty'] -= qty
                    p['amount'] = p['avg_price'] * p['qty'] # Reduce book value prop? Or just standard accounting
                    # Standard: Avg Price doesn't change. Book value drops by proportion? 
                    # Or simpler: Amount is just tracking cost basis?
                    # Usually Amount = AvgPrice * Qty
                    if p['qty'] <= 0:
                         del self.virtual_positions[symbol]
                    success = True

            if success:
                logger.info(f"Sim Executed: {side} {symbol} {qty} @ {exe_price}")
                executed_orders.append(order)
                # Notify
                order_info = {
                    "symbol": symbol,
                    "qty": qty,
                    "side": "BUY" if side == "1" else "SELL",
                    "type": "MARKET" if order['ord_dv'] == "01" else "LIMIT",
                    "price": exe_price,
                    "tag": order.get('tag', ''),
                    "order_no": f"SIM_{int(time.time()*1000)}_{qty}"
                }
                for cb in self.on_order_sent:
                    try: cb(order_info)
                    except: pass
        
        for o in executed_orders:
            if o in self.pending_orders:
                self.pending_orders.remove(o)
