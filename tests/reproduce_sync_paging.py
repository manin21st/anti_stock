import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import Engine
from core import kis_api as ka

class MockResponse:
    def __init__(self, is_ok, body):
        self._is_ok = is_ok
        self._body = MagicMock()
        # Setup body attributes dynamically
        for k, v in body.items():
            setattr(self._body, k, v)
            
        # Also support dict access for getBody()
        self._body.__getitem__ = lambda s, x: body.get(x)
        self._body.keys = lambda: body.keys()
        self._body._fields = list(body.keys()) # Simulate namedtuple fields

    def isOK(self):
        return self._is_ok
    
    def getBody(self):
        return self._body
    
    def getErrorCode(self):
        return "0"
    
    def getErrorMessage(self):
        return ""

class TestSyncPagination(unittest.TestCase):
    @patch('core.kis_api.getTREnv')
    @patch('core.kis_api.auth')
    @patch('core.kis_api.auth_ws')
    @patch('core.kis_api.fetch_daily_ccld')
    def test_sync_pagination(self, mock_fetch, mock_auth_ws, mock_auth, mock_get_env):
        print("\n[Test] Starting Sync Pagination Test...")
        
        # Setup Mock Env
        mock_env = MagicMock()
        mock_env.my_acct = "12345678"
        mock_env.my_prod = "01"
        mock_get_env.return_value = mock_env
        
        # Setup Mock Responses for 2 Pages
        # Page 1: 2 items, has next key "NEXT_KEY_123"
        # Page 2: 1 item, no next key
        
        page1_data = {
            "output1": [
                {
                    "odno": "1001", "pdno": "005930", "tot_ccld_qty": "10", 
                    "avg_prvs": "60000", "sll_buy_dvsn_cd": "02", 
                    "ord_dt": "20251218", "ord_tmd": "100000"
                },
                {
                    "odno": "1002", "pdno": "000660", "tot_ccld_qty": "5", 
                    "avg_prvs": "120000", "sll_buy_dvsn_cd": "01", 
                    "ord_dt": "20251218", "ord_tmd": "100500"
                }
            ],
            "ctx_area_nk100": "NEXT_KEY_123",
            "ctx_area_fk100": ""
        }
        
        page2_data = {
            "output1": [
                {
                    "odno": "1003", "pdno": "035420", "tot_ccld_qty": "3", 
                    "avg_prvs": "200000", "sll_buy_dvsn_cd": "02", 
                    "ord_dt": "20251217", "ord_tmd": "140000"
                }
            ],
            "ctx_area_nk100": "", # End of pages
            "ctx_area_fk100": ""
        }
        
        # Configure mock to return Page 1 then Page 2
        mock_fetch.side_effect = [
            MockResponse(True, page1_data),
            MockResponse(True, page2_data)
        ]
        
        # Initialize Engine (mocking init auth)
        engine = Engine()
        # Clear any existing history
        engine.trade_history = []
        
        # Run Sync
        print("[Test] Calling sync_trade_history...")
        count = engine.sync_trade_history("20251217", "20251218")
        
        # Verify
        print(f"[Test] Sync completed. Total extracted: {count}")
        
        # Assertions
        self.assertEqual(count, 3, "Should have synced 3 trades total")
        self.assertEqual(len(engine.trade_history), 3, "Trade history should have 3 items")
        
        # Check IDs
        ids = [t.order_id for t in engine.trade_history]
        self.assertIn("1001", ids)
        self.assertIn("1002", ids)
        self.assertIn("1003", ids)
        
        # Verify Pagination Call Args
        self.assertEqual(mock_fetch.call_count, 2, "Should obtain 2 pages")
        
        # Check arguments of second call to ensure key was passed
        args, kwargs = mock_fetch.call_args_list[1]
        self.assertEqual(kwargs['ctx_area_nk'], "NEXT_KEY_123", "Second call should use the next key from Page 1")
        
        print("[Test] SUCCESS: Pagination logic verified.")
        print("Fetched Items:")
        for t in engine.trade_history:
            print(f" - {t.timestamp} | {t.symbol} | {t.side} | Qty: {t.qty} | OrderID: {t.order_id}")

if __name__ == '__main__':
    unittest.main()
