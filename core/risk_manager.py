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
        
        # 2. Financial Check (Fix 1: D+2 Deposit & Cash Ratio)
        # Estimated Cost (Trading Fee + Tax buffer ~ 0.25% for safety)
        estimated_cost = qty * price * 1.0025
        
        # D+2 Deposit Check
        # We must ensure that after this purchase, D+2 deposit remains positive
        # And also respect Cash Ratio
        
        cash_ratio = self.config.get("common", {}).get("cash_ratio", 0.2)
        total_asset = self.portfolio.total_asset
        
        # Required Cash to maintain ratio
        required_cash = total_asset * cash_ratio
        
        # Available Cash for Betting = (D+2 Deposit) - Required Cash
        # But we should use the smaller of D+2 or Cash? Usually D+2 is the constraint for settlement.
        available_deposit = self.portfolio.deposit_d2
        
        # Effective Buying Power
        buying_power = available_deposit - required_cash
        
        if buying_power < estimated_cost:
            logger.warning(f"[매수 거부] {symbol} | 필요금액: {int(estimated_cost):,}원 | 가용 D+2: {int(available_deposit):,}원 | 한도(현금비중 고려): {int(buying_power):,}원")
            return False
            
        return True

    def check_daily_loss(self) -> bool:
        """Check if daily loss limit is breached"""
        # Need to track daily starting equity
        # For now, return True (Safe)
        return True
