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
                pnl_pct = 0.0
            else:
                pnl_pct = (current_price - avg_price) / avg_price * 100
            
            # High Watermark Update (Fix 4: Persistence)
            if current_price > position.max_price:
                position.max_price = current_price
                self.portfolio.save_state() # Save new high

            # 1. Stop Loss (Safety First)
            if pnl_pct <= -self.config["stop_loss_pct"]:
                self.logger.info(f"[손절매] {symbol} {stock_name} | 현재가: {int(current_price):,} | 수익률: {pnl_pct:.2f}% (제한: -{self.config['stop_loss_pct']}%)")
                self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
                return

            # 2. Take Profit (Partial)
            if (not position.partial_taken) and pnl_pct >= self.config["take_profit1_pct"]:
                half = position.qty // 2
                if half > 0:
                    self.logger.info(f"[익절] {symbol} {stock_name} | 현재가: {int(current_price):,} | 수익률: {pnl_pct:.2f}% (1차 목표달성)")
                    self.broker.sell_market(symbol, half, tag=self.config["id"])
                    position.partial_taken = True
                    self.portfolio.save_state()
            
            # 3. Trailing Stop (Fix 4: Activation Logic)
            trail_activation_pct = self.config.get("trail_activation_pct", 3.0)
            activation_price = avg_price * (1 + trail_activation_pct / 100.0)
            
            if position.max_price >= activation_price:
                drawdown = (current_price - position.max_price) / position.max_price * 100
                if drawdown <= -self.config["trail_stop_pct"]:
                     self.logger.info(f"[트레일링 스탑] {symbol} {stock_name} | 현재가: {int(current_price):,} | 고점 대비 하락: {drawdown:.2f}% (고점: {int(position.max_price):,})")
                     self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
                     return

            # 사용자 알림 (수익률 변동 시 로그) - Optional logic preserved but formatted
            if abs(pnl_pct) > 1.0 and int(time.time()) % 60 == 0: # Reduce log spam
                 self.logger.debug(f"[보유 중] {symbol} {stock_name} | 현재가: {int(current_price):,} | 수익률: {pnl_pct:.2f}%")

            return # Exit logic done

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

        # Detailed Monitoring
        ma5_now = bars.close.iloc[-5:].mean()
        ma20_now = bars.close.iloc[-20:].mean()
        # ma5_prev = bars.close.iloc[-6:-1].mean()
        # ma20_prev = bars.close.iloc[-21:-1].mean()
        
        volume_now = bars.volume.iloc[-1]
        avg_vol20 = bars.volume.iloc[-20:].mean()
        
        vol_k = self.config.get("vol_k", 1.5)
        
        # Periodic Info Log (Fix 5: Format)
        if avg_vol20 > 0:
             vol_ratio = (volume_now / avg_vol20)
             ma_stat = "(대기)" if ma5_now <= ma20_now else "(충족)"
             vol_stat = "(부족)" if vol_ratio < vol_k else "(충족)"
             
             self.log_monitor(f"[감시 중] {symbol} {stock_name} | 현재가: {int(bars.close.iloc[-1]):,} | 이평돌파: {ma_stat} | 거래량: {vol_ratio:.1f}배 {vol_stat}")

        # Golden Cross Logic
        ma5_prev = bars.close.iloc[-6:-1].mean()
        ma20_prev = bars.close.iloc[-21:-1].mean()
        
        golden_cross = (ma5_prev <= ma20_prev) and (ma5_now > ma20_now)
        vol_ok = volume_now > avg_vol20 * vol_k
        
        if golden_cross and vol_ok:
            qty = self.calc_position_size(symbol)
            # Fix 1: Pass current_price to check buying power
            if self.risk.can_open_new_position(symbol, qty, current_price):
                self.logger.info(f"[매수 진입] {symbol} {stock_name} | 수량: {qty}주 | 현재가: {int(current_price):,} | 골든크로스 + 거래량 충족")
                self.broker.buy_market(symbol, qty, tag=self.config["id"])
