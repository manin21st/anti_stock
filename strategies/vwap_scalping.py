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

        typical_price = (bars.high + bars.low + bars.close) / 3
        cum_pv = (typical_price * bars.volume).cumsum()
        cum_vol = bars.volume.cumsum()
        vwap_series = cum_pv / cum_vol
        vwap_now = vwap_series.iloc[-1]

        close = bars.close.iloc[-1]
        prev_close = bars.close.iloc[-2]

        position = self.portfolio.get_position(symbol)

        # Entry
        if position is None:
            # Cross up VWAP
            crossed_up = (prev_close < vwap_series.iloc[-2]) and (close > vwap_now)
            if crossed_up:
                qty = self.calc_position_size(symbol, risk_pct=self.config.get("risk_pct", 0.01))
                if self.risk.can_open_new_position(symbol, qty):
                    self.logger.info(f"[{symbol}] 매수 진입 (VWAP 상향 돌파) | 수량: {qty}주 | 현재가: {int(close):,}원 > VWAP: {int(vwap_now):,}원")
                    self.broker.buy_market(symbol, qty, tag=self.config["id"])
            return

        # Exit
        pnl_pct = (close - position.avg_price) / position.avg_price * 100
        
        # Stop Loss (Below VWAP) or Take Profit
        if close < vwap_now or pnl_pct >= self.config["take_profit_pct"]:
            reason = "VWAP 이탈" if close < vwap_now else "목표 수익 달성"
            self.logger.info(f"[{symbol}] 매도 실행 ({reason}) | 수익률: {pnl_pct:.2f}% | 현재가: {int(close):,}원")
            self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
