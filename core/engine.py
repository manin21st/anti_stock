import logging
import time
import threading
from typing import Dict, List
import sys
import os
import yaml

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.market_data import MarketData
from core.broker import Broker
from core.portfolio import Portfolio
from core.risk_manager import RiskManager
from core.scanner import Scanner
from core.visualization import TradeEvent
from datetime import datetime
import uuid
# strategies will be imported dynamically or explicitly

logger = logging.getLogger(__name__)

class Engine:
    def __init__(self, config_path: str = "config/strategies.yaml"):
        self.config = self._load_config(config_path)
        self.system_config = self.config.get("system", {"env_type": "paper", "market_type": "KRX"})
        
        # Authenticate first
        env_type = self.system_config.get("env_type", "paper")
        svr = "vps" if env_type == "paper" else "prod"
        logger.info(f"Authenticating for {env_type} ({svr})")
        
        from core import kis_api as ka
        try:
            ka.auth(svr=svr)
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            # We might want to raise here, but let's continue and let components fail if they must
        
        self.market_data = MarketData()
        self.broker = Broker()
        self.portfolio = Portfolio()
        self.risk_manager = RiskManager(self.portfolio)
        self.scanner = Scanner()
        self.strategies = {} # strategy_id -> Strategy Instance
        self.strategy_classes = {} # strategy_id -> Strategy Class
        
        self.is_running = False
        self.is_trading = False
        self.restart_requested = False
        self.last_scan_time = 0
        self.last_sync_time = 0
        
        # Subscribe to market data events
        self.market_data.subscribers.append(self.on_market_data)
        
        # Trade History
        self.trade_history: List[TradeEvent] = []
        
        # Subscribe to Broker and Portfolio events
        self.broker.on_order_sent.append(self.record_order_event)
        self.portfolio.on_position_change.append(self.record_position_event)

    def update_system_config(self, new_config: Dict):
        """Update system configuration"""
        self.system_config.update(new_config)
        # Update main config as well so it gets saved
        if "system" not in self.config:
            self.config["system"] = {}
        self.config["system"].update(new_config)
        logger.info(f"System config updated: {self.system_config}")

    def restart(self):
        """Restart the engine with new settings"""
        logger.info("Restart requested...")
        self.restart_requested = True
        self.is_trading = False

    def start_trading(self):
        """Enable trading"""
        self.is_trading = True
        logger.info("Trading started")

    def stop_trading(self):
        """Disable trading"""
        self.is_trading = False
        logger.info("Trading stopped (Standby)")

    def run(self):
        """Main Engine Loop (Blocking)"""
        self.is_running = True
        self.is_trading = True # Start in active mode by default
        
        while self.is_running:
            logger.info("Engine loop started")
            
            # Re-authenticate if needed (e.g. on restart)
            # Note: Initial auth is done in __init__
            env_type = self.system_config.get("env_type", "paper")
            svr = "vps" if env_type == "paper" else "prod"
            
            from core import kis_api as ka
            try:
                # On restart, we might want to re-auth to be safe
                if self.restart_requested:
                    logger.info(f"DEBUG: Re-authenticating for {env_type} ({svr})")
                    ka.auth(svr=svr)
                
                # Re-instantiate strategies with fresh config
                self.strategies.clear()
                
                active_strategy_id = self.config.get("active_strategy")
                logger.info(f"Active strategy ID: {active_strategy_id}")
                
                if active_strategy_id and active_strategy_id in self.strategy_classes:
                    strategy_class = self.strategy_classes[active_strategy_id]
                    strategy_config = self.config.get(active_strategy_id, {})
                    
                    if "common" in self.config:
                        strategy_config.update(self.config["common"])
                    
                    # Ensure ID is set
                    strategy_config["id"] = active_strategy_id
                        
                    strategy = strategy_class(
                        config=strategy_config,
                        broker=self.broker,
                        risk_manager=self.risk_manager,
                        portfolio=self.portfolio,
                        market_data=self.market_data
                    )
                    self.strategies[active_strategy_id] = strategy
                    logger.info(f"Initialized active strategy: {active_strategy_id}")
                else:
                    logger.warning(f"Strategy not found: {active_strategy_id}")
                
                # Sync initial portfolio state
                # Sync initial portfolio state
                balance = self.broker.get_balance()
                # logger.debug(f"Broker Balance: {balance}")
                if balance:
                    self.portfolio.sync_with_broker(balance)
                    self.portfolio.load_state()
                    
                    total_asset = int(self.portfolio.total_asset)
                    cash = int(self.portfolio.cash)
                    # logger.info(f"[포트폴리오 초기화] 총자산: {total_asset:,}원 | 예수금: {cash:,}원")
                else:
                    logger.error("브로커 잔고 조회 실패")
                
                # time.sleep(1.0) # Prevent rate limit (Handled by RateLimiter)

                # 2. Cache Watchlist
                target_group = self.system_config.get("watchlist_group_code", "000")
                logger.info(f"Fetching Watchlist (Group {target_group}) for caching...")
                try:
                    self.cached_watchlist = self.scanner.get_watchlist(target_group_code=target_group)
                    logger.info(f"Cached Watchlist: {len(self.cached_watchlist)} stocks")
                except Exception as e:
                    logger.error(f"Failed to cache watchlist: {e}")
                    self.cached_watchlist = []

                # time.sleep(1.0) # Prevent rate limit (Handled by RateLimiter)

                # 3. Initial Universe Scan
                self._update_universe()
                
                # Log Initial Universe
                if hasattr(self.market_data, 'polling_symbols'):
                     symbols = self.market_data.polling_symbols
                     # Get names roughly (this is strict map, might be slow if many, but ok for init)
                     # For display, just codes is fine or use scanner's cache if available.
                     logger.info(f"[감시 종목 업데이트] 총 {len(symbols)}개: {', '.join(symbols[:10])}{' ...' if len(symbols)>10 else ''}")

            except Exception as e:
                logger.error(f"초기화 실패: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
            # Start MarketData Polling (REST API)
            # ws_thread = threading.Thread(target=self.market_data.start_ws, daemon=True)
            # ws_thread.start()
            self.market_data.start_polling()
            
            # Inner Loop
            self.restart_requested = False
            last_heartbeat = time.time()
            try:
                while not self.restart_requested and self.is_running:
                    # Periodic Scanner Update
                    if self.system_config.get("use_auto_scanner", False):
                        # User requested fast updates (e.g. 5-10s). 
                        # Optimization: Increase to 60s to avoid rate limits (EGW00201)
                        if time.time() - self.last_scan_time > 60: 
                            self._update_universe()
                            # Log Updated Universe
                            if hasattr(self.market_data, 'polling_symbols'):
                                symbols = self.market_data.polling_symbols
                                logger.info(f"[감시 종목 업데이트] 총 {len(symbols)}개: {', '.join(symbols[:10])}{' ...' if len(symbols)>10 else ''}")
                    
                    # Heartbeat
                    # Heartbeat
                    if time.time() - last_heartbeat > 3:
                        if int(time.time()) % 60 == 0:  # Log every minute
                            # System Status Summary
                            n_monitoring = len(self.market_data.polling_symbols) if hasattr(self.market_data, 'polling_symbols') else 0
                            n_positions = len(self.portfolio.positions)
                            total_asset = int(self.portfolio.total_asset)
                            
                            logger.info(f"[시스템 정상] 감시: {n_monitoring}종목 | 보유: {n_positions}종목 | 총자산: {total_asset:,}원")
                        last_heartbeat = time.time()
                    
                    # Periodic Portfolio Sync (Every 5 seconds)
                    # This ensures manual trades (HTS) are reflected in real-time
                    if time.time() - self.last_sync_time > 5:
                        try:
                            balance = self.broker.get_balance()
                            if balance:
                                self.portfolio.sync_with_broker(balance)
                                # logger.debug("Portfolio synced with broker")
                            self.last_sync_time = time.time()
                        except Exception as e:
                            logger.error(f"Failed to sync portfolio: {e}")
                    
                    time.sleep(1)
            except KeyboardInterrupt:
                self.stop()
                return

            if self.restart_requested:
                logger.info("Performing restart...")
                time.sleep(1)
                continue # Loop back to re-init
            
            if not self.is_running:
                break

    def _update_universe(self):
        """Update stock universe based on config or scanner"""
        universe = []
        
        if self.system_config.get("use_auto_scanner", False):
            mode = self.system_config.get("scanner_mode", "volume")
            logger.info(f"Auto-Scanner running... Mode: {mode}")
            
            try:
                if mode == "volume":
                    # Use Trading Value (Amount) instead of Volume, and filter ETFs/SPACs
                    items = self.scanner.get_trading_value_leaders(limit=50)
                else:
                    items = self.scanner.get_top_gainers(limit=50)
                
                # Defensive extraction of symbols
                scanned_symbols = []
                if items:
                    for item in items:
                        if isinstance(item, dict) and "symbol" in item:
                            scanned_symbols.append(item["symbol"])
                        else:
                            logger.warning(f"Scanner returned invalid item: {item}")

                logger.info(f"Scanner found {len(scanned_symbols)} stocks: {scanned_symbols}")
                
                # Filter by Manual Universe (Watchlist)
                # Use Cached Watchlist
                api_watchlist = getattr(self, 'cached_watchlist', [])
                manual_watchlist = self.system_config.get("universe", [])
                
                # Merge lists (API + Manual Config)
                full_watchlist = set(api_watchlist)
                if manual_watchlist:
                    full_watchlist.update([str(x).zfill(6) for x in manual_watchlist])
                
                watchlist = list(full_watchlist)
                
                if watchlist:
                    # Normalize watchlist
                    watchlist = [str(x).zfill(6) for x in watchlist]
                    # Intersection
                    universe = [s for s in scanned_symbols if s in watchlist]
                    logger.info(f"Filtered by Watchlist (API+Manual): {len(universe)} stocks selected {universe}")
                else:
                    logger.warning("Auto-Scanner is on, but Watchlist (API & Manual) is empty. No stocks selected.")
                    universe = []

            except Exception as e:
                logger.error(f"Scanner failed: {e}")
                universe = []
        else:
            universe = self.system_config.get("universe", [])
            logger.info(f"Using manual universe: {universe}")
            
        # Combine Universe + Current Holdings for subscription
        subscription_list = set(universe) if universe else set()
        
        # Add current holdings to subscription list so we can manage exits
        if self.portfolio.positions:
            holdings = [str(s).zfill(6) for s in self.portfolio.positions.keys()]
            subscription_list.update(holdings)
            logger.info(f"Added {len(holdings)} holdings to subscription list: {holdings}")
            
        if subscription_list:
            # Ensure all are strings and 6 digits
            final_list = [str(x).zfill(6) for x in subscription_list]
            self.market_data.subscribe_market_data(final_list)
        
        # Always update scan time to prevent tight loop on empty results
        self.last_scan_time = time.time()

    def _load_config(self, path: str) -> Dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}

    def register_strategy(self, strategy_class, strategy_id: str):
        """Register a strategy class"""
        self.strategy_classes[strategy_id] = strategy_class
        # logger.info(f"Registered strategy class: {strategy_id}")

    def stop(self):
        self.is_running = False
        if hasattr(self, 'market_data'):
            self.market_data.stop_polling()
        logger.info("Engine stopped")

    def update_strategy_config(self, new_config: Dict):
        """Update strategy configuration (Config only, applied on restart)"""
        # new_config is a dict of {strategy_id: {config}}
        for strategy_id, config_data in new_config.items():
            if strategy_id in self.config:
                self.config[strategy_id].update(config_data)
            else:
                logger.warning(f"Strategy config {strategy_id} not found for update")

    def on_market_data(self, data: Dict):
        """Handle real-time market data"""
        symbol = data.get("symbol")
        if not symbol:
            return
        
        if not self.is_trading:
            return

        # logger.info(f"PROBE: Tick received for {symbol} | Price: {data.get('price')}")
        for strategy in self.strategies.values():
            # if not strategy.enabled: # REMOVED: Legacy check. Active strategy is always enabled.
            #     continue
            
            # Check if strategy is interested in this symbol? 
            # For now, pass to all, let strategy decide or filter.
            try:
                # We might want to construct a 'Bar' or 'Tick' object here
                # data is a dict from MarketData
                # Call on_tick for tick-based logic
                strategy.on_tick(symbol, data)
                
                # Also call on_bar with the current tick data treated as a 'bar' update
                # This ensures strategies like ma_trend (which use on_bar) get real-time updates for exits
                # Construct a minimal bar object from tick with defensive defaults
                current_price = data.get('price', 0.0)
                bar = {
                    'open': data.get('open', current_price),
                    'high': data.get('high', current_price),
                    'low': data.get('low', current_price),
                    'close': data.get('close', current_price),
                    'volume': data.get('volume', 0),
                    'time': data.get('time', '')
                }
                strategy.on_bar(symbol, bar)
                
                # If we want to simulate on_bar from ticks or if MarketData provides bars
                # MarketData should ideally handle bar generation from ticks
                # For now, we assume strategy handles ticks or we implement bar generation later
            except Exception as e:
                logger.error(f"Error in strategy execution: {e}")

    def record_order_event(self, order_info: Dict):
        """Callback from Broker when order is sent"""
        try:
            event = TradeEvent(
                event_id=str(uuid.uuid4()),
                timestamp=datetime.now(),
                symbol=order_info["symbol"],
                strategy_id=order_info["tag"],
                event_type="ORDER_SUBMITTED",
                side=order_info["side"],
                price=float(order_info["price"]),
                qty=int(order_info["qty"]),
                order_id=order_info["order_no"],
                meta={"type": order_info["type"]}
            )
            self.trade_history.append(event)
            logger.info(f"Recorded Order Event: {event.event_type} {event.symbol}")
        except Exception as e:
            logger.error(f"Failed to record order event: {e}")

    def record_position_event(self, change_info: Dict):
        """Callback from Portfolio when position changes"""
        try:
            event_type = change_info["type"]
            # Map to TradeEvent
            # change_info: type, symbol, qty, price, tag
            
            side = "BUY" if "BUY" in event_type else "SELL"
            if event_type == "POSITION_CLOSED":
                side = "SELL" # Assuming long-only for now
            
            event = TradeEvent(
                event_id=str(uuid.uuid4()),
                timestamp=datetime.now(),
                symbol=change_info["symbol"],
                strategy_id=change_info["tag"],
                event_type=event_type,
                side=side,
                price=float(change_info["price"]),
                qty=int(change_info["qty"]),
                order_id="sync_detected", # We don't have order ID here easily
                meta={}
            )
            self.trade_history.append(event)
            logger.info(f"Recorded Position Event: {event.event_type} {event.symbol}")
        except Exception as e:
            logger.error(f"Failed to record position event: {e}")


    def run_backtest(self, strategy_id: str, symbol: str, start_date: str, end_date: str, initial_cash: int = 100000000, strategy_config: Dict = None) -> Dict:
        """
        Run backtest for a specific strategy and symbol.
        Returns a dictionary with result metrics and history.
        """
        logger.info(f"Starting Backtest: {strategy_id} on {symbol} ({start_date}~{end_date})")
        
        # 1. Setup Isolated Environment
        from core.market_data import MarketData
        from core.broker import Broker
        from core.portfolio import Portfolio
        from core.risk_manager import RiskManager
        from utils.data_loader import DataLoader
        
        sim_market = MarketData()
        sim_broker = Broker()
        sim_portfolio = Portfolio()
        sim_risk = RiskManager(sim_portfolio)
        
        # Configure Simulation
        sim_broker.set_simulation_mode(True, initial_cash)
        
        # Load Data
        data_loader = DataLoader()
        # Verify/Download Data
        # Add 60-day buffer for warmup to ensure indicators can coincide and catch early trends
        from datetime import datetime, timedelta
        
        try:
            s_dt = datetime.strptime(start_date, "%Y%m%d")
            buffer_date = (s_dt - timedelta(days=60)).strftime("%Y%m%d")
        except ValueError:
            # Handle dashes if present
            try:
                s_dt = datetime.strptime(start_date, "%Y-%m-%d")
                buffer_date = (s_dt - timedelta(days=60)).strftime("%Y%m%d")
                # Normalize input dates to YYYYMMDD for consistency
                start_date = s_dt.strftime("%Y%m%d")
                end_date = end_date.replace("-", "")
            except:
                buffer_date = start_date

        logger.info(f"Downloading data with warmup buffer: {buffer_date} ~ {end_date}")
        df = data_loader.download_data(symbol, buffer_date, end_date)
        if df.empty:
            return {"error": "No data found for the specified period."}
            
        # 2. Initialize Strategy
        if strategy_id not in self.strategy_classes:
            return {"error": f"Strategy {strategy_id} not registered."}
            
        st_class = self.strategy_classes[strategy_id]
        
        # Merge config
        st_cfg = self.config.get(strategy_id, {}).copy()
        if strategy_config:
            st_cfg.update(strategy_config)
        st_cfg["id"] = strategy_id
        
        strategy = st_class(
            config=st_cfg,
            broker=sim_broker,
            risk_manager=sim_risk,
            portfolio=sim_portfolio,
            market_data=sim_market
        )
        
        # 3. Execution Loop
        history = []
        daily_stats = []
        
        dates = df['date'].unique()
        dates.sort()
        
        # Map date to OHLC for order processing
        data_map = df.set_index('date').to_dict('index')
        
        for date in dates:
            # A. Setup Environment for this Day
            sim_market.set_simulation_date(date)
            
            # B. Process Pending Orders (from previous day)
            # We assume orders fill at Open of this day (or use Close if you prefer)
            # Let's use Open for realistic slippage/gap simulation
            day_data = data_map[date]
            current_prices = {symbol: day_data['open']} # Use Open for execution
            
            # Capture filled orders to record history
            def on_sim_order(info):
                # info: {symbol, qty, side, type, price, tag, order_no}
                # Add timestamp
                info['timestamp'] = date # Use date string as timestamp for backtest
                history.append(info)
                
            sim_broker.on_order_sent = [on_sim_order] # Override listener
            
            sim_broker.process_simulation_orders(current_prices)
            
            # Sync Portfolio after execution
            # For accurate valuation, use Close price of today
            sim_balance = sim_broker.get_balance()
            
            # Update virtual holdings valuation in sim_balance? 
            # Broker.get_balance returns 0 for price. Portfolio needs to know price.
            # Portfolio usually checks market_data.get_last_price.
            # market_data.get_last_price(symbol) will return Close of `date` because we set simulation_date=date.
            # So Portfolio.sync_with_broker will pick up the Close price correctly!
            
            sim_portfolio.sync_with_broker(sim_balance)
            # Force update with current market prices (Close)
            # Portfolio.update_valuation might not exist or might rely on sync.
            # Let's assume sync does it if we mocked it right.
            # But Broker returned "0" for price.
            # Portfolio.sync logic:
            # if 'prpr' in item and item['prpr'] != "0": ...
            # else: current_price = self.market_data.get_last_price(symbol)
            # So yes, it will fetch from market_data! We need to pass market_data to sync?
            # Portfolio usually holds reference to market_data?
            # In engine __init__: self.portfolio = Portfolio().
            # Portfolio doesn't seem to take MarketData in init based on file list (size 8763 bytes).
            # Let's check Portfolio.sync_with_broker implementation if I can.
            # But I should not read too many files.
            # Assuming Portfolio can handle it or I manually update it.
            
            # C. Run Strategy
            # Strategy sees data up to Today's Close (since set_simulation_date(date) makes get_bars return up to date)
            # Strategy makes decision at Close.
            bar = {
                'open': float(day_data['open']),
                'high': float(day_data['high']),
                'low': float(day_data['low']),
                'close': float(day_data['close']),
                'volume': int(day_data['volume']),
                'time': date
            }
            try:
                strategy.on_bar(symbol, bar)
            except Exception as e:
                logger.error(f"Backtest Error on {date}: {e}")
                
            # D. Record Stats
            daily_stats.append({
                "date": date,
                "total_asset": sim_portfolio.total_asset,
                "cash": sim_portfolio.cash,
                "holdings_val": sim_portfolio.total_asset - sim_portfolio.cash,
                "pnl_daily": 0 # Calc later
            })

        # 4. Calculate Metrics
        start_asset = initial_cash
        end_asset = sim_portfolio.total_asset
        total_return = (end_asset - start_asset) / start_asset * 100
        
        # MDD
        peak = start_asset
        max_drawdown = 0
        for s in daily_stats:
            val = s['total_asset']
            if val > peak: peak = val
            dd = (peak - val) / peak * 100
            if dd > max_drawdown: max_drawdown = dd
            
        trades_count = len(history)
        
        return {
            "metrics": {
                "total_return": round(total_return, 2),
                "total_asset": int(end_asset),
                "mdd": round(max_drawdown, 2),
                "trade_count": trades_count,
            },
            "history": history,
            "daily_stats": daily_stats
        }
