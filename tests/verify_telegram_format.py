import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.telegram import TelegramBot

class TestTelegramFormatting(unittest.TestCase):
    def setUp(self):
        self.config = {
            "telegram": {
                "bot_token": "dummy_token",
                "chat_id": "dummy_chat_id",
                "enable_trade_alert": True,
                "enable_system_alert": True
            }
        }
        self.bot = TelegramBot(self.config)
        # Mock the _send method to capture the message instead of sending network request
        self.bot._send = MagicMock()

    def test_trade_event_buy_order_submitted(self):
        # Scenario: submitted buy order for Samsung Electronics
        self.bot.send_trade_event(
            event_type="ORDER_SUBMITTED",
            symbol="005930",
            price=80000,
            qty=10,
            side="BUY",
            stock_name="삼성전자"
        )
        
        # Expected: 🔴 매수주문: 삼성전자 (10주, 80,000원)
        args, _ = self.bot._send.call_args
        msg = args[0]
        # print(f"Captured Message (Buy Order): {msg}")
        self.assertIn("🔴", msg)
        self.assertIn("매수주문", msg)
        self.assertIn("삼성전자", msg)
        self.assertIn("10주", msg)
        self.assertIn("80,000원", msg)

    def test_trade_event_sell_filled(self):
        # Scenario: filled sell order for SK Hynix
        self.bot.send_trade_event(
            event_type="ORDER_FILLED",
            symbol="000660",
            price=120000,
            qty=5,
            side="SELL",
            stock_name="SK하이닉스"
        )
        
        # Expected: 🔵 매도체결: SK하이닉스 (5주, 120,000원)
        args, _ = self.bot._send.call_args
        msg = args[0]
        # print(f"Captured Message (Sell Filled): {msg}")
        self.assertIn("🔵", msg)
        self.assertIn("매도체결", msg)
        self.assertIn("SK하이닉스", msg)
        self.assertIn("5주", msg)
        self.assertIn("120,000원", msg)

    def test_trade_event_position_closed(self):
        # Scenario: position closed (Sell)
        self.bot.send_trade_event(
            event_type="POSITION_CLOSED",
            symbol="005930",
            price=85000,
            qty=10,
            side="SELL",
            stock_name="삼성전자"
        )
        
        # Expected: 🔵 청산완료: 삼성전자 (10주, 85,000원)
        args, _ = self.bot._send.call_args
        msg = args[0]
        # print(f"Captured Message (Closed): {msg}")
        self.assertIn("🔵", msg)
        self.assertIn("청산완료", msg)
        self.assertIn("삼성전자", msg)

    def test_system_alert(self):
        self.bot.send_system_alert("테스트 메시지입니다.")
        args, _ = self.bot._send.call_args
        msg = args[0]
        # print(f"Captured Message (System): {msg}")
        self.assertIn("시스템 알림", msg)
        self.assertIn("테스트 메시지입니다.", msg)

if __name__ == '__main__':
    unittest.main()
