import logging

logger = logging.getLogger(__name__)

class RiskManager:
    def __init__(self, portfolio, config: dict = {}):
        self.portfolio = portfolio
        self.config = config
        self.max_positions = config.get("common", {}).get("max_positions", 10)
        self.max_loss_daily_pct = 5.0 # 5%

    def can_open_new_position(self, symbol: str, qty: int, price: float) -> bool:
        """Check if new position can be opened safely"""
        # 1. Available Slot Check
        if len(self.portfolio.positions) >= self.max_positions:
            logger.warning(f"Risk Check Failed: Max positions reached ({len(self.portfolio.positions)})")
            return False
        
        # 2. Financial Check (Fix 1: D+2 Deposit)
        # Estimated Cost (Trading Fee + Tax buffer ~ 0.25% for safety)
        estimated_cost = qty * price * 1.0025
        
        # D+2 Deposit Check
        # We use D+2 deposit as the buying power limit
        buying_power = self.portfolio.deposit_d2
        
        if buying_power < estimated_cost:
            logger.warning(f"[매수 거부] {symbol} | 필요금액: {int(estimated_cost):,}원 | 가용 D+2: {int(buying_power):,}원")
            return False
            
        return True

    def check_daily_loss(self) -> bool:
        """Check if daily loss limit is breached"""
        # Need to track daily starting equity
        # For now, return True (Safe)
        return True
