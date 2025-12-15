
import unittest
from unittest.mock import MagicMock
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.portfolio import Portfolio

class TestDuplicateNotification(unittest.TestCase):
    def setUp(self):
        self.portfolio = Portfolio()
        # Mock the callback to capture events
        self.events = []
        self.portfolio.on_position_change.append(self.record_event)
        
        from core.portfolio import Position
        # Add a dummy position directly
        self.portfolio.positions["005930"] = Position(
            symbol="005930", 
            name="Samsung", 
            qty=10, 
            avg_price=50000, 
            current_price=50000, 
            tag="test_strategy"
        )
        # Clear init events
        self.events.clear()

    def record_event(self, event):
        self.events.append(event)

    def test_sync_zero_qty(self):
        """Test Scenario: Sync returns qty=0. Should trigger POSITION_CLOSED and remove position."""
        print("\n[Test] Sync with Quantity 0")
        
        # Mock Balance Data from Broker with 0 Qty
        balance_data = {
            'holdings': [{
                'pdno': '005930',
                'prdt_name': 'Samsung',
                'hldg_qty': '0', # API string format
                'pchs_avg_pric': '50000',
                'prpr': '55000',
                'evlu_amt': '0',
                'pchs_amt': '0'
            }],
            'summary': [{
                'dnca_tot_amt': '1000000',
                'tot_evlu_amt': '1000000',
                'nass_amt': '1000000'
            }]
        }
        
        self.portfolio.sync_with_broker(balance_data)
        
        # Check Events
        print(f"Events captured: {[e['type'] for e in self.events]}")
        
        # Expectation: 1 POSITION_CLOSED event
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0]['type'], 'POSITION_CLOSED')
        
        # Expectation: Position removed
        self.assertNotIn("005930", self.portfolio.positions)
        print("Position successfully removed.")

        # Step 2: Sync again with Empty List (Missing)
        print("[Test] Sync with Empty List (Next Cycle)")
        self.events.clear()
        
        balance_data_empty = {
            'holdings': [],
            'summary': balance_data['summary']
        }
        self.portfolio.sync_with_broker(balance_data_empty)
        
        print(f"Events captured: {[e['type'] for e in self.events]}")
        
        # Expectation: 0 Events (Already removed)
        self.assertEqual(len(self.events), 0)
        print("No duplicate event triggered.")

    def test_partial_sell(self):
        """Test Scenario: Partial Sell (10 -> 5). Should trigger SELL_FILLED."""
        print("\n[Test] Sync with Partial Sell (Qty 5)")
        
        balance_data = {
            'holdings': [{
                'pdno': '005930',
                'prdt_name': 'Samsung',
                'hldg_qty': '5',
                'pchs_avg_pric': '50000',
                'prpr': '55000',
                'evlu_amt': '275000',
                'pchs_amt': '250000'
            }],
            'summary': {}
        }
        
        self.portfolio.sync_with_broker(balance_data)
        
        print(f"Events captured: {[e['type'] for e in self.events]}")
        
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0]['type'], 'SELL_FILLED')
        self.assertEqual(self.events[0]['qty'], 5) # 10 - 5 = 5 sold
        
        # Position should still exist
        self.assertIn("005930", self.portfolio.positions)
        self.assertEqual(self.portfolio.positions["005930"].qty, 5)

if __name__ == '__main__':
    unittest.main()
