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
            logger.debug(f"Telegram Bot Configured. Trade: {self.enable_trade}, System: {self.enable_system}")

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

    def send_trade_event(self, event_type: str, symbol: str, price: float, qty: int, side: str, stock_name: str = None, position_info: Dict = None):
        """Send Trade Alert with Enhanced Data"""
        if not self.enabled or not self.enable_trade:
            return

        display_name = stock_name if stock_name else symbol
        
        # Prepare Data
        exec_price = price
        exec_qty = qty
        exec_amt = exec_price * exec_qty
        
        # Defaults if position_info not provided
        new_qty = 0
        new_avg = 0.0
        new_amt = 0
        tag = ""
        total_asset = 0
        
        if position_info:
            new_qty = int(position_info.get("new_qty", 0))
            new_avg = float(position_info.get("new_avg_price", 0.0))
            new_amt = int(new_qty * new_avg)
            tag = position_info.get("tag", "")
            total_asset = int(position_info.get("total_asset", 0))
            old_avg = float(position_info.get("old_avg_price", 0.0))

        # Format Message
        emoji = "🔴" if side == "BUY" else "🔵"
        title = "[매수체결]" if side == "BUY" else "[매도체결]"
        
        lines = [f"{emoji} <b>{title}</b> {display_name} ({symbol})"]
        lines.append(f"체결: {int(exec_price):,}원 | 수량: {exec_qty}주 | 금액: {int(exec_amt):,}원")
        
        if side == "BUY":
            lines.append(f"보유: {int(new_avg):,}원 | 수량: {new_qty}주 | 금액: {int(new_amt):,}원")
            if tag:
                lines.append(f"전략: {tag}")
        else:
            # SELL or CLOSED
            # PnL Calculation
            pnl_val = 0
            pnl_pct = 0.0
            
            # If old_avg is available, use it. Otherwise approximate with current price? No, huge error risk.
            if position_info and old_avg > 0:
                pnl_val = int((exec_price - old_avg) * exec_qty)
                pnl_pct = (exec_price - old_avg) / old_avg * 100
                
            pnl_sign = "+" if pnl_val >= 0 else ""
            
            lines.append(f"보유: {int(new_avg):,}원 | 수량: {new_qty}주 | 금액: {int(new_amt):,}원")
            lines.append(f"실현손익: {pnl_sign}{pnl_val:,}원 ({pnl_sign}{pnl_pct:.2f}%) 잔고: {total_asset:,}원 (추정)")
            
        msg = "\n".join(lines)
        self._send(msg)
