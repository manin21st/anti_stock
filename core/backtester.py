import logging
import pandas as pd
from typing import Dict, Optional, Callable, List
from datetime import datetime, timedelta
import time

from core import interface as ka
from core.market_data import MarketData
from core.broker import Broker
from core.portfolio import Portfolio
from core.risk import Risk
from utils.data_loader import DataLoader

logger = logging.getLogger(__name__)

class Backtester:
    def __init__(self, config: Dict, strategy_classes: Dict):
        self.config = config
        self.strategy_classes = strategy_classes
        self._data_loader = DataLoader()
        self._suppressed_loggers = []

    def run_backtest(self, strategy_id: str, symbol: str, start_date: str, end_date: str, initial_cash: int = 100000000, strategy_config: Dict = None, progress_callback=None) -> Dict:
        """
        Run backtest for a specific strategy and symbol.
        Returns a dictionary with result metrics and history.
        """
        logger.info(f"Starting Backtest: {strategy_id} on {symbol} ({start_date}~{end_date})")

        # 1. Setup Isolated Environment (The Matrix)
        
        # Suppress Logs during Backtest
        logging.getLogger('core.broker').setLevel(logging.WARNING)
        logging.getLogger('core.market_data').setLevel(logging.WARNING)
        # logging.getLogger('core.risk').setLevel(logging.WARNING) # Keep Risk logs visible? Maybe.
        
        # Activate API Backtest Mode
        ka.set_backtest_mode(True)
        
        # Create Isolated Components
        # Note: MarketData init will skip API connect due to backtest mode
        sim_market = MarketData()
        sim_broker = Broker()
        # Portfolio with state_file=None to prevent persistence
        sim_portfolio = Portfolio(state_file=None)
        
        # Update Config for Strategy
        temp_cfg = self.config.get(strategy_id, {}).copy()
        if strategy_config:
            temp_cfg.update(strategy_config)
        
        # Inject is_simulation flag into config
        temp_cfg["is_simulation"] = True
        
        sim_risk = Risk(sim_portfolio, self.config) # Base config needed for common settings
        
        # Initialize Simulation State
        virtual_state = {
            "cash": float(initial_cash),
            "positions": {}, # {symbol: {qty, avg_price, amount}}
            "orders": []
        }
        
        ka.set_mock_state(virtual_state["cash"], virtual_state["positions"], {}) # Initial State
        
        # Load Data
        tf = temp_cfg.get("timeframe", "D")
        buffer_days = 60 if tf == "D" else 5
        
        # Helper to parse dates
        def parse_date(d):
            try: return datetime.strptime(d, "%Y%m%d")
            except: return datetime.strptime(d, "%Y-%m-%d")
            
        s_dt = parse_date(start_date)
        e_dt_str = end_date.replace("-", "")
        buffer_date = (s_dt - timedelta(days=buffer_days)).strftime("%Y%m%d")
        start_date_str = s_dt.strftime("%Y%m%d")

        logger.info(f"Loading data from local storage: {buffer_date} ~ {e_dt_str} (TF: {tf})")
        df = self._data_loader.load_data(symbol, buffer_date, e_dt_str, timeframe=tf)
        
        if df.empty:
            self._cleanup_backtest()
            return {"error": "No data found. Please run download first."}

        # Register Data Provider for Strategy's Historical Data Requests
        # Strategy might ask for 1d bars for trend check
        def data_provider(req_symbol, req_type, req_start, req_end=None):
            # Simple provider that uses existing data loader
            # Optimally we should use the loaded 'df' if applicable, but Strategy might ask for different ranges.
            # We let DataLoader load it (cached).
            if req_type == "day":
                # CRITICAL Fix for Backtest:
                # MarketData uses datetime.now() to calc start/end, which is Real Time.
                # In backtest, we must return data relative to Simulation Time.
                
                sim_date = ka._mock_state.get('date')
                if sim_date:
                    # Adjust req_end to Simulation Date to prevent Look-ahead
                    req_end = sim_date
                    
                    # Adjust req_start to ensure we have enough history from Sim Date
                    # Simulating "100 days lookback" from Sim Date
                    try:
                        s_dt_obj = datetime.strptime(sim_date, "%Y%m%d")
                        # 150 days buffer to be safe for trading days
                        req_start = (s_dt_obj - timedelta(days=150)).strftime("%Y%m%d")
                    except:
                        pass
                
                d = self._data_loader.load_data(req_symbol, req_start, req_end, timeframe="D")
                if not d.empty:
                    return d.to_dict('records')
            elif req_type == "min":
                 # req_start is YYYYMMDD (Current Simulation Date)
                 # req_end is HHMMSS (Current Simulation Time)
                 
                 # Load minute data for this day
                 d = self._data_loader.load_data(req_symbol, start_date=req_start, end_date=req_start, timeframe="1m")
                 
                 if not d.empty:
                     # Filter for time <= req_end
                     # Ensure time column is string
                     # DataLoader ensures 'time' is str
                     
                     if req_end:
                         d = d[d['time'] <= req_end]
                     
                     # MarketData expects KIS-like list of dicts
                     return d.to_dict('records')
            return []
            
        ka.set_data_provider(data_provider)

        # Initialize Strategy
        if strategy_id not in self.strategy_classes:
            self._cleanup_backtest()
            return {"error": f"Strategy {strategy_id} not registered."}

        st_class = self.strategy_classes[strategy_id]
        st_cfg = temp_cfg
        st_cfg["id"] = strategy_id

        strategy = st_class(
            config=st_cfg,
            broker=sim_broker,
            risk=sim_risk,
            portfolio=sim_portfolio,
            market_data=sim_market
        )
        
        # Suppress Strategy Logger
        # Strategies usually use logging.getLogger(self.__class__.__name__)
        # We need to suppress only for this backtest instance.
        # But logging is global. We restore it later.
        strat_logger_name = st_class.__name__
        logging.getLogger(strat_logger_name).setLevel(logging.WARNING)
        self._suppressed_loggers.append(strat_logger_name) # Track to restore

        # 3. Execution Loop
        history = []
        daily_stats = []
        
        # Prepare Data Iterator
        if tf == "D":
            dates = df['date'].unique()
            dates.sort()
            # Filter only requested range
            dates = [d for d in dates if d >= start_date_str]
            data_map = df.set_index('date').to_dict('index')
            
            total_steps = len(dates)
            
            for i, date in enumerate(dates):
                row = data_map[date]
                # Inject State
                current_price = row['close']
                ka.set_mock_state(
                    virtual_state["cash"], 
                    virtual_state["positions"], 
                    {symbol: current_price},
                    date=date
                )
                
                # Update Internal Stats Calculation for Progress
                self._update_progress(i, total_steps, virtual_state, current_price, symbol, start_date, progress_callback, history)
                
                # Execute Step
                try:
                    # Create Bar Object
                    bar = row.copy()
                    bar['date'] = date
                    strategy.on_bar(symbol, bar)
                except Exception as e:
                    logger.error(f"Strategy Error on {date}: {e}")

                # Process Orders & Update State
                self._process_orders(symbol, current_price, virtual_state, history, date, sim_portfolio, progress_callback)
                
                # End of Day Stats
                daily_stats.append({
                    "date": date,
                    "total_asset": sim_portfolio.total_asset,
                    "cash": sim_portfolio.cash,
                    "holdings_val": sim_portfolio.total_asset - sim_portfolio.cash
                })

        else: # Intraday
             # Similar logic but iterating datetime
             pass # Implement if needed, but keeping it simple for now based on D logic logic structure
             
             # Fallback logic for Intraday support (copied/adapted from prev implementation)
             df['date'] = df['date'].astype(str)
             df['time'] = df['time'].astype(str).str.zfill(6)
             df['datetime'] = pd.to_datetime(df['date'] + df['time'], format="%Y%m%d%H%M%S")
             df = df.set_index('datetime').sort_index()
             
             # Filter Range
             df = df[df['date'] >= start_date_str]
             
             # Resample to TF
             rule = tf.replace("m", "min")
             resampled = df.resample(rule).agg({
                'date': 'first', 'time': 'last', 'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
             }).dropna()
             
             total_steps = len(resampled)
             
             prev_date = None
             
             for i, (dt, row) in enumerate(resampled.iterrows()):
                 current_price = row['close']
                 date_str = str(row['date'])
                 time_str = str(row['time'])
                 
                 # Clear Cache on Day Change
                 if prev_date != date_str:
                     sim_market._daily_cache.clear()
                     prev_date = date_str
                 
                 ka.set_mock_state(
                    virtual_state["cash"], 
                    virtual_state["positions"], 
                    {symbol: current_price},
                    date=date_str,
                    time=time_str
                 )

                 if i % 10 == 0:
                     self._update_progress(i, total_steps, virtual_state, current_price, symbol, start_date, progress_callback, history)

                 try:
                     bar = row.to_dict()
                     strategy.on_bar(symbol, bar)
                 except Exception as e:
                     logger.error(f"Strategy Error on {dt}: {e}")

                 self._process_orders(symbol, current_price, virtual_state, history, f"{date_str} {time_str}", sim_portfolio, progress_callback)


        # 4. Final Wrap-up
        self._cleanup_backtest()
        
        # Metrics
        end_asset = sim_portfolio.total_asset
        total_return = (end_asset - initial_cash) / initial_cash * 100
        
        return {
            "metrics": {
                "total_return": round(total_return, 2),
                "total_asset": int(end_asset),
                "mdd": 0.0, # TODO: Implement MDD
                "trade_count": len(history),
            },
            "history": history,
            "daily_stats": daily_stats
        }

    def _update_progress(self, current_step, total_steps, state, price, symbol, start_date, callback, history):
        if not callback: return

        # Calc metrics for display
        pos = state["positions"].get(symbol, {})
        qty = pos.get('qty', 0)
        avg_price = pos.get('avg_price', 0)
        cash = state["cash"]
        
        eval_amt = qty * price
        total_asset = cash + eval_amt
        # Use initial cash from start? We don't have it passed here easily unless stored.
        # Approximation.
        
        status = {
            "percent": int((current_step / total_steps) * 100),
            "qty": qty,
            "avg_price": avg_price,
            "buy_amt": qty * avg_price,
            "current_price": price,
            "eval_amt": eval_amt,
            "eval_pnl": eval_amt - (qty * avg_price),
            "return_rate": 0, # Calculated in UI mostly or passed?
            "trade_count": len(history)
        }
        callback("progress", status)

    def _process_orders(self, symbol, current_price, state, history, timestamp, portfolio, callback):
        orders = ka.get_mock_orders()
        
        for order in orders:
            # {'symbol':..., 'qty':..., 'buy_sell_gb': '1'/'2', 'ord_dv':...} OR KIS Params
            
            # 1. Parse Quantity
            if 'qty' in order:
                qty = int(order['qty'])
            elif 'ORD_QTY' in order:
                qty = int(order['ORD_QTY'])
            else:
                logger.warning(f"Unknown Order Format (No Qty): {order}")
                continue
                
            # 2. Parse Side (Buy/Sell)
            side = order.get('buy_sell_gb')
            if not side:
                tr_id = order.get('tr_id', '')
                # TTTC0802U/VTTC0802U -> Buy (2)
                # TTTC0801U/VTTC0801U -> Sell (1)
                # Note: KIS Broker often uses '1' for Sell? '2' for Buy?
                # Broker._send_order passes '1' for Sell, '2' for Buy.
                # Broker logic:
                # if buy_sell_gb == "1": tr_id = ...801U (Sell)
                # if buy_sell_gb == "2": tr_id = ...802U (Buy)
                # Wait. Standard KIS constants:
                # 0802U -> Buy
                # 0801U -> Sell
                
                if "0802U" in tr_id:
                     side = "2" # Broker mapping: 1=Sell, 2=Buy.
                     # Wait. Backtester logic:
                     # if side == "1": # Buy
                     # elif side == "2": # Sell
                     # THIS CONTRADICTS Broker.py?
                     # Let's check Backtester lines 304, 324.
                     # line 304: if side == "1": # Buy
                     # line 324: elif side == "2": # Sell
                     # This logic in Backtester seems to assume '1' is Buy.
                     # Broker.py says: Buy='2', Sell='1'.
                     # CHECK BROKER.PY!
                elif "0801U" in tr_id:
                     side = "1" 
                else:
                     logger.warning(f"Unknown TR_ID for side: {tr_id}")
                     continue

            # Resolve Side to Backtester's internal '1'/'2' convention
            # Backtester Logic: "1" = Buy, "2" = Sell
            # Broker Logic: "2" = Buy, "1" = Sell
            # We must normalize.
            # If tr_id indicates Buy (0802U), set side="1" (Backtester Buy).
            # If tr_id indicates Sell (0801U), set side="2" (Backtester Sell).
            
            if "0802U" in order.get('tr_id', ''):
                backtest_side = "1" # Buy
            elif "0801U" in order.get('tr_id', ''):
                backtest_side = "2" # Sell
            elif side == "2": # Broker Buy
                 backtest_side = "1"
            elif side == "1": # Broker Sell
                 backtest_side = "2"
            else:
                 backtest_side = side # Fallback
            
            # Simple Execution Logic (Market Price)
            exec_price = current_price
            
            if backtest_side == "1": # Buy
                cost = exec_price * qty
                fee = cost * 0.00015
                total_cost = cost + fee
                
                if state['cash'] >= total_cost:
                    state['cash'] -= total_cost
                    if symbol not in state['positions']:
                        state['positions'][symbol] = {'qty': 0, 'avg_price': 0, 'amount': 0}
                    
                    p = state['positions'][symbol]
                    old_qty = p['qty']
                    old_amt = p['amount']
                    
                    p['qty'] += qty
                    p['amount'] += cost
                    p['avg_price'] = p['amount'] / p['qty']
                    
                    self._log_trade(history, timestamp, symbol, "BUY", qty, exec_price, order.get('tag'), callback)
                    
            elif side == "2": # Sell
                p = state['positions'].get(symbol)
                if p and p['qty'] >= qty:
                    revenue = exec_price * qty
                    fee = revenue * 0.00015 + revenue * 0.002 # Tax
                    net_revenue = revenue - fee
                    
                    state['cash'] += net_revenue
                    p['qty'] -= qty
                    # Update amount proportionally
                    p['amount'] = p['avg_price'] * p['qty']
                    
                    if p['qty'] <= 0:
                        del state['positions'][symbol]
                        
                    self._log_trade(history, timestamp, symbol, "SELL", qty, exec_price, order.get('tag'), callback)

        # Update Portfolio (Constructing Mock Balance)
        holdings = []
        total_eval = 0
        for s, p in state['positions'].items():
            ev = p['qty'] * current_price
            total_eval += ev
            holdings.append({
                "pdno": s,
                "prdt_name": s,
                "hldg_qty": str(p['qty']),
                "pchs_avg_pric": str(p['avg_price']),
                "prpr": str(current_price)
            })
            
        summary = [{
            "dnca_tot_amt": str(state['cash']),
            "tot_evlu_amt": str(state['cash'] + total_eval),
            # Mocking D+2 deposit as cash for simple backtest logic
            "prvs_rcdl_excc_amt": str(state['cash'])
        }]
        
        # Sync
        portfolio.sync_with_broker({"holdings": holdings, "summary": summary}, notify=False, allow_clear=True)

    def _log_trade(self, history, timestamp, symbol, side, qty, price, tag, callback):
        info = {
            "timestamp": timestamp,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "tag": tag,
            "order_no": f"SIM_{int(time.time()*1000)}"
        }
        history.append(info)
        if callback:
            callback("trade_event", info)

    def _cleanup_backtest(self):
        ka.set_backtest_mode(False)
        ka.clear_mock_orders()
        
        # Restore Log Levels
        logging.getLogger('core.broker').setLevel(logging.INFO)
        logging.getLogger('core.market_data').setLevel(logging.INFO)
        
        for name in self._suppressed_loggers:
            logging.getLogger(name).setLevel(logging.INFO)
        self._suppressed_loggers.clear()
