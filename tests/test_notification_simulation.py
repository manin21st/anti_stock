import sys
import os
import time

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.portfolio import Portfolio
from utils.telegram import TelegramBot

# Mock Engine-like behavior
class MockEngine:
    def __init__(self):
        # Initialize with dummy config
        self.telegram = TelegramBot({"telegram": {"bot_token": "TEST", "chat_id": "TEST", "enable_trade_alert": True}})
        # Mock _send to print instead of request
        self.telegram._send = self.mock_send
        self.portfolio = Portfolio()
        self.portfolio.on_position_change.append(self.record_position_event)
        self.market_data = self # Mock market data
        
    def mock_send(self, text):
        print("\n" + "="*40)
        print(" [TELEGRAM MESSAGE]")
        print("-" * 40)
        
        # Debug: Show raw repr to ensure we received data
        try:
            # Force ASCII safe printing of the message content
            # Encode to ASCII, ignoring errors (strips emojis/Korean)
            safe_text = text.encode('ascii', 'ignore').decode('ascii')
            print(safe_text)
        except Exception as e:
            print(f"!!! Error printing message: {e}")
            
        print("="*40 + "\n")

    def get_stock_name(self, symbol):
        return "삼성전자" if symbol == "005930" else f"Stock_{symbol}"

    def record_position_event(self, change_info):
        print(f"DEBUG: Engine received event type: {change_info['type']}")
        
        event_type = change_info["type"]
        side = "BUY" if "BUY" in event_type else "SELL"
        if event_type == "POSITION_CLOSED":
             side = "SELL"

        stock_name = self.get_stock_name(change_info["symbol"])
        
        # Call Telegram
        self.telegram.send_trade_event(
            event_type=event_type,
            symbol=change_info["symbol"],
            price=float(change_info["price"]),
            qty=int(change_info["qty"]),
            side=side,
            stock_name=stock_name,
            position_info=change_info
        )

def run_simulation():
    print(">>> Starting Notification Simulation <<<\n")
    engine = MockEngine()
    
    # Scene 1: Initial Buy (New Position)
    print("[Scenario 1] Initial Buy: 10 sh @ 80,000")
    broker_data_1 = {
        "summary": [{"tot_evlu_amt": "10000000", "dnca_tot_amt": "2000000"}],
        "holdings": [{
            "pdno": "005930", "prdt_name": "삼성전자", "hldg_qty": "10", 
            "pchs_avg_pric": "80000.0", "prpr": "80000.0"
        }]
    }
    engine.portfolio.sync_with_broker(broker_data_1)
    time.sleep(1)

    # Scene 2: Additional Buy
    print("[Scenario 2] Additional Buy: 10 sh @ 82,000")
    broker_data_2 = {
        "summary": [{"tot_evlu_amt": "9180000", "dnca_tot_amt": "1180000"}],
        "holdings": [{
            "pdno": "005930", "prdt_name": "삼성전자", "hldg_qty": "20", 
            "pchs_avg_pric": "81000.0", "prpr": "82000.0"
        }]
    }
    engine.portfolio.sync_with_broker(broker_data_2)
    time.sleep(1)

    # Scene 3: Partial Sell (Profit)
    print("[Scenario 3] Partial Sell: 10 sh @ 85,000 (Profit)")
    broker_data_3 = {
        "summary": [{"tot_evlu_amt": "10030000", "dnca_tot_amt": "2030000"}],
        "holdings": [{
            "pdno": "005930", "prdt_name": "삼성전자", "hldg_qty": "10", 
            "pchs_avg_pric": "81000.0", "prpr": "85000.0"
        }]
    }
    engine.portfolio.sync_with_broker(broker_data_3)
    time.sleep(1)

    # Scene 4: Full Sell (Stop Loss/Exit)
    print("[Scenario 4] Full Sell: 10 sh @ 79,000 (Loss)")
    broker_data_4 = {
        "summary": [{"tot_evlu_amt": "10010000", "dnca_tot_amt": "2820000"}],
        "holdings": [] 
    }
    
    # Manually update current price in portfolio for accurate sell logging
    if "005930" in engine.portfolio.positions:
        engine.portfolio.positions["005930"].current_price = 79000.0
        
    engine.portfolio.sync_with_broker(broker_data_4)

if __name__ == "__main__":
    run_simulation()
