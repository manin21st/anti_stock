from .base import BaseStrategy
import pandas as pd
import time

class MovingAverageTrendStrategy(BaseStrategy):
    def on_bar(self, symbol, bar):
        # bar: Series or dict with OHLCV
        
        # 1. Check Position & Exit Logic FIRST (Prioritize Selling)
        position = self.portfolio.get_position(symbol)
        
        if position is not None:
            # --- Exit Logic (No History Needed) ---
            current_price = bar.get('close', 0.0)
            if current_price <= 0:
                return

            avg_price = position.avg_price
            if avg_price <= 0:
                pnl_pct = 0.0
            else:
                pnl_pct = (current_price - avg_price) / avg_price * 100
            
            high_price = bar.get('high', current_price)
            max_price = max(position.max_price, high_price)
            if max_price <= 0:
                max_price = current_price
            
            self.logger.info(f"DEBUG: Checking Exit {symbol} | PnL: {pnl_pct:.2f}% | Price: {current_price} | Avg: {avg_price} | Max: {max_price}")

            # Breakeven Stop (Safety)
            # If partial profit taken, do not let remaining position turn into loss
            if position.partial_taken and current_price < avg_price:
                 self.logger.info(f"SELL Signal (Breakeven Stop): {symbol} {current_price} < {avg_price}")
                 self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
                 return

            # Stop Loss (Only if not partial taken, or if price drops significantly below avg despite breakeven logic)
            if pnl_pct <= -self.config["stop_loss_pct"]:
                self.logger.info(f"SELL Signal (Stop Loss): {symbol} {pnl_pct:.2f}%")
                self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
                return

            # Take Profit (Partial)
            if (not position.partial_taken) and pnl_pct >= self.config["take_profit1_pct"]:
                half = position.qty // 2
                if half > 0:
                    self.logger.info(f"SELL Signal (Partial TP): {symbol} {half} (PnL {pnl_pct:.2f}%)")
                    self.broker.sell_market(symbol, half, tag=self.config["id"])
                    position.partial_taken = True
                    self.portfolio.save_state() # Persist state

            # Trailing Stop
            if max_price > 0:
                drawdown_from_high = (current_price - max_price) / max_price * 100
                if drawdown_from_high <= -self.config["trail_stop_pct"]:
                    self.logger.info(f"SELL Signal (Trailing Stop): {symbol} {drawdown_from_high:.2f}% (Max: {max_price})")
                    self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
            
            return # Exit logic done

        # 2. Entry Logic (Needs History)
        # Rate Limit Check
        if not self.check_rate_limit(symbol):
            return

        # Optimization handled by check_rate_limit
        # Only fetch history if we don't have a position and might want to enter
        bars = self.market_data.get_bars(symbol, timeframe=self.config["timeframe"])
        daily = self.market_data.get_bars(symbol, timeframe="1d")

        # Debug Data Status
        self.logger.info(f"DEBUG: {symbol} Date={bar.get('date')} Bars={len(bars)} Daily={len(daily)}")

        if bars is None or daily is None or len(bars) < 20 or len(daily) < 20:
             self.logger.info(f"DEBUG: Insufficient data for {symbol}. Bars: {len(bars)}, Daily: {len(daily)}")
             return
        
        # self.last_analysis_time[symbol] = time.time()  # REMOVED: Redundant and causes AttributeError

        # Daily Trend Filter
        ma20_daily_now = daily.close.iloc[-20:].mean()
        ma20_daily_prev = daily.close.iloc[-21:-1].mean()
        
        # Check if MA20 is rising and Close > MA20
        trend_up = (ma20_daily_now > ma20_daily_prev) and (daily.close.iloc[-1] > ma20_daily_now)
        
        self.logger.info(f"DEBUG: Trend Up? {trend_up} (MA20_Now: {ma20_daily_now:.2f}, Close: {daily.close.iloc[-1]})")

        if not trend_up: return

        # Intraday MA Calculation
        ma5_now = bars.close.iloc[-5:].mean()
        ma5_prev = bars.close.iloc[-6:-1].mean()
        ma20_now = bars.close.iloc[-20:].mean()
        ma20_prev = bars.close.iloc[-21:-1].mean()

        volume_now = bars.volume.iloc[-1]
        avg_vol20 = bars.volume.iloc[-20:].mean()

        golden_cross = (ma5_prev <= ma20_prev) and (ma5_now > ma20_now)
        vol_ok = volume_now > avg_vol20 * self.config.get("vol_k", 1.5)
        
        self.logger.info(f"DEBUG: GC? {golden_cross} Vol_OK? {vol_ok} (Vol: {volume_now} vs Avg*K: {avg_vol20 * self.config.get('vol_k', 1.5):.2f})")

        if golden_cross and vol_ok:
            qty = self.calc_position_size(symbol)
            if self.risk.can_open_new_position(symbol, qty):
                self.logger.info(f"BUY Signal (Golden Cross): {symbol} {qty}")
                self.broker.buy_market(symbol, qty, tag=self.config["id"])
