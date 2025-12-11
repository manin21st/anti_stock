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
        return max(qty, 1) # Minimum 1 share

    def check_rate_limit(self, symbol: str, interval_seconds: int = 5) -> bool:
        """
        Check if we should proceed with analysis based on rate limits.
        Returns True if safe to proceed, False if we should skip.
        """
        # 1. Bypass checks in simulation mode
        if getattr(self.market_data, 'simulation_date', None):
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
