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

            stock_name = self.market_data.get_stock_name(symbol)

            avg_price = position.avg_price
            if avg_price <= 0:
                pnl_pct = 0.0
            else:
                pnl_pct = (current_price - avg_price) / avg_price * 100
            
            high_price = bar.get('high', current_price)
            max_price = max(position.max_price, high_price)
            if max_price <= 0:
                max_price = current_price
            
            # 사용자 알림: 1% 이상 수익 변동 시에만 로그 출력
            if abs(pnl_pct) > 1.0:
                 self.logger.info(f"[{symbol} {stock_name}] 보유 중 | 현재가: {int(current_price):,}원 | 수익률: {pnl_pct:.2f}% (목표: {self.config['take_profit1_pct']}%)")

            # Breakeven Stop (Safety)
            # If partial profit taken, do not let remaining position turn into loss
            if position.partial_taken and current_price < avg_price:
                 self.logger.info(f"[{symbol} {stock_name}] 본전 탈출 (Breakeven) 실행 | 현재가: {int(current_price):,}원 < 평단가")
                 self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
                 return

            # Stop Loss (Only if not partial taken, or if price drops significantly below avg despite breakeven logic)
            if pnl_pct <= -self.config["stop_loss_pct"]:
                self.logger.info(f"[{symbol} {stock_name}] 손절매 (Stop Loss) 실행 | 수익률: {pnl_pct:.2f}% (조건: -{self.config['stop_loss_pct']}%)")
                self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
                return

            # Take Profit (Partial)
            if (not position.partial_taken) and pnl_pct >= self.config["take_profit1_pct"]:
                half = position.qty // 2
                if half > 0:
                    self.logger.info(f"[{symbol} {stock_name}] 1차 수익 실현 (Partial TP) | 수익률: {pnl_pct:.2f}% | 매도수량: {half}주")
                    self.broker.sell_market(symbol, half, tag=self.config["id"])
                    position.partial_taken = True
                    self.portfolio.save_state() # Persist state

            # Trailing Stop
            if max_price > 0:
                drawdown_from_high = (current_price - max_price) / max_price * 100
                if drawdown_from_high <= -self.config["trail_stop_pct"]:
                    self.logger.info(f"[{symbol} {stock_name}] 트레일링 스탑 실행 | 고점 대비 하락: {drawdown_from_high:.2f}% (고점: {int(max_price):,}원)")
                    self.broker.sell_market(symbol, position.qty, tag=self.config["id"])
            
            return # Exit logic done

        # 2. Entry Logic (Needs History)
        # self.logger.info(f"DEBUG: on_bar triggered for {symbol}") # 진입 확인용
        # Rate Limit Check (Default 5s from BaseStrategy)
        if not self.check_rate_limit(symbol):
            # self.logger.info(f"DEBUG: Rate limit hit for {symbol}")
            return

        # Optimization handled by check_rate_limit
        # Only fetch history if we don't have a position and might want to enter
        bars = self.market_data.get_bars(symbol, timeframe=self.config["timeframe"])
        daily = self.market_data.get_bars(symbol, timeframe="1d")
        
        stock_name = self.market_data.get_stock_name(symbol)

        # Debug Data Status
        # self.logger.debug(f"DEBUG: {symbol} Date={bar.get('date')} Bars={len(bars)} Daily={len(daily)}")

        if daily is None or len(daily) < 20:
             self.logger.warning(f"[데이터 부족] {symbol} {stock_name} | 일봉 데이터 부족 ({len(daily) if daily is not None else 0}/20)")
             return

        # Daily Trend Filter
        # Use simple MA20 logic
        ma20_daily_now = daily.close.iloc[-20:].mean()
        # ma20_daily_prev = daily.close.iloc[-21:-1].mean() # unused for simple logic? used below
        ma20_daily_prev = daily.close.iloc[-21:-1].mean()

        # Check if MA20 is rising and Close > MA20
        trend_up = (ma20_daily_now > ma20_daily_prev) and (daily.close.iloc[-1] > ma20_daily_now)
        
        if not trend_up:
             self.logger.info(f"[감시 제외] {symbol} {stock_name} | 사유: 하락 추세 (현재 {int(daily.close.iloc[-1]):,} < MA20 {int(ma20_daily_now):,})")
             return

        # Trend is UP -> Check Intraday Data
        if bars is None or len(bars) < 20:
             self.logger.info(f"[감시 중] {symbol} {stock_name} | 대기: 데이터 수집 중 (분봉 {len(bars) if bars is not None else 0}/20)")
             return

        # Detailed Monitoring (Trend UP + Sufficient Data)
        ma5_now = bars.close.iloc[-5:].mean()
        ma20_now = bars.close.iloc[-20:].mean()
        
        volume_now = bars.volume.iloc[-1]
        avg_vol20 = bars.volume.iloc[-20:].mean()

        if avg_vol20 > 0:
             # 주기적(10초)으로 관심 종목 상태(Golden Cross + 거래량) 상세 알림
             vol_k = self.config.get("vol_k", 1.5)
             vol_ratio = (volume_now / avg_vol20)
             
             ma_stat = "(대기)" if ma5_now <= ma20_now else "(충족)"
             vol_stat = "(부족)" if vol_ratio < vol_k else "(충족)"
             
             self.logger.info(f"[감시 중] {symbol} {stock_name} | 현재가: {int(bars.close.iloc[-1]):,} | 이평돌파: {int(ma5_now):,} ≥ {int(ma20_now):,}{ma_stat} | 거래량비: {vol_ratio:.1f} ≥ {vol_k:.1f}{vol_stat}")

        # Intraday MA Calculation
        ma5_now = bars.close.iloc[-5:].mean()
        ma5_prev = bars.close.iloc[-6:-1].mean()
        ma20_now = bars.close.iloc[-20:].mean()
        ma20_prev = bars.close.iloc[-21:-1].mean()

        volume_now = bars.volume.iloc[-1]
        avg_vol20 = bars.volume.iloc[-20:].mean()

        golden_cross = (ma5_prev <= ma20_prev) and (ma5_now > ma20_now)
        vol_ok = volume_now > avg_vol20 * self.config.get("vol_k", 1.5)
        
        if golden_cross and not vol_ok:
             self.logger.info(f"[{symbol} {stock_name}] 골든크로스 발생했으나 거래량 부족 (현재: {volume_now}, 필요: {int(avg_vol20 * self.config.get('vol_k', 1.5))})")

        if golden_cross and vol_ok:
            qty = self.calc_position_size(symbol)
            if self.risk.can_open_new_position(symbol, qty):
                self.logger.info(f"[{symbol} {stock_name}] 매수 진입 (골든크로스 + 거래량 충족) | 수량: {qty}주 | 현재가: {int(bars.close.iloc[-1]):,}원")
                self.broker.buy_market(symbol, qty, tag=self.config["id"])
