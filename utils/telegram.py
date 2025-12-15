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
        self.reload_config(config)

    def reload_config(self, config: Dict[str, Any]):
        """Reload configuration from dictionary"""
        self.config = config.get("telegram", {}) if "telegram" in config else config
        
        # Support both nested 'telegram' key and direct keys (flat config)
        # If config has 'telegram' key, use it. Otherwise assume config IS the telegram config or system config containing keys.
        # But looking at Engine.__init__, it passes self.system_config.
        # system_config typically contains flat keys like 'env_type', 'market_type'.
        # But where are telegram keys stored?
        # In secrets.yaml they are likely under 'telegram' section if merged?
        # Let's check how it was initialized: self.telegram = TelegramBot(self.system_config)
        # And system_config comes from config.get("system") combined with secrets?
        
        # In Engine.__init__:
        # secrets = self._load_config("config/secrets.yaml")
        # self._merge_config(self.config, secrets)
        # self.system_config = self.config.get("system", ...)
        
        # So if secrets.yaml has:
        # system:
        #   telegram:
        #     bot_token: ...
        # OR
        # system:
        #   bot_token: ...
        
        # Let's assume keys might be directly in config if flat, or in 'telegram' sub-dict.
        # The previous code was: self.config = config.get("telegram", {}) ... self.token = self.config.get("bot_token")
        # This implies config passed to __init__ (which is self.system_config) MUST have a 'telegram' key.
        
        # Let's stick to that pattern but be robust.
        
        self.raw_config = config.get("telegram", {})
        
        # If 'telegram' key didn't exist or was empty, maybe attributes are at root?
        # But original code strictly looked into .get("telegram", {}).
        # So we continue with that.
        
        self.token = self.raw_config.get("bot_token")
        self.chat_id = self.raw_config.get("chat_id")
        self.enable_trade = self.raw_config.get("enable_trade_alert", False)
        self.enable_system = self.raw_config.get("enable_system_alert", False)

        if not self.token or not self.chat_id:
            logger.warning("Telegram Bot Token or Chat ID not configured. Alerts disabled.")
            self.enabled = False
        else:
            self.enabled = True
            logger.info(f"Telegram Bot Configured. Trade: {self.enable_trade}, System: {self.enable_system}")

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
            self._send(f"🖥 <b>[시스템 알림]</b> {message}")

    def send_otp(self, otp: str):
        """Send Login OTP"""
        if self.enabled and self.enable_system:
            msg = f"🔐 <b>[로그인 인증]</b> 코드: <code>{otp}</code> (입력하여 로그인하세요)"
            self._send(msg)

    def send_trade_event(self, event_type: str, symbol: str, price: float, qty: int, side: str, stock_name: str = None):
        """Send Trade Alert (Korean, Concise, Name-based)"""
        if not self.enabled or not self.enable_trade:
            return

        emoji = "🔴" if side == "BUY" else "🔵"
        action = "매수" if side == "BUY" else "매도"
        
        # event_type translation map
        type_map = {
            "ORDER_SUBMITTED": "주문",
            "ORDER_FILLED": "체결",
            "POSITION_CLOSED": "청산", # or 매도체결
            "BUY": "매수",
            "SELL": "매도"
        }
        
        # Refine action description
        # e.g. "SELL POSITION_CLOSED" -> "매도 청산" -> Just "청산" or "매도완료"
        # If event_type containts "FILLED" or "CLOSED", it's a done deal.
        # If "SUBMITTED", it's an order placement.
        
        if "SUBMITTED" in event_type:
            desc = f"{action}주문"
        elif "FILLED" in event_type:
            desc = f"{action}체결"
        elif "CLOSED" in event_type:
            desc = "청산완료"
        else:
            desc = f"{action}"

        display_name = stock_name if stock_name else symbol
        
        # Format: 🔴 매수체결: 삼성전자 (10주, 50,000원)
        msg = (
            f"{emoji} <b>{desc}</b>: {display_name} ({qty}주, {price:,.0f}원)"
        )
        self._send(msg)
