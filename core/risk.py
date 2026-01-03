import logging

logger = logging.getLogger(__name__)

class Risk:
    def __init__(self, portfolio, config: dict = {}):
        self.portfolio = portfolio
        self.config = config
        self.max_positions = config.get("common", {}).get("max_positions", 10)
        self.max_loss_daily_pct = config.get("common", {}).get("max_loss_daily_pct", 5.0) # 5% default
        self.daily_start_equity = 0.0

    def set_daily_start_equity(self, equity: float):
        """Set the starting equity for the day (e.g., at 09:00)"""
        if equity > 0:
            self.daily_start_equity = equity
            logger.info(f"Daily Start Equity set to: {int(equity):,} KRW")

    def can_open_new_position(self, symbol: str, qty: int, price: float) -> bool:
        """Check if new position can be opened safely"""
        
        # 1. Daily Loss Check
        if not self.check_daily_loss():
            logger.warning("Risk Check Failed: Daily Loss Limit Reached")
            return False

        # 2. Available Slot Check
        is_existing = symbol in self.portfolio.positions
        if not is_existing and len(self.portfolio.positions) >= self.max_positions:
            logger.warning(f"Risk Check Failed: Max positions reached ({len(self.portfolio.positions)})")
            return False

        # 3. Financial Check (D+2 Deposit)
        # RiskManager checks "Buying Power" (Deposit D+2)
        # Broker might also check, but this is a pre-flight safety check.
        estimated_cost = qty * price * 1.0025
        
        buying_power = self.portfolio.buying_power

        if buying_power < estimated_cost:
            logger.warning(f"[매수 거부] {symbol} | 필요금액: {int(estimated_cost):,}원 | D+2예수금: {int(buying_power):,}원")
            return False

        return True

    def check_daily_loss(self) -> bool:
        """
        Check if daily loss limit is breached.
        Returns True if SAFE (loss within limit), False if BREACHED.
        """
        if self.daily_start_equity <= 0:
            # If not initialized, assume safe.
            return True

        current_equity = self.portfolio.total_asset
        if current_equity <= 0:
             return True

        pnl = current_equity - self.daily_start_equity
        pnl_pct = (pnl / self.daily_start_equity) * 100

        if pnl_pct <= -self.max_loss_daily_pct:
            logger.error(f"Daily Loss Limit Breached! PnL: {pnl_pct:.2f}% (Limit: -{self.max_loss_daily_pct}%)")
            return False

        return True
