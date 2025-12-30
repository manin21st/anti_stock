from .base import BaseStrategy
import pandas as pd

class BollingerMeanReversion(BaseStrategy):
    # 필수 설정
    REQUIRED_KEYS = ['timeframe', 'stop_loss_pct']

    def execute(self, symbol, bar):
        # Preprocessing passed. Only Entry Logic here.
        # Fallback if timeframe is not day, code above was getting bars manually
        bars = self.market_data.get_bars(symbol, timeframe=self.config["timeframe"], lookback=60)
        if bars is None or len(bars) < 20: return

        stock_name = self.market_data.get_stock_name(symbol)
        ma20 = bars.close.iloc[-20:].mean()
        std20 = bars.close.iloc[-20:].std()
        lower = ma20 - 2 * std20
        close = bars.close.iloc[-1]

        # Entry Logic
        # Price below lower band by 1%
        if close < lower * 0.99:
            qty = self.calculate_buy_quantity(symbol, close)
            # Use risk check
            if qty > 0 and self.risk.can_open_new_position(symbol, qty, close):
                 self.logger.info(f"[{symbol} {stock_name}] 매수 진입 (볼린저 하단 반등) | 수량: {qty}주 | 현재가: {int(close):,}원 < 하단: {int(lower):,}원")
                 self.broker.buy_market(symbol, qty, tag=self.config["id"])

    def manage_position(self, position, symbol, stock_name, current_price):
        # 1. Base Strategy Logic (Stop Loss / Trail Stop / Partial TP)
        if super().manage_position(position, symbol, stock_name, current_price):
            return True

        # 2. Strategy Specific Exit: Mean Reversion Target (MA20)
        bars = self.market_data.get_bars(symbol, timeframe=self.config["timeframe"], lookback=30)
        if bars is None or len(bars) < 20: return False
        
        ma20 = bars.close.iloc[-20:].mean()
        pnl_ratio = (current_price - position.avg_price) / position.avg_price
        
        if current_price >= ma20:
            self.logger.info(f"[{symbol} {stock_name}] 수익 실현 (평균회귀 도달) | 현재가: {int(current_price):,}원 >= MA20: {int(ma20):,}원 | 수익률: {pnl_ratio*100:.2f}%")
            self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
            return True
            
        return False
