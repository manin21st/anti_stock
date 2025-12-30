from .base import BaseStrategy
import pandas as pd

class VWAPScalping(BaseStrategy):
    # 필수 설정
    REQUIRED_KEYS = ['take_profit_pct']

    def execute(self, symbol, bar):
        # Entry Logic
        bars = self.market_data.get_bars(symbol, timeframe="1m", lookback=200)
        if len(bars) < 5: return

        stock_name = self.market_data.get_stock_name(symbol)
        
        typical_price = (bars.high + bars.low + bars.close) / 3
        cum_pv = (typical_price * bars.volume).cumsum()
        cum_vol = bars.volume.cumsum()
        vwap_series = cum_pv / cum_vol
        vwap_now = vwap_series.iloc[-1]

        close = bars.close.iloc[-1]
        prev_close = bars.close.iloc[-2]
        
        # Cross up VWAP
        crossed_up = (prev_close < vwap_series.iloc[-2]) and (close > vwap_now)
        if crossed_up:
            qty = self.calculate_buy_quantity(symbol, close)
            if qty > 0 and self.risk.can_open_new_position(symbol, qty, close):
                self.logger.info(f"[{symbol} {stock_name}] 매수 진입 (VWAP 상향 돌파) | 수량: {qty}주 | 현재가: {int(close):,}원 > VWAP: {int(vwap_now):,}원")
                self.broker.buy_market(symbol, qty, tag=self.config["id"])

    def manage_position(self, position, symbol, stock_name, current_price):
        # 1. Base Strategy Logic (Stop Loss / Trail Stop / Partial TP)
        # Note: vwap used 'take_profit_pct' which sounds like Full TP.
        # But BaseStrategy only has partial. If user wants full TP, we implement here?
        # Or map 'take_profit_pct' to something else? 
        # Let's assume we implement Full TP here if set.
        
        if super().manage_position(position, symbol, stock_name, current_price):
            return True

        # 2. Strategy Specific: VWAP Break Exit OR Full TP
        bars = self.market_data.get_bars(symbol, timeframe="1m", lookback=200)
        if len(bars) < 5: return False
        
        typical_price = (bars.high + bars.low + bars.close) / 3
        cum_pv = (typical_price * bars.volume).cumsum()
        cum_vol = bars.volume.cumsum()
        vwap_now = (cum_pv / cum_vol).iloc[-1]
        
        pnl_ratio = (current_price - position.avg_price) / position.avg_price
        
        # Full TP Check explicitly
        tp_pct = self.config.get("take_profit_pct")
        if tp_pct and pnl_ratio >= tp_pct:
             self.logger.info(f"[{symbol} {stock_name}] 매도 실행 (목표 수익 달성) | 수익률: {pnl_ratio*100:.2f}%")
             self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
             return True

        # VWAP Break Check
        if current_price < vwap_now:
             self.logger.info(f"[{symbol} {stock_name}] 매도 실행 (VWAP 이탈) | 수익률: {pnl_ratio*100:.2f}% | 현재가: {int(current_price):,}원 < VWAP")
             self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
             return True

        return False
