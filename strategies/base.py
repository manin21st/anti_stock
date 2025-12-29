from abc import ABC, abstractmethod
import logging
import time

logger = logging.getLogger(__name__)

class BaseStrategy(ABC):
    def __init__(self, config, broker, risk_manager, portfolio, market_data):
        self.config = config
        self.broker = broker
        self.risk = risk_manager
        self.portfolio = portfolio
        self.market_data = market_data
        self.logger = logging.getLogger(self.__class__.__name__)
        self.enabled = config.get("enabled", True) # Default to enabled

    def update_config(self, new_config):
        """Update configuration dynamically"""
        self.config.update(new_config)
        self.enabled = self.config.get("enabled", True)
        self.logger.info(f"Config updated. Enabled: {self.enabled}")

    @abstractmethod
    def on_bar(self, symbol, bar):
        """Called when a new bar (candle) is available"""
        pass

    def on_tick(self, symbol, tick):
        """Called on every tick"""
        pass

    def on_order_update(self, order):
        """Called when order status changes"""
        pass

    def calculate_buy_quantity(self, symbol: str, current_price: float) -> int:
        """
        Calculate buy quantity based on Risk Management & Target Weight logic.
        Centralizes logic for both New Entry and Add-on (Split Buying).
        """
        if current_price <= 0:
            return 0

        # 1. Basic Risk Management (Step Size)
        # Calculates strictly based on risk_pct (e.g. 3% of total equity)
        risk_step_qty = self.calc_position_size(symbol, risk_pct=self.config.get("risk_pct"))
        
        # 2. Target Weight Logic
        # Check if we have a target weight limit (default usually 0.1 / 10%)
        # If target_weight is not set or 0, we rely solely on risk_pct (Unlimited Add-on? No, usually safer to limit)
        target_weight = self.config.get("target_weight", 0.0) 
        
        if target_weight <= 0:
            # If no target weight specified, just return the risk based step quantity
            # But usually strategies should have a max allocation. Check max_allocation?
            # For now, return step qty.
            return risk_step_qty

        # Calculate Deficit
        total_equity = self.portfolio.get_account_value()
        target_val = total_equity * target_weight
        
        current_qty = 0
        position = self.portfolio.get_position(symbol)
        if position:
            current_qty = position.qty
            
        current_val = current_qty * current_price
        deficit_val = target_val - current_val
        
        if deficit_val <= 0:
            # Already met or exceeded target
            return 0
            
        # Convert deficit value to quantity
        deficit_qty = int(deficit_val // current_price)
        
        # 3. Final Quantity Determination
        # We want to buy 'risk_step', but NOT exceed 'deficit'.
        # And obviously trigger logic only if meaningful amount (e.g. > 0)
        
        buy_qty = min(risk_step_qty, deficit_qty)
        
        # Logging Context
        if buy_qty > 0:
            # Only log if we are actually planning to buy?
            # Caller will log "Buy Order Sent", but here we can log the decision context if needed.
            # But keeping logs clean, maybe return tuple? (qty, reason).
            # For now, let caller handle main logs, but debug here is fine.
            
            # Additional User Requirement:
            # "Add-on Monitor" log was confusing. 
            # We will log concise info here if it's an Add-on scenario
            if current_qty > 0:
                self.logger.info(f"[비중 조절] {symbol} | 목표부족: {deficit_val:,.0f}원({deficit_qty}주) | 매수진행: {buy_qty}주")
        
        return buy_qty

    def calc_position_size(self, symbol, risk_pct=None):
        """Calculate position size based on risk percentage"""
        account_value = self.portfolio.get_account_value()
        if risk_pct is None:
            risk_pct = self.config.get("risk_pct", 0.03) # Default 3%

        alloc = account_value * risk_pct
        price = self.market_data.get_last_price(symbol)
        
        if price <= 0:
            return 0
            
        qty = int(alloc // price)
        return max(qty, 0) # Allow 0 if price is too high or alloc too small

    def check_rate_limit(self, symbol: str, interval_seconds: int = 5) -> bool:
        """
        Check if we should proceed with analysis based on rate limits.
        Returns True if safe to proceed, False if we should skip.
        """
        # 1. Bypass checks in simulation mode
        if self.config.get("is_simulation", False):
            return True
            
        # 2. Check real-time rate limit
        now = time.time()
        if not hasattr(self, "_last_analysis_time"):
            self._last_analysis_time = {}
            
        if now - self._last_analysis_time.get(symbol, 0) < interval_seconds:
            return False
            
        self._last_analysis_time[symbol] = now
        
        # 3. Add safety sleep for real trading to prevent API burst
        # time.sleep(0.5) # REMOVED: Handled by core.kis_api RateLimiter
        return True

    def can_enter_market(self, current_time_str: str = None) -> bool:
        """
        Check if we can enter the market based on 'entry_start_time'.
        Commonly used to avoid early morning volatility (e.g. before 09:10).
        """
        if not current_time_str:
            return True
            
        start_time_raw = self.config.get("entry_start_time", "090000")
        
        # Defensive Type Conversion & Padding
        start_time = str(start_time_raw).zfill(6)

        if current_time_str < start_time:
            # Silent reject or debug log?
            return False
            
        return True
