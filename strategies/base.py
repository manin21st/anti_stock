from abc import ABC, abstractmethod
import logging

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
