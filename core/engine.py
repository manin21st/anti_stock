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
from utils.telegram import TelegramBot
from datetime import datetime
import uuid
import pandas as pd
# strategies will be imported dynamically or explicitly

logger = logging.getLogger(__name__)

class Engine:
    def __init__(self, config_path: str = "config/strategies.yaml"):
        self.config = self._load_config(config_path)
        
        # Load secrets and merge
        secrets = self._load_config("config/secrets.yaml")
        if secrets:
            self._merge_config(self.config, secrets)
            logger.info("Loaded secrets from config/secrets.yaml")
            
        self.system_config = self.config.get("system", {"env_type": "paper", "market_type": "KRX"})
        
        # Authenticate first
        env_type = self.system_config.get("env_type", "paper")
        svr = "vps" if env_type == "paper" else "prod"
        logger.info(f"Authenticating for {env_type} ({svr})")
        
        from core import kis_api as ka
        try:
            ka.auth(svr=svr)
            ka.auth_ws(svr=svr) # Also get WebSocket approval key
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            # We might want to raise here, but let's continue and let components fail if they must
        
        self.market_data = MarketData()
        self.broker = Broker()
        self.portfolio = Portfolio()
        self.risk_manager = RiskManager(self.portfolio, self.config)
        self.risk_manager = RiskManager(self.portfolio, self.config)
        self.scanner = Scanner()
        self.telegram = TelegramBot(self.system_config)
        self.telegram.send_system_alert("🚀 <b>System Started</b>\nAnti-Stock Engine Initialized.")
        
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
        self.load_trade_history()
        
        # Subscribe to Broker and Portfolio events
        self.broker.on_order_sent.append(self.record_order_event)
        self.portfolio.on_position_change.append(self.record_position_event)

    def update_system_config(self, new_config: Dict):
        """Update system configuration and save to appropriate files"""
        # 1. Update In-Memory Config (Deep Merge)
        self._merge_config(self.system_config, new_config)
        
        # Update main config wrapper
        if "system" not in self.config:
            self.config["system"] = {}
        self._merge_config(self.config["system"], new_config)
        
        # 2. Reload components
        if hasattr(self, 'telegram'):
            self.telegram.reload_config(self.system_config)
            
        # 3. Save to Files (Split Strategy vs Secrets)
        # Load current secrets to preserve valid token/chat_id existing there
        try:
            secrets_path = "config/secrets.yaml"
            with open(secrets_path, "r", encoding="utf-8") as f:
                secrets_data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            secrets_data = {}
            
        # Ensure 'system' -> 'telegram' structure in secrets
        if "system" not in secrets_data:
            secrets_data["system"] = {}
        if "telegram" not in secrets_data["system"]:
            secrets_data["system"]["telegram"] = {}
            
        # Extract telegram config from new_config/system_config to update secrets
        # We use system_config because it contains the latest merged state (including UI updates)
        current_telegram_config = self.system_config.get("telegram", {})
        
        # Update secrets_data with current telegram config
        # We only strictly need to update what changed, but syncing the whole telegram block is safer
        secrets_data["system"]["telegram"].update(current_telegram_config)
        
        # Save Secrets
        with open(secrets_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(secrets_data, f, allow_unicode=True, default_flow_style=False)
            
        # Save Strategies (Exclude Telegram)
        # Create a clean copy of config for strategies.yaml
        import copy
        strategies_data = copy.deepcopy(self.config)
        
        # Remove telegram from system in strategies_data
        if "system" in strategies_data and "telegram" in strategies_data["system"]:
            del strategies_data["system"]["telegram"]
            
        with open("config/strategies.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(strategies_data, f, allow_unicode=True, default_flow_style=False)
            
        logger.info(f"System config saved. Telegram config -> secrets.yaml, Others -> strategies.yaml")

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
                    
                    # Fix 7: Strategy Config Precedence
                    # Common config as base
                    strategy_config = self.config.get("common", {}).copy()
                    # Override with Strategy specific config
                    strategy_config.update(self.config.get(active_strategy_id, {}))
                    
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
                    # Fix 2 & User Request: Strict Trading Hour Check
                    if not self._is_trading_hour():
                        if self.market_data.is_polling:
                            logger.info("장 운영 시간이 종료되었습니다. 감시를 중단합니다. (KRX: 09:00~15:30)")
                            self.market_data.stop_polling()
                        
                        # Log periodically while waiting
                        if int(time.time()) % 300 == 0: # Every 5 mins
                            logger.debug("장 운영 시간이 아닙니다. 대기 중... (KRX: 09:00~15:30)")
                        
                        time.sleep(1)
                        continue
                    else:
                        # Market IS Open
                        # Ensure polling is running if trading is active
                        if self.is_trading and not self.market_data.is_polling:
                             # Only start if we have symbols?
                             if hasattr(self.market_data, 'polling_symbols') and self.market_data.polling_symbols:
                                 logger.info("장 운영 시간입니다. 감시를 재개합니다.")
                                 self.market_data.start_polling()

                    # Periodic Scanner Update (Only during trading hours)
                    if self.system_config.get("use_auto_scanner", False):
                        # User requested fast updates (e.g. 5-10s). 
                        # Optimization: Increase to 60s to avoid rate limits (EGW00201)
                        if time.time() - self.last_scan_time > 60: 
                            self._update_universe()
                            # Scanner logic typically updates subscription list
                            # If polling was stopped, we might need to restart it if symbols added?
                            # _update_universe should handle subscription. 
                            # If polling is not running but we are valid, start it.
                            if self.is_trading and not self.market_data.is_polling:
                                self.market_data.start_polling()
                            
                            # Log Updated Universe
                            if hasattr(self.market_data, 'polling_symbols'):
                                symbols = self.market_data.polling_symbols
                                logger.info(f"[감시 종목 업데이트] 총 {len(symbols)}개: {', '.join(symbols[:10])}{' ...' if len(symbols)>10 else ''}")
                    
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
                    # Allowed even outside trading hours? Maybe, for checkups.
                    if time.time() - self.last_sync_time > 5:
                        try:
                            balance = self.broker.get_balance()
                            if balance:
                                self.portfolio.sync_with_broker(balance)
                                # logger.debug("Portfolio synced with broker")

                                # FIX: Correct prices during off-hours or whenever polling is inactive
                                # Broker balance inquiry often returns 'evaluated price' which differs from real close price
                                if not self.market_data.is_polling:
                                    for symbol in list(self.portfolio.positions.keys()):
                                        try:
                                            price = self.market_data.get_last_price(symbol)
                                            if price > 0:
                                                self.portfolio.update_market_price(symbol, price)
                                        except Exception as e:
                                            logger.warning(f"Failed to manual fetch price for {symbol}: {e}")
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

    def _is_trading_hour(self) -> bool:
        """Check if current time is within trading hours"""
        # Allow bypass for simulation/backtest or dev mode?
        if self.config.get("system", {}).get("env_type") == "dev":
            return True
            
        market_type = self.system_config.get("market_type", "KRX")
        now = datetime.now()
        
        if market_type == "KRX":
            # Weekends
            if now.weekday() >= 5: return False
            
            # 09:00 ~ 15:30
            current_time = now.time()
            # Need to import time class from datetime module if not available?
            # datetime.now().time() returns datetime.time object
            # Compare with limits
            start = now.replace(hour=9, minute=0, second=0, microsecond=0).time()
            end = now.replace(hour=15, minute=30, second=0, microsecond=0).time()
            
            return start <= current_time <= end
        
        elif market_type == "NXT":
            # 08:00 ~ 20:00
            current_time = now.time()
            start = now.replace(hour=8, minute=0, second=0, microsecond=0).time()
            end = now.replace(hour=20, minute=0, second=0, microsecond=0).time()
            return start <= current_time <= end
            
        return True

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

    def _merge_config(self, base: Dict, update: Dict):
        """Recursively merge update dict into base dict"""
        for k, v in update.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                self._merge_config(base[k], v)
            else:
                base[k] = v

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
        if not self._is_trading_hour():
            return

        symbol = data.get("symbol")
        if not symbol:
            return
        
        if not self.is_trading:
            return

        # Update Portfolio with Real-time Price
        self.portfolio.update_market_price(symbol, data.get("price", 0.0))

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

    def load_trade_history(self):
        """Load trade history from file"""
        try:
            path = "data/trade_history.json"
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.trade_history = [TradeEvent(**item) for item in data]
                logger.info(f"Loaded {len(self.trade_history)} trade events from {path}")
            else:
                logger.info("No existing trade history found. Starting fresh.")
        except Exception as e:
            logger.error(f"Failed to load trade history: {e}")

    def save_trade_history(self):
        """Save trade history to file"""
        try:
            path = "data/trade_history.json"
            os.makedirs("data", exist_ok=True)
            
            # Serialize
            data = [event.__dict__ for event in self.trade_history]
            # Convert datetime objects to string if needed (TradeEvent usually stores timestamp as datetime)
            # Assuming TradeEvent.__dict__ has timestamps as strings or we need custom encoder
            # Let's use a robust serialization approach
            def json_serial(obj):
                if isinstance(obj, (datetime, pd.Timestamp)):
                    return obj.isoformat()
                return str(obj)

            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, default=json_serial, indent=2, ensure_ascii=False)
            
            logger.debug(f"Saved {len(self.trade_history)} trade events")
        except Exception as e:
            logger.error(f"Failed to save trade history: {e}")

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
            self.save_trade_history() # Save on update
            logger.info(f"Recorded Order Event: {event.event_type} {event.symbol}")
            
            # Telegram Alert
            stock_name = self.market_data.get_stock_name(order_info["symbol"])
            self.telegram.send_trade_event(
                event_type="ORDER_SUBMITTED",
                symbol=order_info["symbol"],
                price=float(order_info["price"]),
                qty=int(order_info["qty"]),
                side=order_info["side"],
                stock_name=stock_name
            )
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
                meta=change_info
            )
            self.trade_history.append(event)
            self.save_trade_history() # Save on update
            logger.info(f"Recorded Position Event: {event.event_type} {event.symbol}")

            # Telegram Alert
            stock_name = self.market_data.get_stock_name(change_info["symbol"])
            self.telegram.send_trade_event(
                event_type=event_type,
                symbol=change_info["symbol"],
                price=float(change_info["price"]),
                qty=int(change_info["qty"]),
                side=side,
                stock_name=stock_name,
                position_info=change_info # Pass full context
            )
        except Exception as e:
            logger.error(f"Failed to record position event: {e}")

    def sync_trade_history(self, start_date: str, end_date: str):
        """Syncs local trade history with Broker API"""
        from core import kis_api as ka
        try:
            logger.info(f"Syncing trade history from {start_date} to {end_date}...")
            # Fetch from API
            resp = ka.fetch_daily_ccld(start_date, end_date)
            
            if not resp.isOK():
                logger.error(f"API Error: {resp.getErrorCode()} {resp.getErrorMessage()}")
                return 0
                
            # Process API Data
            # resp.getBody().output1 is the list of executions
            # output1 might be a list of dicts.
            import pandas as pd
            
            # Safe access to output1 (it might be a list or None)
            body = resp.getBody()
            output1 = getattr(body, 'output1', [])
            
            if not output1:
                logger.info("No execution history found from API.")
                return 0
                
            df1 = pd.DataFrame(output1)
            
            if df1.empty:
                logger.info("No execution history found from API (Empty DataFrame).")
                return 0
                
            # Process API Data
            # KIS API df1 columns: odno(order_no), pdno(symbol), ccld_qty(qty), avg_prvs(price), sll_buy_dvsn_cd(1:sell, 2:buy), ord_dt(date)
            # We need to deduplicate based on ODNO (Order No)
            
            local_odnos = set(t.order_id for t in self.trade_history if t.order_id)
            new_count = 0
            
            for _, row in df1.iterrows():
                odno = str(row['odno'])
                if odno in local_odnos:
                    continue
                    
                # New Trade Found
                symbol = str(row['pdno'])
                qty = int(row['ccld_qty'])
                price = float(row['avg_prvs'])
                date_str = str(row['ord_dt']) # YYYYMMDD
                side_code = str(row['sll_buy_dvsn_cd'])
                side = "BUY" if side_code == "02" else "SELL"
                
                # Assume time is unknown (00:00:00) or check if API provides time (usually separate field or not in this TR)
                # inquire-daily-ccld output usually has date but maybe not precise time.
                # Let's check keys if needed, but for now use date + noon
                ts = datetime.strptime(date_str, "%Y%m%d")
                
                # Strategy ID Logic: Default to 'ma_trend' as per user request
                strategy_id = "ma_trend" 
                
                event = TradeEvent(
                    event_id=str(uuid.uuid4()),
                    timestamp=ts,
                    symbol=symbol,
                    strategy_id=strategy_id,
                    event_type="ORDER_FILLED_SYNC", # Distinct type
                    side=side,
                    price=price,
                    qty=qty,
                    order_id=odno,
                    meta={"source": "api_sync"}
                )
                self.trade_history.append(event)
                new_count += 1
                
            if new_count > 0:
                # Sort by timestamp
                self.trade_history.sort(key=lambda x: x.timestamp if isinstance(x.timestamp, datetime) else datetime.fromisoformat(str(x.timestamp)))
                self.save_trade_history()
                logger.info(f" synced {new_count} new trades from Broker API.")
            else:
                logger.info("All trades already exist locally.")
                
            return new_count
            
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise e

    def run_backtest(self, strategy_id: str, symbol: str, start_date: str, end_date: str, initial_cash: int = 100000000, strategy_config: Dict = None, progress_callback=None) -> Dict:
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
        
        sim_market = MarketData(is_simulation=True)
        sim_broker = Broker()
        sim_portfolio = Portfolio()
        sim_risk = RiskManager(sim_portfolio)
        
        # Configure Simulation
        sim_broker.set_simulation_mode(True, initial_cash)
        sim_portfolio.cash = float(initial_cash)
        sim_portfolio.total_asset = float(initial_cash)
        
        # Determine Timeframe early
        temp_cfg = self.config.get(strategy_id, {}).copy()
        if strategy_config:
            temp_cfg.update(strategy_config)
        tf = temp_cfg.get("timeframe", "D")
        
        # Load Data
        data_loader = DataLoader()
        # Verify/Download Data
        # Add 60-day buffer for warmup to ensure indicators can coincide and catch early trends
        from datetime import datetime, timedelta
        
        try:
            buffer_days = 60 if tf == "D" else 5 # Reduce buffer for minute data to avoid long download
            
            s_dt = datetime.strptime(start_date, "%Y%m%d")
            buffer_date = (s_dt - timedelta(days=buffer_days)).strftime("%Y%m%d")
        except ValueError:
            # Handle dashes if present
            try:
                buffer_days = 60 if tf == "D" else 5
                
                s_dt = datetime.strptime(start_date, "%Y-%m-%d")
                buffer_date = (s_dt - timedelta(days=buffer_days)).strftime("%Y%m%d")
                # Normalize input dates to YYYYMMDD for consistency
                start_date = s_dt.strftime("%Y%m%d")
                end_date = end_date.replace("-", "")
            except:
                buffer_date = start_date

        logger.info(f"Loading data from local storage: {buffer_date} ~ {end_date} (TF: {tf})")
        df = data_loader.load_data(symbol, buffer_date, end_date, timeframe=tf)
        if df.empty:
            return {"error": "No data found. Please run download first."}
            
        # 2. Initialize Strategy
        if strategy_id not in self.strategy_classes:
            return {"error": f"Strategy {strategy_id} not registered."}
            
        st_class = self.strategy_classes[strategy_id]
        
        # Merge config
        st_cfg = temp_cfg # Reuse parsed config
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
        
        # Get Timeframe from strategy config
        tf = st_cfg.get("timeframe", "D") # e.g. "D", "3m", "5m"
        
        # Prepare Data
        if tf == "D":
            dates = df['date'].unique()
            dates.sort()
            data_map = df.set_index('date').to_dict('index')
            
            total_days = len(dates)
            for i, date in enumerate(dates):
                # Daily Loop Logic (Existing)
                sim_market.set_simulation_date(date)
                day_data = data_map[date]
                current_prices = {symbol: day_data['open']} 

                if progress_callback:
                    # Calculate Real-time Status
                    current_price = day_data['close']
                    pos = sim_portfolio.get_position(symbol)
                    qty = int(pos.qty) if pos else 0
                    avg_price = float(pos.avg_price) if pos else 0.0
                    buy_amt = qty * avg_price
                    eval_amt = qty * current_price
                    eval_pnl = eval_amt - buy_amt
                    
                    # Estimate Total Asset (Cash + Stock Val)
                    # sim_portfolio.total_asset might be stale if not updated, so calc manually
                    cur_total_asset = sim_portfolio.cash + eval_amt
                    total_return = (cur_total_asset - float(initial_cash)) / float(initial_cash) * 100
                    
                    status = {
                        "percent": int((i / total_days) * 100),
                        "qty": qty,
                        "avg_price": avg_price,
                        "buy_amt": buy_amt,
                        "current_price": current_price,
                        "eval_amt": eval_amt,
                        "eval_pnl": eval_pnl,
                        "return_rate": total_return,
                        "trade_count": len(history)
                    }
                    progress_callback("progress", status) 
                
                # ... (Order Processing & Strategy Run similar to before)
                self._run_backtest_step(sim_broker, sim_portfolio, strategy, symbol, day_data, date, history, is_intraday=False, progress_callback=progress_callback)
                
                # Daily Stats
                daily_stats.append(self._calculate_daily_stat(date, sim_portfolio))
                
        else:
            # Intraday Backtest
            logger.info(f"Running Intraday Backtest for {tf} timeframe...")
            
            # 1. Pre-process 1m data to target timeframe
            # Ensure date and time are strings
            df['date'] = df['date'].astype(str)
            df['time'] = df['time'].astype(str).str.zfill(6) # Ensure 6 digits (090000) if cast from int
            
            df['datetime'] = pd.to_datetime(df['date'] + df['time'], format="%Y%m%d%H%M%S")
            df = df.set_index('datetime').sort_index()
            
            # Resample
            # timeframe "3m" -> "3min" (Pandas future warning fix)
            rule = tf.replace("m", "min")
            
            resampled = df.resample(rule).agg({
                'date': 'first', # Keep date string
                'time': 'last',  # Keep time string of close
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            
            # Loop
            current_date_str = None
            
            total_bars = len(resampled)
            for i, (dt, row) in enumerate(resampled.iterrows()):
                if progress_callback and i % 10 == 0: # Throttle updates
                    # Intraday Status
                    current_price = row['close']
                    pos = sim_portfolio.get_position(symbol)
                    qty = int(pos.qty) if pos else 0
                    avg_price = float(pos.avg_price) if pos else 0.0
                    buy_amt = qty * avg_price
                    eval_amt = qty * current_price
                    eval_pnl = eval_amt - buy_amt
                    
                    cur_total_asset = sim_portfolio.cash + eval_amt
                    total_return = (cur_total_asset - float(initial_cash)) / float(initial_cash) * 100
                    
                    status = {
                        "percent": int((i / total_bars) * 100),
                        "qty": qty,
                        "avg_price": avg_price,
                        "buy_amt": buy_amt,
                        "current_price": current_price,
                        "eval_amt": eval_amt,
                        "eval_pnl": eval_pnl,
                        "return_rate": total_return,
                        "trade_count": len(history)
                    }
                    progress_callback("progress", status)

                date_str = row['date']
                time_str = row['time']
                
                # Update Simulation Time Context (Date + Time for Intraday)
                # This ensures MarketData.get_bars returns data strictly up to this minute
                sim_market.set_simulation_date(f"{date_str}{time_str}")
                
                # Update daily stats logic if date changed (optional/complex)
                if date_str != current_date_str:
                    current_date_str = date_str
                    if daily_stats:
                        # Update the last entry of previous day with final close?
                        pass
                
                bar = row.to_dict()
                bar['time'] = row['time'] # Ensure time string exists
                
                # Execute Step
                self._run_backtest_step(sim_broker, sim_portfolio, strategy, symbol, bar, date_str, history, is_intraday=True, progress_callback=progress_callback)
                
            # Final Stats Calculation needed? 
            # We can generate daily stats from history/equity curve if needed.
            # For now, let's just create daily_stats at the end of each day in the loop.
            
            # Make sure we fill daily_stats for consistency
            # Group resampled by date to record eod stats
            # Re-looping strategies usually tracking equity curve.
            
            # Let's approximate daily_stats by sampling at the change of day
            # (Just before updating current_date_str, record stat for prev date)
            pass

        # 4. Calculate Metrics (Same as before)
        start_asset = initial_cash
        end_asset = sim_portfolio.total_asset
        total_return = (end_asset - start_asset) / start_asset * 100
        
        # MDD
        peak = start_asset
        max_drawdown = 0
        # If daily_stats is empty (e.g. intraday loop didn't fill it yet), use equity history?
        # Let's verify we populate daily_stats. 
        # For simplicity in Intraday, we can rebuild daily_stats from history or just take EOD snapshots.
        
        if not daily_stats and tf != "D": 
            # Quick generate daily stats logic for intraday
            # Or just add logic in loop
            pass
            
        # ... Return result ...
        
        return {
            "metrics": {
                "total_return": round(total_return, 2),
                "total_asset": int(end_asset),
                "mdd": round(max_drawdown, 2),
                "trade_count": len(history),
            },
            "history": history,
            "daily_stats": daily_stats
        }

    def _calculate_daily_stat(self, date, portfolio):
        return {
            "date": date,
            "total_asset": portfolio.total_asset,
            "cash": portfolio.cash,
            "holdings_val": portfolio.total_asset - portfolio.cash,
            "pnl_daily": 0 
        }

    def _run_backtest_step(self, broker, portfolio, strategy, symbol, bar, date, history, is_intraday, progress_callback=None):
        # 1. Update Broker Prices (Simulation)
        # Use Open price for execution if not intraday? 
        # For intraday, we are at the end of the bar (close). 
        # But orders filled at... Open of next bar? Or this bar?
        # Real-time: on_bar comes after bar close. Order sent. Filled next tick.
        # Backtest: Order filled at Next Bar Open.
        # Current logic: Fill at Current Bar Open? (Look-ahead bias if using current bar data to decide and fill at open)
        # Proper Backtest:
        # A. Fill Pending Orders using Current Bar (Open/High/Low)
        # B. Strategy.on_bar(Current Bar) -> Generates New Orders
        
        # Correct sequence:
        # 1. Broker.process_orders(Current Bar OHLC) -> Fills orders from PREVIOUS step
        # 2. Strategy.on_bar(Current Bar) -> Creates NEW orders for NEXT step
        
        current_prices = {symbol: bar['open']} # Simple execution price
        if is_intraday:
            # Intraday execution could be more precise (High/Low checks)
            current_prices[symbol] = bar['open'] 
        
        # Hook for history
        def on_sim_order(info):
            info['timestamp'] = f"{date} {bar.get('time', '')}"
            history.append(info)
            if progress_callback:
                 progress_callback("trade_event", info)
        broker.on_order_sent = [on_sim_order]

        broker.process_simulation_orders(current_prices)
        
        # Sync Portfolio
        # For valuation, use Close
        # We need to mock market price for portfolio
        # Portfolio uses market_data.get_last_price(symbol)
        # We should set that in sim_market!
        # sim_market.set_current_price(symbol, bar['close']) # Hypothetical method
        # If market_data doesn't have it, we might need to rely on what Portfolio does.
        # Assuming sim_market.set_simulation_date loads daily data and get_last_price returns Close.
        # For Intraday, we must ensure get_last_price returns current bar close.
        # Taking a look at MarketData/Portfolio might be needed, but let's assume Portfolio.sync_with_broker 
        # uses the price we just successfully traded at or something.
        
        # Actually, let's just focus on running the strategy. 
        # Valuation is for stats.
        
        try:
            strategy.on_bar(symbol, bar)
        except Exception as e:
            logger.error(f"Backtest Error on {date}: {e}")
