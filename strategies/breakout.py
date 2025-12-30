from .base import BaseStrategy
import pandas as pd

class PreviousHighBreakout(BaseStrategy):
    # 필수 설정
    REQUIRED_KEYS = ['gap_pct', 'stop_loss_pct', 'take_profit1_pct', 'vol_k']

    def execute(self, symbol, bar):
        # Entry Logic Only
        daily = self.market_data.get_bars(symbol, timeframe="1d", lookback=2)
        if len(daily) < 2: return

        prev_high = daily.high.iloc[-2]
        prev_close = daily.close.iloc[-2]
        today_open = daily.open.iloc[-1]

        bars = self.market_data.get_bars(symbol, timeframe="1m", lookback=50)
        if len(bars) < 20: return

        stock_name = self.market_data.get_stock_name(symbol)
        close = bars.close.iloc[-1]
        volume_now = bars.volume.iloc[-1]
        avg_vol20 = bars.volume.iloc[-20:].mean()

        # Entry Conditions
        gap_up = (today_open - prev_close) / prev_close >= self.config.get("gap_pct", 0.02)
        breakout = (bars.high.iloc[-1] > prev_high) and (close > prev_high)
        vol_ok = volume_now > avg_vol20 * self.config.get("vol_k", 2.0)

        if gap_up and breakout and vol_ok:
            qty = self.calculate_buy_quantity(symbol, close)
            if qty > 0 and self.risk.can_open_new_position(symbol, qty, close):
                self.logger.info(f"[{symbol} {stock_name}] 매수 진입 (전고점 돌파) | 수량: {qty}주 | 현재가: {int(close):,}원 > 전고점: {int(prev_high):,}원")
                self.broker.buy_market(symbol, qty, tag=self.config["id"])

    def manage_position(self, position, symbol, stock_name, current_price):
        # 1. Base Strategy Logic (Stop Loss / Trail Stop / Partial TP)
        if super().manage_position(position, symbol, stock_name, current_price):
            return True

        # 2. Strategy Specific Exit: Fall below Previous High
        # We need prev_high data.
        daily = self.market_data.get_bars(symbol, timeframe="1d", lookback=2)
        if len(daily) < 2: return False
        prev_high = daily.high.iloc[-2]

        if current_price < prev_high:
            pnl_ratio = (current_price - position.avg_price) / position.avg_price
            self.logger.info(f"[{symbol} {stock_name}] 매도 실행 (돌파 실패-전고점 하회) | 수익률: {pnl_ratio*100:.2f}%")
            self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
            return True
            
        return False
