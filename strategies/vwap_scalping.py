from .base import BaseStrategy
import pandas as pd

class VWAPScalping(BaseStrategy):
    def on_bar(self, symbol, bar):
        # Rate Limit Check
        if not self.check_rate_limit(symbol):
            return

        bars = self.market_data.get_bars(symbol, timeframe="1m", lookback=200)
        if len(bars) < 5:
            return

        stock_name = self.market_data.get_stock_name(symbol)

        typical_price = (bars.high + bars.low + bars.close) / 3
        cum_pv = (typical_price * bars.volume).cumsum()
        cum_vol = bars.volume.cumsum()
        vwap_series = cum_pv / cum_vol
        vwap_now = vwap_series.iloc[-1]

        close = bars.close.iloc[-1]
        prev_close = bars.close.iloc[-2]

        position = self.portfolio.get_position(symbol)

        # Entry
        # Entry Logic (Combined New + Add-on)
        # Cross up VWAP
        crossed_up = (prev_close < vwap_series.iloc[-2]) and (close > vwap_now)
        if crossed_up:
            qty = self.calculate_buy_quantity(symbol, close)
            if qty > 0 and self.risk.can_open_new_position(symbol, qty, close):
                self.logger.info(f"[{symbol} {stock_name}] 매수 진입 (VWAP 상향 돌파) | 수량: {qty}주 | 현재가: {int(close):,}원 > VWAP: {int(vwap_now):,}원")
                self.broker.buy_market(symbol, qty, tag=self.config["id"])
        
        if position is None:
            return

        # Exit
        pnl_ratio = (close - position.avg_price) / position.avg_price
        
        # Stop Loss (Below VWAP) or Take Profit (Config: 0.015)
        if close < vwap_now or pnl_ratio >= self.config["take_profit_pct"]:
            reason = "VWAP 이탈" if close < vwap_now else "목표 수익 달성"
            self.logger.info(f"[{symbol} {stock_name}] 매도 실행 ({reason}) | 수익률: {pnl_ratio*100:.2f}% | 현재가: {int(close):,}원")
            self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
