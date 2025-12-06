from .base import BaseStrategy
import pandas as pd

class PreviousHighBreakout(BaseStrategy):
    def on_bar(self, symbol, bar):
        daily = self.market_data.get_bars(symbol, timeframe="1d", lookback=2)
        if len(daily) < 2:
            return

        prev_high = daily.high.iloc[-2]
        prev_close = daily.close.iloc[-2]
        today_open = daily.open.iloc[-1]

        bars = self.market_data.get_bars(symbol, timeframe="1m", lookback=50)
        if len(bars) < 20:
            return

        position = self.portfolio.get_position(symbol)
        close = bars.close.iloc[-1]
        volume_now = bars.volume.iloc[-1]
        avg_vol20 = bars.volume.iloc[-20:].mean()

        # Entry
        if position is None:
            gap_up = (today_open - prev_close) / prev_close * 100 >= self.config.get("gap_pct", 2.0)
            breakout = (bars.high.iloc[-1] > prev_high) and (close > prev_high)
            vol_ok = volume_now > avg_vol20 * self.config.get("vol_k", 2.0)

            if gap_up and breakout and vol_ok:
                qty = self.calc_position_size(symbol)
                if self.risk.can_open_new_position(symbol, qty):
                    self.logger.info(f"BUY Signal (Breakout): {symbol} {qty}")
                    self.broker.buy_market(symbol, qty, tag=self.config["id"])
            return

        # Exit
        pnl_pct = (close - position.avg_price) / position.avg_price * 100

        # Stop Loss: Below Prev High or Fixed %
        if close < prev_high or pnl_pct <= -self.config["stop_loss_pct"]:
            self.logger.info(f"SELL Signal (Stop Loss/Breakout Fail): {symbol}")
            self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
            return

        # Take Profit
        if (not position.partial_taken) and pnl_pct >= self.config["take_profit1_pct"]:
            half = position.qty // 2
            if half > 0:
                self.logger.info(f"SELL Signal (Partial TP): {symbol} {half}")
                self.broker.sell_market(symbol, half, tag=self.config["id"])
                position.partial_taken = True
