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
        # Determine TR ID
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
        
        # logger.info(f"Sending Order: {buy_sell_gb} {symbol} {qty} @ {ord_dv} (Tag: {tag})")
        # Log suppression will be handled by the caller (Backtester) setting logger level.
        # But we can keep this for Real Mode.
        logger.info(f"Sending Order: {buy_sell_gb} {symbol} {qty} @ {ord_dv} (Tag: {tag})")
        
        res = ka.send_order(tr_id, params)
        
        if res.isOK():
            # In Backtest Mode, res.getBody() returns a mock object with 'ODNO'
            try:
                msg = getattr(res.getBody(), 'msg1', 'Success')
                output = res.getBody().output
                odno = output.get('ODNO', 'UNKNOWN')
            except Exception:
                # Fallback for mock if structure differs slightly
                msg = "Success"
                odno = "MOCK"

            logger.info(f"Order Success: {msg} (Order No: {odno})")
            
            # Notify listeners
            order_info = {
                "symbol": symbol,
                "qty": qty,
                "side": "BUY" if buy_sell_gb == "1" else "SELL",
                "type": "MARKET" if ord_dv == "01" else "LIMIT",
                "price": price,
                "tag": tag,
                "order_no": odno
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
            from datetime import datetime
            is_weekend = datetime.now().weekday() >= 5
            log_fn = logger.warning if is_weekend else logger.error
            log_fn("Failed to get balance: Response is None")
            return {}

        if isinstance(res, dict): # Handle mock response which is already a dict
             return {
                "holdings": res.get("output2", []), # Note: kis_api mock returns dict with output1/2 keys
                "summary": res.get("output1", [])
            }
        
        # Determine if it's a real response object (has isOK method)
        if hasattr(res, 'isOK'):
            if res.isOK():
                return {
                    "holdings": res.getBody().output1,
                    "summary": res.getBody().output2
                }
            else:
                from datetime import datetime
                is_weekend = datetime.now().weekday() >= 5
                log_fn = logger.warning if is_weekend else logger.error
                log_fn(f"Failed to get balance: {res.getErrorMessage()}")
                return {}
        
        # Fallback for dict mock response if passed directly (safeguard)
        return res if isinstance(res, dict) else {}
