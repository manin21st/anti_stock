from .base import BaseStrategy
import pandas as pd
import time

class MovingAverageTrendStrategy(BaseStrategy):
    def log_monitor(self, msg):
        if not getattr(self.market_data, 'simulation_date', None):
             self.logger.info(msg)
        else:
             self.logger.debug(msg)

    def on_bar(self, symbol, bar):
        # bar: Series or dict with OHLCV
        
        # 1. Check Position & Exit Logic FIRST (Prioritize Selling)
        position = self.portfolio.get_position(symbol)
        current_price = bar.get('close', 0.0)
        stock_name = self.market_data.get_stock_name(symbol)
        
        if position is not None:
            # --- Exit Logic (Real-time) ---
            if current_price <= 0:
                return

            avg_price = position.avg_price
            if avg_price <= 0:
                pnl_ratio = 0.0
            else:
                pnl_ratio = (current_price - avg_price) / avg_price
            
            # High Watermark Update (Fix 4: Persistence)
            if current_price > position.max_price:
                position.max_price = current_price
                self.portfolio.save_state() # Save new high

            # 1. Stop Loss (Safety First)
            # Config: 0.02 (2%)
            if pnl_ratio <= -self.config["stop_loss_pct"]:
                self.logger.info(f"[손절매] {symbol} {stock_name} | 현재가: {int(current_price):,} | 수익률: {pnl_ratio*100:.2f}% (제한: -{self.config['stop_loss_pct']*100}%)")
                self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
                return

            # 2. Take Profit (Partial)
            # Config: 0.03 (3%)
            if (not position.partial_taken) and pnl_ratio >= self.config["take_profit1_pct"]:
                half = position.qty // 2
                if half > 0:
                    self.logger.info(f"[익절] {symbol} {stock_name} | 현재가: {int(current_price):,} | 수익률: {pnl_ratio*100:.2f}% (1차 목표달성)")
                    self.broker.sell_market(symbol, half, tag=self.config["id"])
                    position.partial_taken = True
                    self.portfolio.save_state()
            
            # 3. Trailing Stop (Fix 4: Activation Logic)
            # Config: 0.03 (3%)
            trail_activation_ratio = self.config.get("trail_activation_pct", 0.03)
            # activation_price = avg_price * (1 + 0.03)
            activation_price = avg_price * (1 + trail_activation_ratio)
            
            if position.max_price >= activation_price:
                # Drawdown is also ratio: (9800 - 10000) / 10000 = -0.02
                drawdown = (current_price - position.max_price) / position.max_price
                
                # Config: 0.015 (1.5%)
                if drawdown <= -self.config["trail_stop_pct"]:
                     # Safety check: Ensure we are still in profit (or at least breakeven)
                     if current_price < avg_price:
                         # Fell below avg_price, allow Stop Loss to handle it or hold
                         return

                     self.logger.info(f"[트레일링 스탑] {symbol} {stock_name} | 현재가: {int(current_price):,} | 매수가: {int(avg_price):,} | 고점: {int(position.max_price):,} ({drawdown*100:.2f}%) | 발동가: {int(activation_price):,}")
                     self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
                     return

            # 4. Add-on Logic removed (Refactored to check only on signal)
            pass

        # 2. Entry Logic (Timeframe Throttled - Fix 3)
        # Check rate limit (60s default for entry scan to match user request)
        if not self.check_rate_limit(symbol, interval_seconds=60):
            return

        bars = self.market_data.get_bars(symbol, timeframe=self.config["timeframe"])
        daily = self.market_data.get_bars(symbol, timeframe="1d")
        
        # stock_name already fetched
        
        if daily is None or len(daily) < 20:
             return # Silent skip

        # Daily Trend Filter (Fix 6: Better exclusion reason)
        ma20_daily_now = daily.close.iloc[-20:].mean()
        ma20_daily_prev = daily.close.iloc[-21:-1].mean()
        
        current_daily_close = daily.close.iloc[-1]
        
        if current_daily_close < ma20_daily_now:
             self.log_monitor(f"[감시 제외] {symbol} {stock_name} | 사유: 하락 추세 (현재 {int(current_daily_close):,} < MA20 {int(ma20_daily_now):,})")
             return
        
        if ma20_daily_now < ma20_daily_prev:
             self.log_monitor(f"[감시 제외] {symbol} {stock_name} | 사유: 20이평 하락 추세 (MA20 {int(ma20_daily_now):,} < 전일 {int(ma20_daily_prev):,})")
             return

        # Trend is UP -> Check Intraday Data
        if bars is None or len(bars) < 20:
             return

        ma_short = self.config.get("ma_short", 5)
        ma_long = self.config.get("ma_long", 20)

        # Detailed Monitoring
        ma_short_now = bars.close.iloc[-ma_short:].mean()
        ma_long_now = bars.close.iloc[-ma_long:].mean()
        
        volume_now = bars.volume.iloc[-1]
        avg_vol20 = bars.volume.iloc[-20:].mean()
        
        whipsaw_threshold = self.config.get("whipsaw_threshold", 0.0)
        cross_lookback = self.config.get("cross_lookback", 1)
        vol_k = self.config.get("vol_k", 1.5)

        # Periodic Info Log (Fix 5: Format)
        if avg_vol20 > 0:
             vol_ratio = (volume_now / avg_vol20)
             ma_stat = "(대기)" if ma_short_now <= ma_long_now else "(충족)"
             vol_stat = "(부족)" if vol_ratio < vol_k else "(충족)"
             
             self.log_monitor(f"[감시 중] {symbol} {stock_name} | 현재가: {int(bars.close.iloc[-1]):,} | 이평돌파: {ma_stat} | 거래량: {vol_ratio:.1f}배 {vol_stat}")

        # --- Enhanced Entry Logic (Persistent Cross & Whipsaw Filter) ---
        
        # 1. Check for Golden Cross within 'cross_lookback' bars
        # recent_cross_occurred = False
        # We need at least lookback + 1 range to detect cross
        
        recent_cross_occurred = False
        
        # Look back 'cross_lookback' bars (including current)
        # For each bar i from -lookback to -1:
        # Check if MA5 crosses MA20 at that bar
        # Note: We need historical MAs. We can calculate them on the fly or iterate.
        # Efficient way: Iterate locally
        
        lookback_limit = min(cross_lookback, len(bars) - ma_long - 1)
        if lookback_limit < 1: lookback_limit = 1
        
        # Check cross in recent N bars
        for i in range(lookback_limit):
            # 0 is current (-1), 1 is prev (-2), etc.
            idx_curr = -1 - i
            idx_prev = -2 - i
            
            # Calculate simple MA at that point (approximation or slicing)
            # Slicing is safer
            slice_end = idx_curr + 1 if idx_curr + 1 < 0 else None
            
            # MA Short
            s_series = bars.close.iloc[:slice_end] if slice_end else bars.close
            
            if len(s_series) < ma_long + 1: continue
            
            m_s_now = s_series.iloc[-ma_short:].mean()
            m_l_now = s_series.iloc[-ma_long:].mean()
            
            m_s_prev = s_series.iloc[-(ma_short+1):-1].mean()
            m_l_prev = s_series.iloc[-(ma_long+1):-1].mean()
            
            if m_s_prev <= m_l_prev and m_s_now > m_l_now:
                recent_cross_occurred = True
                break
        
        # 2. Current Status Check (Must still be in uptrend)
        in_uptrend = ma_short_now > ma_long_now
        
        # 3. Whipsaw Filter (Strength Check)
        # Price must be > MA Long * (1 + threshold)
        strong_breakout = bars.close.iloc[-1] >= ma_long_now * (1 + whipsaw_threshold)
        
        # 4. Volume Check
        vol_ok = volume_now > avg_vol20 * vol_k
        
        if recent_cross_occurred and in_uptrend and vol_ok:
            if not strong_breakout:
                 self.logger.info(f"[휩쏘 필터] {symbol} {stock_name} | 이격도 부족 (현재 {((bars.close.iloc[-1]/ma_long_now)-1)*100:.2f}% < {whipsaw_threshold*100}%) | 진입 보류")
                 return

            # 1. Calculate Buy Quantity (Risk + Target Weight)
            buy_qty = self.calculate_buy_quantity(symbol, current_price)
            
            if buy_qty > 0:
                # 2. Risk Check & Execution
                if self.risk.can_open_new_position(symbol, buy_qty, current_price):
                    self.logger.info(f"[매수 진입] {symbol} {stock_name} | 골든크로스(확정) | 수량: {buy_qty}주")
                    self.broker.buy_market(symbol, buy_qty, tag=self.config["id"])
            else:
                self.logger.warning(f"[매수 실패] {symbol} {stock_name} | 수량 계산 0 (진입 불가) | 현재가: {int(current_price):,}원 | 원인: 자금/비중 부족 혹은 주가 과도")
