import logging

logger = logging.getLogger(__name__)

class RiskManager:
    def __init__(self, portfolio):
        self.portfolio = portfolio
        self.max_positions = 10
        self.max_loss_daily_pct = 5.0 # 5%

    def can_open_new_position(self, symbol: str, qty: int) -> bool:
        """Check if new position can be opened"""
        if len(self.portfolio.positions) >= self.max_positions:
            logger.warning(f"Risk Check Failed: Max positions reached ({len(self.portfolio.positions)})")
            return False
        
        # Additional checks: Buying Power, Daily Loss Limit, etc.
        
        return True

    def check_daily_loss(self) -> bool:
        """Check if daily loss limit is breached"""
        # Need to track daily starting equity
        # For now, return True (Safe)
        return True
