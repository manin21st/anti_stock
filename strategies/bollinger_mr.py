from .base import BaseStrategy
import pandas as pd

class BollingerMeanReversion(BaseStrategy):
    def on_bar(self, symbol, bar):
        bars = self.market_data.get_bars(symbol, timeframe=self.config["timeframe"], lookback=60)
        if len(bars) < 20:
            return

        ma20 = bars.close.iloc[-20:].mean()
        std20 = bars.close.iloc[-20:].std()
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        close = bars.close.iloc[-1]

        position = self.portfolio.get_position(symbol)

        # Entry
        if position is None:
            # Price below lower band by 1%
            if close < lower * 0.99:
                qty = self.calc_position_size(symbol, risk_pct=self.config.get("risk_pct", 0.03))
                if self.risk.can_open_new_position(symbol, qty):
                    self.logger.info(f"BUY Signal (Bollinger Lower): {symbol} {qty}")
                    self.broker.buy_market(symbol, qty, tag=self.config["id"])
            return

        # Exit
        pnl_pct = (close - position.avg_price) / position.avg_price * 100

        # Stop Loss
        if pnl_pct <= -self.config["stop_loss_pct"]:
            self.logger.info(f"SELL Signal (Stop Loss): {symbol} {pnl_pct:.2f}%")
            self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
            return

        # Mean Reversion Target (MA20)
        if close >= ma20:
            self.logger.info(f"SELL Signal (Mean Reversion): {symbol} Reached MA20")
            self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
