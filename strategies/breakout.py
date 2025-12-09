from .base import BaseStrategy
import pandas as pd

class PreviousHighBreakout(BaseStrategy):
    def on_bar(self, symbol, bar):
        # Rate Limit Check
        if not self.check_rate_limit(symbol):
            return

        daily = self.market_data.get_bars(symbol, timeframe="1d", lookback=2)
        if len(daily) < 2:
            return

        prev_high = daily.high.iloc[-2]
        prev_close = daily.close.iloc[-2]
        today_open = daily.open.iloc[-1]

        bars = self.market_data.get_bars(symbol, timeframe="1m", lookback=50)
        if len(bars) < 20:
            return

        stock_name = self.market_data.get_stock_name(symbol)

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
                    self.logger.info(f"[{symbol} {stock_name}] 매수 진입 (전고점 돌파) | 수량: {qty}주 | 현재가: {int(close):,}원 > 전고점: {int(prev_high):,}원")
                    self.broker.buy_market(symbol, qty, tag=self.config["id"])
            return

        # Exit
        pnl_pct = (close - position.avg_price) / position.avg_price * 100

        # Stop Loss: Below Prev High or Fixed %
        if close < prev_high or pnl_pct <= -self.config["stop_loss_pct"]:
            reason = "돌파 실패(전고점 하회)" if close < prev_high else "손절매 조건 도달"
            self.logger.info(f"[{symbol} {stock_name}] 매도 실행 ({reason}) | 수익률: {pnl_pct:.2f}%")
            self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
            return

        # Take Profit
        if (not position.partial_taken) and pnl_pct >= self.config["take_profit1_pct"]:
            half = position.qty // 2
            if half > 0:
                self.logger.info(f"[{symbol} {stock_name}] 1차 수익 실현 (Partial TP) | 수익률: {pnl_pct:.2f}% | 매도수량: {half}주")
                self.broker.sell_market(symbol, half, tag=self.config["id"])
                position.partial_taken = True
