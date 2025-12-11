import logging
import requests
import threading
from typing import Dict, Any

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Telegram Bot with config
        config: {
            "bot_token": "...",
            "chat_id": "...",
            "enable_trade_alert": True,
            "enable_system_alert": True
        }
        """
        self.config = config.get("telegram", {})
        self.token = self.config.get("bot_token")
        self.chat_id = self.config.get("chat_id")
        self.enable_trade = self.config.get("enable_trade_alert", False)
        self.enable_system = self.config.get("enable_system_alert", False)

        if not self.token or not self.chat_id:
            logger.warning("Telegram Bot Token or Chat ID not configured. Alerts disabled.")
            self.enabled = False
        else:
            self.enabled = True
            logger.info("Telegram Bot Initialized.")

    def _send(self, text: str):
        if not self.enabled:
            return

        def _request():
            try:
                url = f"https://api.telegram.org/bot{self.token}/sendMessage"
                data = {
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML"
                }
                requests.post(url, data=data, timeout=5)
            except Exception as e:
                logger.error(f"Failed to send Telegram message: {e}")

        # Send asynchronously to avoid blocking the trading loop
        threading.Thread(target=_request, daemon=True).start()

    def send_message(self, text: str):
        """Send generic message"""
        if self.enabled:
            self._send(text)

    def send_system_alert(self, message: str):
        """Send system alert if enabled"""
        if self.enabled and self.enable_system:
            self._send(f"🖥 <b>[SYSTEM ALERT]</b>\n{message}")

    def send_otp(self, otp: str):
        """Send Login OTP"""
        if self.enabled and self.enable_system:
            msg = f"🔐 <b>[LOGIN OTP]</b>\nCode: <code>{otp}</code>\n\nUse this code to log in."
            self._send(msg)

    def send_trade_event(self, event_type: str, symbol: str, price: float, qty: int, side: str):
        """Send Trade Alert"""
        if not self.enabled or not self.enable_trade:
            return

        emoji = "🔴" if side == "BUY" else "🔵"
        msg = (
            f"{emoji} <b>{side} {event_type}</b>\n"
            f"Symbol: <code>{symbol}</code>\n"
            f"Price: {price:,.0f} KRW\n"
            f"Qty: {qty}\n"
            f"Amt: {price * qty:,.0f} KRW"
        )
        self._send(msg)
