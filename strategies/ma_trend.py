from .base import BaseStrategy
import pandas as pd
import time

class MovingAverageTrendStrategy(BaseStrategy):
    def log_monitor(self, msg):
        self.logger.info(msg)

    def on_bar(self, symbol, bar):
        # 1. Check Position & Exit Logic FIRST (Prioritize Selling)
        position = self.portfolio.get_position(symbol)
        current_price = bar.get('close', 0.0)
        stock_name = self.market_data.get_stock_name(symbol)

        if position is not None:
            if current_price <= 0: return

            avg_price = position.avg_price
            pnl_ratio = (current_price - avg_price) / avg_price if avg_price > 0 else 0.0

            # High Watermark Update
            if current_price > position.max_price:
                position.max_price = current_price
                self.portfolio.save_state()

            # 1. Stop Loss
            if pnl_ratio <= -self.config["stop_loss_pct"]:
                self.logger.info(f"[손절매] {symbol} {stock_name} | 현재가: {int(current_price):,} | 수익률: {pnl_ratio*100:.2f}%")
                self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
                return

            # 2. Take Profit (Partial)
            if (not position.partial_taken) and pnl_ratio >= self.config["take_profit1_pct"]:
                half = position.qty // 2
                if half > 0:
                    self.logger.info(f"[익절] {symbol} {stock_name} | 현재가: {int(current_price):,} | 수익률: {pnl_ratio*100:.2f}% (1차)")
                    self.broker.sell_market(symbol, half, tag=self.config["id"])
                    position.partial_taken = True
                    self.portfolio.save_state()

            # 3. Trailing Stop
            trail_activation_ratio = self.config.get("trail_activation_pct", 0.03)
            activation_price = avg_price * (1 + trail_activation_ratio)

            if position.max_price >= activation_price:
                drawdown = (current_price - position.max_price) / position.max_price

                if drawdown <= -self.config["trail_stop_pct"]:
                     if current_price < avg_price: return
                     self.logger.info(f"[트레일링 스탑] {symbol} {stock_name} | 현재가: {int(current_price):,} | 고점: {int(position.max_price):,} | 발동가: {int(activation_price):,}")
                     self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
                     return
            pass

        # 2. Entry Logic
        if not self.check_rate_limit(symbol, interval_seconds=60):
            return

        current_time = bar.get('time', '')
        if not self.can_enter_market(current_time):
             return

        # Optimization: Get daily bars first (usually cached) before intraday
        daily = self.market_data.get_bars(symbol, timeframe="1d")
        if daily is None or len(daily) < 22: return

        # Daily Trend Filter
        ma20_daily_now = daily.close.iloc[-20:].mean()
        ma20_daily_prev = daily.close.iloc[-21:-1].mean()
        current_daily_close = daily.close.iloc[-1]

        if current_daily_close < ma20_daily_now:
             self.log_monitor(f"[감시 제외] {symbol} {stock_name} | 하락 추세 (현재 < Daily MA20)")
             return

        if ma20_daily_now < ma20_daily_prev:
             self.log_monitor(f"[감시 제외] {symbol} {stock_name} | Daily MA20 하락")
             return

        # Daily Relative Volume Filter
        prev_daily_vol_k = self.config.get("prev_daily_vol_k", 1.5)
        prev_vol = daily.volume.iloc[-2]
        prev_avg_vol = daily.volume.iloc[-22:-2].mean()

        if prev_avg_vol > 0 and prev_vol < (prev_avg_vol * prev_daily_vol_k):
             self.log_monitor(f"[감시 제외] {symbol} {stock_name} | 전일 거래량 부족")
             return

        # Intraday Check
        bars = self.market_data.get_bars(symbol, timeframe=self.config["timeframe"])
        if bars is None or len(bars) < 20: return

        ma_short = self.config.get("ma_short", 5)
        ma_long = self.config.get("ma_long", 20)

        # Vectorized MA Calc is fast for small windows, simple mean is fine
        ma_short_now = bars.close.iloc[-ma_short:].mean()
        ma_long_now = bars.close.iloc[-ma_long:].mean()
        volume_now = bars.volume.iloc[-1]
        avg_vol20 = bars.volume.iloc[-20:].mean()

        whipsaw_threshold = self.config.get("whipsaw_threshold", 0.0)
        cross_lookback = self.config.get("cross_lookback", 1)
        vol_k = self.config.get("vol_k", 1.5)

        # 1. Golden Cross Check (Loop optimized)
        recent_cross_occurred = False
        lookback_limit = min(cross_lookback, len(bars) - ma_long - 1)

        if lookback_limit >= 1:
            # Only check if strictly needed.
            # If current status is not uptrend, cross implies it just happened or failed.
            if ma_short_now > ma_long_now:
                 # Check previous bars to confirm cross happened recently
                 # Optimization: Only calculate MA for previous bar first
                 m_s_prev = bars.close.iloc[-(ma_short+1):-1].mean()
                 m_l_prev = bars.close.iloc[-(ma_long+1):-1].mean()

                 if m_s_prev <= m_l_prev:
                     recent_cross_occurred = True
                 else:
                     # Check further back if lookback > 1
                     for i in range(1, lookback_limit):
                        idx_end = -1 - i
                        m_s = bars.close.iloc[idx_end-ma_short:idx_end].mean()
                        m_l = bars.close.iloc[idx_end-ma_long:idx_end].mean()
                        m_s_p = bars.close.iloc[idx_end-ma_short-1:idx_end-1].mean()
                        m_l_p = bars.close.iloc[idx_end-ma_long-1:idx_end-1].mean()

                        if m_s_p <= m_l_p and m_s > m_l:
                             recent_cross_occurred = True
                             break

        in_uptrend = ma_short_now > ma_long_now
        strong_breakout = bars.close.iloc[-1] >= ma_long_now * (1 + whipsaw_threshold)
        vol_ok = volume_now > avg_vol20 * vol_k

        # Periodic Log
        if avg_vol20 > 0:
             vol_ratio = (volume_now / avg_vol20)
             ma_stat = "(골든크로스)" if recent_cross_occurred else ("(정배열)" if in_uptrend else "(대기)")
             vol_stat = "(충족)" if vol_ok else "(부족)"
             self.log_monitor(f"[감시 중] {symbol} {stock_name} | 추세: {ma_stat} | 거래량: {vol_ratio:.1f}배 {vol_stat}")

        if recent_cross_occurred and in_uptrend and vol_ok:
            if not strong_breakout:
                 current_sep = ((bars.close.iloc[-1]/ma_long_now)-1)*100
                 self.logger.info(f"[진입 보류] {symbol} {stock_name} | 휩쏘 필터 미달 ({current_sep:.2f}%)")
                 return

            buy_qty = self.calculate_buy_quantity(symbol, current_price)
            if buy_qty > 0:
                if self.risk.can_open_new_position(symbol, buy_qty, current_price):
                    self.logger.info(f"[매수 진입] {symbol} {stock_name} | 조건 만족 | 수량: {buy_qty}")
                    self.broker.buy_market(symbol, buy_qty, tag=self.config["id"])
            else:
                position = self.portfolio.get_position(symbol)
                if position:
                     self.logger.info(f"[진입 생략] {symbol} {stock_name} | 목표 비중 도달")
                else:
                     self.logger.warning(f"[매수 실패] {symbol} {stock_name} | 수량 0 (자산 부족/리스크)")
