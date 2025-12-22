import logging
import time
import threading
from typing import Dict, List
import sys
import os
import yaml
import json

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.market_data import MarketData
from core.broker import Broker
from core.portfolio import Portfolio
from core.risk_manager import RiskManager
from core.scanner import Scanner
from core.visualization import TradeEvent
from core.dao import TradeDAO, WatchlistDAO
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
            logger.debug("Loaded secrets from config/secrets.yaml")
            
        self.system_config = self.config.get("system", {"env_type": "paper", "market_type": "KRX"})
        
        # Authenticate first
        env_type = self.system_config.get("env_type", "paper")
        svr = "vps" if env_type == "paper" else "prod"
        logger.debug(f"Authenticating for {env_type} ({svr})")
        
        from core import kis_api as ka
        try:

            # Apply TPS Config (Limit & URL)
            tps_limit = float(self.system_config.get("tps_limit", os.environ.get("TPS_LIMIT", 2.0)))
            tps_url = self.system_config.get("tps_server_url", os.environ.get("TPS_SERVER_URL", "http://localhost:9000"))
            
            if hasattr(ka, 'rate_limiter') and ka.rate_limiter:
                ka.rate_limiter.set_limit(tps_limit)
                ka.rate_limiter.set_server_url(tps_url)

            ka.auth(svr=svr)
            ka.auth_ws(svr=svr) # Also get WebSocket approval key
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            # We might want to raise here, but let's continue and let components fail if they must
        
        self.market_data = MarketData()
        self.broker = Broker()
        self.portfolio = Portfolio()
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
        self._last_wait_log_time = 0
        
        # Subscribe to market data events
        self.market_data.subscribers.append(self.on_market_data)
        
        # Trade History
        self.trade_history: List[TradeEvent] = []
        self.load_trade_history()
        
        # Subscribe to Broker and Portfolio events
        self.broker.on_order_sent.append(self.record_order_event)
        self.portfolio.on_position_change.append(self.record_position_event)

        # Watchlist Management
        self.watchlist = []
        self._load_watchlist() 
        # Database Warm-up
        self._warmup_db()

    def _warmup_db(self):
        """Force DB connection establishment to avoid lazy loading delay on first UI request"""
        try:
            logger.debug("Warming up Database Connection...")
            from core.database import db_manager
            
            # Simple connection check
            db_manager.get_session().close()
            
            # Real query to warm up table/cache
            count = TradeDAO.get_all_trades_count()
            logger.debug(f"Database Connection Ready. (Trades in DB: {count})")
        except Exception as e:
            logger.warning(f"Database Warm-up failed (will retry on demand): {e}")

    def _load_watchlist(self):
        """Load watchlist from Database"""
        try:
            self.watchlist = WatchlistDAO.get_all_symbols()
            logger.debug(f"Loaded Watchlist: {len(self.watchlist)} items from Database")
        except Exception as e:
            logger.error(f"Failed to load watchlist: {e}")
            self.watchlist = []


    def _save_watchlist(self):
        """Save watchlist (Deprecated for DB)"""
        pass


    def _migrate_legacy_universe(self):
        """Migrate legacy 'universe' config to watchlist.json"""
        legacy_universe = self.system_config.get("universe", [])
        if legacy_universe:
            logger.info(f"Migrating legacy universe ({len(legacy_universe)} items) to Watchlist...")
            
            current_set = set(self.watchlist)
            for code in legacy_universe:
                current_set.add(str(code).zfill(6))
            
            self.watchlist = list(current_set)
            
            # DB Sync
            for s in self.watchlist:
                WatchlistDAO.add_symbol(s)
                
            # Clear legacy config

            self.update_system_config({"universe": []})
            logger.info("Legacy universe migration completed.")

    def import_broker_watchlist(self):
        """Import watchlist from Broker (HTS Groups)"""
        try:
            logger.info("Importing Broker Watchlist...")
            imported = self.scanner.get_watchlist() # Fetches from API
            if imported:
                current_set = set(self.watchlist)
                count_before = len(current_set)
                for code in imported:
                    current_set.add(str(code).zfill(6))
                
                self.watchlist = list(current_set)
                
                from core.dao import WatchlistDAO
                for s in self.watchlist:
                    WatchlistDAO.add_symbol(s)

                
                added = len(current_set) - count_before
                logger.info(f"Imported {len(imported)} items from Broker. (New: {added})")
                return len(imported), added
            return 0, 0
        except Exception as e:
            logger.error(f"Failed to import broker watchlist: {e}")
            raise e

    def update_watchlist(self, new_list: List[str]):
        """Update entire watchlist"""
        self.watchlist = [str(x).zfill(6) for x in new_list]
        
        # DB Sync (Full Replace)
        from core.dao import WatchlistDAO
        current_db = set(WatchlistDAO.get_all_symbols())
        new_set = set(self.watchlist)
        
        to_add = new_set - current_db
        to_remove = current_db - new_set
        
        for s in to_add:
            WatchlistDAO.add_symbol(s)
        for s in to_remove:
            WatchlistDAO.remove_symbol(s)

        # Trigger subscription update immediately
        self._update_universe()
        # If trading is active, ensure polling is updated
        if self.is_trading and not self.market_data.is_polling:
             self.market_data.start_polling()

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
            
        # Apply TPS Config Dynamic Update
        try:
            from core import kis_api as ka
            if hasattr(ka, 'rate_limiter') and ka.rate_limiter:
                if "tps_limit" in new_config:
                    ka.rate_limiter.set_limit(float(new_config["tps_limit"]))
                if "tps_server_url" in new_config:
                    ka.rate_limiter.set_server_url(new_config["tps_server_url"])
        except Exception as e:
            logger.error(f"Failed to update TPS dynamic config: {e}")
            
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
        
        # Update TPS Limit on Restart
        try:
            from core import kis_api as ka
            tps_limit = float(self.system_config.get("tps_limit", os.environ.get("TPS_LIMIT", 2.0)))
            tps_url = self.system_config.get("tps_server_url", os.environ.get("TPS_SERVER_URL", "http://localhost:9000"))
            
            if hasattr(ka, 'rate_limiter') and ka.rate_limiter:
                ka.rate_limiter.set_limit(tps_limit)
                ka.rate_limiter.set_server_url(tps_url)
        except Exception as e:
            logger.error(f"Failed to update TPS Config on restart: {e}")

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
                    logger.debug(f"DEBUG: Re-authenticating for {env_type} ({svr})")
                    ka.auth(svr=svr)
                
                # Re-instantiate strategies with fresh config
                self.strategies.clear()
                
                active_strategy_id = self.config.get("active_strategy")
                logger.debug(f"Active strategy ID: {active_strategy_id}")
                
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
                    logger.debug(f"Initialized active strategy: {active_strategy_id}")
                else:
                    logger.warning(f"Strategy not found: {active_strategy_id}")
                
                # [OPTIMIZATION] Offload heavy initialization to background thread
                # This prevents blocking the Main Thread (GIL) for too long, allowing Web Server to respond instantly.
                def _async_init_tasks():
                    try:
                        logger.debug("Running background initialization tasks...")
                        # 1. Sync initial portfolio state
                        balance = self.broker.get_balance()
                        if balance:
                            self.portfolio.sync_with_broker(balance, notify=False, tag_lookup_fn=self._resolve_strategy_tag)
                            self.portfolio.load_state()
                            total_asset = int(self.portfolio.total_asset)
                            cash = int(self.portfolio.cash)
                            logger.debug(f"[Init] Portfolio Synced: Asset {total_asset:,} / Cash {cash:,}")
                        else:
                            logger.error("[Init] Failed to fetch broker balance")

                        # 2. Cache Watchlist
                        target_group = self.system_config.get("watchlist_group_code", "000")
                        logger.debug(f"Fetching Watchlist (Group {target_group}) for caching...")
                        try:
                            self.cached_watchlist = self.scanner.get_watchlist(target_group_code=target_group)
                            logger.debug(f"Cached Watchlist: {len(self.cached_watchlist)} stocks")
                        except Exception as e:
                            logger.error(f"Failed to cache watchlist: {e}")
                            self.cached_watchlist = []

                        # 3. Initial Universe Scan (Only if Market is Open)
                        if self._is_trading_hour():
                            self._update_universe()
                            
                            # Log Initial Universe
                            if hasattr(self.market_data, 'polling_symbols'):
                                 symbols = self.market_data.polling_symbols
                                 logger.info(f"[Init] Monitoring {len(symbols)} symbols: {', '.join(symbols[:10])}...")
                        else:
                            logger.info(f"[Init] Watchlist Loaded from DB ({len(self.watchlist if self.watchlist else [])} items). (Market Closed - Auto-Scanner Skipped)")
                             
                    except Exception as e:
                        logger.error(f"Background Initialization Failed: {e}")
                        import traceback
                        logger.error(traceback.format_exc())

                # Start Init Thread
                threading.Thread(target=_async_init_tasks, daemon=True).start()

            except Exception as e:
                logger.error(f"초기화 실패: {e}")
                import traceback
                logger.error(traceback.format_exc())

            except Exception as e:
                logger.error(f"초기화 실패: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
            # Start MarketData Polling (REST API)
            # ws_thread = threading.Thread(target=self.market_data.start_ws, daemon=True)
            # ws_thread.start()
            # self.market_data.start_polling() # MOVED: Triggered inside loop if trading hour
            
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
                            self._last_wait_log_time = int(time.time()) # Mark as logged (suppress "Waiting" log)
                        
                        # Log only ONCE (First time entering wait state)
                        if self._last_wait_log_time == 0:
                             logger.info("장 운영 시간이 아닙니다. 대기 중... (KRX: 09:00~15:30)")
                             self._last_wait_log_time = int(time.time())
                        
                        time.sleep(1)
                        continue
                    else:
                        # Market IS Open
                        # Reset wait log flag so we notify next time market closes
                        if self._last_wait_log_time != 0:
                             self._last_wait_log_time = 0

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
                                # [Fix] Pass lookup function
                                self.portfolio.sync_with_broker(balance, notify=True, tag_lookup_fn=self._resolve_strategy_tag)
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
                # Use Cached Watchlist (HTS) only if UI Watchlist is empty
                api_watchlist = getattr(self, 'cached_watchlist', [])
                
                # Determine the Authority List
                if self.watchlist:
                    # User has defined a list in UI -> This is the FINAL list
                    full_watchlist = set(self.watchlist)
                    # logger.info(f"Using UI Watchlist as Filter: {len(full_watchlist)} items")
                else:
                    # Fallback to Broker Group if UI list is empty
                    full_watchlist = set(api_watchlist)
                    # logger.info(f"Using Broker Group as Filter: {len(full_watchlist)} items")
                
                watchlist = list(full_watchlist)
                
                if watchlist:
                    # Normalize watchlist
                    watchlist = [str(x).zfill(6) for x in watchlist]
                    # Intersection
                    universe = [s for s in scanned_symbols if s in watchlist]
                    logger.info(f"Filtered by Watchlist: {len(universe)} stocks selected {universe}")
                else:
                    logger.warning("Auto-Scanner is on, but Watchlist is empty. No stocks selected.")
                    universe = []

            except Exception as e:
                logger.error(f"Scanner failed: {e}")
                universe = []
        else:
            # universe = self.system_config.get("universe", []) # Legacy
            universe = self.watchlist # Use New Watchlist as Manual Universe
            logger.info(f"Using manual universe (Watchlist): {universe}")
            
        # Combine Universe + Current Holdings + WATCHLIST for subscription
        # New Rule: We ALWAYS subscribe to Watchlist items to show them in the UI tab,
        # even if they are not selected for 'Trading Universe' by the scanner.
        subscription_list = set(universe) if universe else set()
        
        # Add Watchlist (for UI monitoring)
        if self.watchlist:
            subscription_list.update(self.watchlist)
        
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

    def _resolve_strategy_tag(self, symbol: str) -> str:
        """Helper to find the last strategy that traded this symbol from history"""
        for event in reversed(self.trade_history):
            if event.symbol == symbol and event.event_type == "ORDER_SUBMITTED":
                 return event.strategy_id
        return ""

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
        """Load trade history from Database"""
        try:
            from core.dao import TradeDAO
            from core.visualization import TradeEvent
            trades = TradeDAO.get_trades(limit=1000)
            
            # Convert SQLAlchemy Models to TradeEvent objects for consistent memory usage
            self.trade_history = []
            for t in trades:
                self.trade_history.append(TradeEvent(
                    event_id=t.event_id,
                    timestamp=t.timestamp,
                    symbol=t.symbol,
                    strategy_id=t.strategy_id,
                    event_type="DB_LOADED", # Or infer from meta
                    side=t.side,
                    price=t.price,
                    qty=t.qty,
                    exec_amt=t.exec_amt if t.exec_amt else (t.price * t.qty),
                    order_id=t.order_id,
                    pnl=t.pnl,
                    pnl_pct=t.pnl_pct,
                    meta=t.meta
                ))
            logger.debug(f"Loaded {len(self.trade_history)} recent trade events from Database")
        except Exception as e:
            logger.error(f"Failed to load trade history: {e}")


    def save_trade_history(self):
        """Save trade history (Deprecated for DB)"""
        # With DB, we save incrementally. This method might be kept for compatibility or bulk save if needed.
        # For now, PASS as individual updates handle persistence.
        pass


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
                meta={"type": order_info["type"], "event_type": "ORDER_SUBMITTED"}
            )
            # self.trade_history.append(event) # Optional: Keep in memory? Yes.
            
            # DB Insert
            # DB Insert
            TradeDAO.insert_trade({
                "event_id": event.event_id,
                "timestamp": event.timestamp,
                "symbol": event.symbol,
                "strategy_id": event.strategy_id,
                "side": event.side,
                "price": event.price,
                "qty": event.qty,
                "exec_amt": event.price * event.qty,
                "order_id": event.order_id,
                "meta": event.meta
            })
            # Reload memory to sync? Or just append. 
            self.trade_history.insert(0, event) # Prepend for recent
            
            logger.info(f"Recorded Order Event: {event.event_type} {event.symbol}")
            
            # Telegram Alert Removed: Duplicate notification. 
            # "Order Submitted" is not "Execution". 
            # True execution alert is handled by 'record_position_event'.
        except Exception as e:
            logger.error(f"Failed to record order event: {e}")

    def record_position_event(self, change_info: Dict):
        """Callback from Portfolio when position changes (Fills)"""
        try:
            event_type = change_info["type"]
            # Map to TradeEvent
            # change_info: type, symbol, qty, price, tag, exec_qty, exec_price, old_avg_price...
            
            side = "BUY" if "BUY" in event_type else "SELL"
            if event_type == "POSITION_CLOSED":
                side = "SELL" # Position Closed is a valid SELL event
            
            # [FIX] Filter out invalid events with 0 price
            if float(change_info["price"]) <= 0:
                return

            # XPnL Calculation (Client-side)
            pnl = None
            pnl_pct = None
            
            if side == "SELL":
                exec_qty = change_info.get("exec_qty", 0)
                exec_price = change_info.get("exec_price", 0)
                old_avg_price = change_info.get("old_avg_price", 0)
                
                if exec_qty > 0 and old_avg_price > 0:
                    # Fee Calculation (Conservative: 0.25%)
                    # Tax/Fee = Total Sell Amount * 0.0025
                    total_sell_amt = exec_price * exec_qty
                    fees = total_sell_amt * 0.0025
                    
                    gross_pnl = (exec_price - old_avg_price) * exec_qty
                    net_pnl = gross_pnl - fees
                    
                    pnl = round(net_pnl, 0)
                    pnl_pct = round(((exec_price - old_avg_price) / old_avg_price) * 100, 2)
                    
                    logger.info(f"[PnL Calculated] {change_info['symbol']} PnL: {pnl} ({pnl_pct}%) [Avg: {old_avg_price} -> Sell: {exec_price}]")
            
            # [NEW] Ensure meta has fees and old_avg_price
            if "meta" not in change_info:
                change_info["meta"] = {}
            if side == "SELL":
                # If calculated above
                if pnl is not None:
                     change_info["fees"] = round(fees, 0) if 'fees' in locals() else 0
                     change_info["old_avg_price"] = round(old_avg_price, 2) if 'old_avg_price' in locals() else 0

            # Create TradeEvent for the Fill
            event = TradeEvent(
                event_id=str(uuid.uuid4()),
                timestamp=datetime.now(),
                symbol=change_info["symbol"],
                strategy_id=change_info.get("tag", ""),
                event_type=event_type,
                side=side,
                price=float(change_info["price"]),
                qty=int(change_info["qty"]), # Remaining Qty or Exec Qty? 
                # change_info['qty'] in portfolio.py comes from 'qty' (current position qty).
                # We want Execution Qty for the log.
                # Portfolio sends 'exec_qty' in enhanced data.
                order_id=f"fill_{int(time.time()*1000)}", # Virtual Order ID since we don't have exact ODNO here easily
                pnl=pnl,
                pnl_pct=pnl_pct,
                meta=change_info # Store full context
            )
            
            # Use 'exec_qty' if available for accurate trade record, otherwise diff
            if "exec_qty" in change_info:
                event.qty = change_info["exec_qty"]

            self.trade_history.insert(0, event) # Prepend
            
            # DB Insert
            TradeDAO.insert_trade({
                "event_id": event.event_id,
                "timestamp": event.timestamp,
                "symbol": event.symbol,
                "strategy_id": event.strategy_id,
                "side": event.side,
                "price": event.price,
                "qty": event.qty,
                "exec_amt": event.price * event.qty,
                "pnl": event.pnl,
                "pnl_pct": event.pnl_pct,
                "order_id": event.order_id,
                "meta": event.meta
            })

            logger.info(f"Recorded Position Event: {event.event_type} {event.symbol} (PnL: {pnl})")

            # Telegram Alert
            stock_name = self.market_data.get_stock_name(change_info["symbol"])
            self.telegram.send_trade_event(
                event_type=event_type,
                symbol=change_info["symbol"],
                price=float(change_info["price"]),
                qty=int(event.qty),
                side=side,
                stock_name=stock_name,
                position_info=change_info
            )
        except Exception as e:
            logger.error(f"Failed to record position event: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def sync_trade_history(self, start_date: str, end_date: str):
        """Syncs local trade history with Broker API"""
        from core import kis_api as ka
        import time
        try:
            logger.info(f"Syncing trade history from {start_date} to {end_date}...")
            
            all_trades = []
            ctx_area_fk = ""
            ctx_area_nk = ""
            prev_nk = ""
            
            page_count = 0
            empty_page_count = 0
            MAX_PAGES = 200 # Safety limit
            
            while True:
                page_count += 1
                if page_count > MAX_PAGES:
                    logger.warning(f"Reached MAX_PAGES ({MAX_PAGES}) limit. Stopping sync.")
                    break

                # Fetch from API
                resp = ka.fetch_daily_ccld(start_date, end_date, ctx_area_fk=ctx_area_fk, ctx_area_nk=ctx_area_nk)
                
                if not resp.isOK():
                    logger.error(f"API Error: {resp.getErrorCode()} {resp.getErrorMessage()}")
                    break
                    
                # Process API Data
                body = resp.getBody()
                
                # Helper to get attribute case-insensitively
                def get_attr_case_insensitive(obj, attr_name, default=None):
                    # If obj is namedtuple or object, dir(obj) helps, but _fields is better for namedtuple
                    if hasattr(obj, '_fields'):
                        for field in obj._fields:
                            if field.lower() == attr_name.lower():
                                return getattr(obj, field)
                    # If it's a dict (fallback for body dict)
                    elif isinstance(obj, dict):
                         for key in obj.keys():
                             if key.lower() == attr_name.lower():
                                 return obj[key]
                    return default

                output1 = get_attr_case_insensitive(body, 'output1', [])
                
                if output1:
                    all_trades.extend(output1)
                    empty_page_count = 0
                else:
                    empty_page_count += 1
                    
                if empty_page_count >= 5:
                    logger.warning("Too many consecutive empty pages with next token. Stopping sync.")
                    break
                
            # Check Pagination
                # ctx_area_nk100 might be in body or header. 
                # Let's inspect body keys for debugging first
                # if not ctx_area_nk:
                #      body_keys = getattr(body, '_fields', [])
                #      logger.debug(f"[DEBUG] Body Keys: {body_keys}")
                
                ctx_area_nk = get_attr_case_insensitive(body, 'ctx_area_nk100', "").strip()
                ctx_area_fk = get_attr_case_insensitive(body, 'ctx_area_fk100', "").strip()
                
                logger.info(f"[DEBUG] Pagination: fk=[{ctx_area_fk}], nk=[{ctx_area_nk}], count={len(output1)} (Page {page_count})")
                
                if not ctx_area_nk:
                    break

                if ctx_area_nk == prev_nk:
                    logger.warning(f"Infinite loop detected: Pagination token {ctx_area_nk} did not change. Stopping sync.")
                    break
                prev_nk = ctx_area_nk
                    
                time.sleep(0.2) # Rate limit safety
                
            if not all_trades:
                logger.info("No execution history found from API.")
                return 0
                
            import pandas as pd
            # Normalize list of dicts/objects to dicts if they are objects
            # output1 elements are likely namedtuples too if created by kis_auth? 
            # kis_auth._getResultObject creates namedtuples recursively? 
            # No, _setBody creates namedtuple for top level. JSON deserialization usually makes dicts for nested objects unless customized.
            # requests.json() returns dicts/lists. 
            # kis_auth: _tb_ = namedtuple("body", self._resp.json().keys()) -> attributes are values.
            # If value is list, it's list of dicts.
            
            df1 = pd.DataFrame(all_trades)
            
            if df1.empty:
                logger.info("No execution history found from API (Empty DataFrame).")
                return 0
                
            # Process API Data
            # KIS API v1.0 domestic-stock/trading/inquire-daily-ccld details
            
            local_odnos = set(t.order_id for t in self.trade_history if t.order_id)
            new_count = 0
            
            for _, row in df1.iterrows():
                # row is a Series. Keys are columns.
                # Columns might be upper/lower.
                
                def get_val(row_series, candidates, default=None):
                    for cand in candidates:
                         if cand in row_series:
                             return row_series[cand]
                         if cand.upper() in row_series:
                             return row_series[cand.upper()]
                         if cand.lower() in row_series:
                             return row_series[cand.lower()]
                    return default

                odno = str(get_val(row, ['odno', 'ODNO']))
                if odno == 'None' or not odno: # Skip invalid
                     continue

                if odno in local_odnos:
                    continue
                    
                # New Trade Found
                symbol = str(get_val(row, ['pdno', 'PDNO']))
                
                qty_candidates = ['tot_ccld_qty', 'TOT_CCLD_QTY', 'ccld_qty', 'CCLD_QTY']
                qty = int(get_val(row, qty_candidates, 0))
                
                price = float(get_val(row, ['avg_prvs', 'AVG_PRVS'], 0.0))
                date_str = str(get_val(row, ['ord_dt', 'ORD_DT'], "")) 
                time_str = str(get_val(row, ['ord_tmd', 'ORD_TMD'], "000000"))
                side_code = str(get_val(row, ['sll_buy_dvsn_cd', 'SLL_BUY_DVSN_CD'], ""))
                side = "BUY" if side_code == "02" else "SELL"
                
                # Parse Date and Time
                if not date_str:
                     continue # Skip if no date
                     
                try:
                    full_dt_str = f"{date_str}{time_str}"
                    ts = datetime.strptime(full_dt_str, "%Y%m%d%H%M%S")
                except ValueError:
                     # Fallback if time is missing or invalid
                     try:
                        ts = datetime.strptime(date_str, "%Y%m%d")
                     except:
                        ts = datetime.now() # Should not happen

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
                
                from core.dao import TradeDAO
                TradeDAO.insert_trade({
                    "event_id": event.event_id,
                    "timestamp": event.timestamp,
                    "symbol": event.symbol,
                    "strategy_id": event.strategy_id,
                    "side": event.side,
                    "price": event.price,
                    "qty": event.qty,
                    "exec_amt": event.price * event.qty,
                    "order_id": event.order_id,
                    "meta": event.meta
                })
                
            if new_count > 0:
                # Sort by timestamp
                self.trade_history.sort(key=lambda x: x.timestamp if isinstance(x.timestamp, datetime) else datetime.fromisoformat(str(x.timestamp)))
                logger.info(f" synced {new_count} new trades from Broker API.")
            else:
                logger.info("All trades already exist locally.")

            # --- Sync Realized PnL ---
            try:
                # Only sync PnL if we have trades or just always try for the period? 
                # Always try is safer to catch up updates.
                logger.info(f"Syncing Period PnL from {start_date} to {end_date}...")
                pnl_resp = ka.fetch_period_profit(start_date, end_date)
                
                if pnl_resp and pnl_resp.isOK():
                    pnl_body = pnl_resp.getBody()
                    pnl_list = getattr(pnl_body, 'output1', [])
                    
                    # Build Map: (date_str, symbol) -> pnl
                    pnl_map = {}

                    def safe_float(val):
                        if val is None or val == "": return 0.0
                        if isinstance(val, (int, float)): return float(val)
                        try:
                            # Remove commas and whitespace
                            clean_val = str(val).replace(',', '').strip()
                            if not clean_val: return 0.0
                            return float(clean_val)
                        except Exception:
                            return 0.0

                    # Inspect first item to handle naming key variations
                    if pnl_list and len(pnl_list) > 0:
                        sample = pnl_list[0]
                        # logger.debug(f"PnL Sample Data: {sample}")

                    for item in pnl_list:
                        # Helper to get value
                        def g(obj, keys, default=None):
                            if isinstance(obj, dict):
                                for k in keys: 
                                    if k in obj: return obj[k]
                            else:
                                for k in keys:
                                    if hasattr(obj, k): return getattr(obj, k)
                            return default

                        dt = str(g(item, ['tr_dt', 'TR_DT', 'ord_dt', 'ORD_DT'], ""))
                        sym = str(g(item, ['pdno', 'PDNO', 'shtn_pdno'], ""))
                        
                        # Use safe_float for PnL
                        pnl_raw = g(item, ['rlzg_pl', 'RLZG_PL', 'cisa_pl', 'CISA_PL'], 0)
                        pnl = safe_float(pnl_raw)
                        
                        if dt and sym:
                            pnl_map[(dt, sym)] = pnl_map.get((dt, sym), 0.0) + pnl
                    
                    if pnl_map:
                        logger.info(f"Fetched PnL data for {len(pnl_map)} day-symbol pairs.")
                    else:
                        logger.info("Fetched PnL data but result map is empty.")

                    # Assign PnL to local Sell events
                    # Strategy: Assign Daily PnL to the LAST Sell event of that day for that symbol
                    
                    # 1. Group Sell Events
                    day_sell_events = {} # (date_str, symbol) -> [event]
                    
                    for event in self.trade_history:
                        if event.side == "SELL":
                            d_str = event.timestamp.strftime("%Y%m%d")
                            k = (d_str, event.symbol)
                            if k not in day_sell_events:
                                day_sell_events[k] = []
                            day_sell_events[k].append(event)
                    
                    # 2. Match and Update
                    updated_pnl_count = 0
                    for k, events in day_sell_events.items():
                        if k in pnl_map:
                            daily_pnl = pnl_map[k]
                            # Sort events by time just in case
                            events.sort(key=lambda x: x.timestamp)
                            
                            # Assign to the last one
                            last_event = events[-1]
                            
                            # Check if update needed
                            if last_event.pnl != daily_pnl:
                                last_event.pnl = daily_pnl
                                updated_pnl_count += 1
                                # logger.debug(f"Updated PnL for {last_event.symbol} on {k[0]}: {daily_pnl}")
                    
                    if updated_pnl_count > 0:
                        from core.dao import TradeDAO
                        # We need to loop again to update DB or track what changed
                        # Re-loop day_sell_events is faster
                         
                        for k, events in day_sell_events.items():
                             if k in pnl_map:
                                 daily_pnl = pnl_map[k]
                                 last_event = events[-1]
                                 # Update DB using TradeDAO
                                 TradeDAO.update_pnl(last_event.event_id, daily_pnl, 0.0) # Pct calc might need more info, passing 0 for now or calc it

                        logger.info(f"Updated PnL for {updated_pnl_count} trade events.")
                    else:
                        logger.info("No PnL updates needed.")
                        
                else:
                    msg = pnl_resp.getErrorMessage() if pnl_resp else 'None'
                    code = pnl_resp.getErrorCode() if pnl_resp else 'Unknown'
                    logger.warning(f"PnL Fetch Failed: [{code}] {msg}. Falling back to local FIFO PnL calculation.")
                    self._calculate_pnl_from_local_history()

            except Exception as e:
                logger.error(f"PnL Sync Logic Error: {e}")
                import traceback
                logger.error(traceback.format_exc())

            return new_count
            
        except KeyboardInterrupt:
            logger.warning("Sync operation interrupted by user.")
            return 0
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise e
        finally:
            # Refresh In-Memory Cache with latest DB state
            self.load_trade_history()

    def _calculate_pnl_from_local_history(self):
        """
        Calculate Realized PnL for SELL events using FIFO method from local trade history.
        This is a fallback when API PnL is unavailable.
        """
        try:
            # Sort by time
            sorted_events = sorted(self.trade_history, key=lambda x: x.timestamp)
            
            # Inventory: symbol -> list of [price, qty]
            inventory = {}
            updated_count = 0
            
            for event in sorted_events:
                sym = event.symbol
                if sym not in inventory:
                    inventory[sym] = []
                    
                if event.side == "BUY":
                    # Add to inventory
                    inventory[sym].append([event.price, event.qty])
                
                elif event.side == "SELL":
                    # FIFO Matching
                    sell_qty = event.qty
                    sell_price = event.price
                    
                    cost_basis = 0.0
                    matched_qty = 0
                    
                    # Consume inventory
                    while sell_qty > 0 and inventory[sym]:
                        bucket = inventory[sym][0] # Oldest
                        b_price = bucket[0]
                        b_qty = bucket[1]
                        
                        take_qty = min(sell_qty, b_qty)
                        
                        cost_basis += (take_qty * b_price)
                        matched_qty += take_qty
                        
                        # Update bucket
                        if b_qty > take_qty:
                            bucket[1] -= take_qty
                            sell_qty = 0
                        else:
                            inventory[sym].pop(0) # Fully consumed
                            sell_qty -= take_qty
                            
                    if matched_qty > 0:
                        avg_buy_price = cost_basis / matched_qty
                        gross_pnl = (sell_price - avg_buy_price) * matched_qty
                        
                        # Apply Fee (Estimate 0.25%)
                        fee = (sell_price * matched_qty) * 0.0025
                        net_pnl = gross_pnl - fee
                        pnl_pct = ((sell_price - avg_buy_price) / avg_buy_price) * 100
                        
                        # Update Event if PnL is missing or we want to overwrite?
                        # Only update if missing to respect API data if valid
                        if event.pnl is None or event.pnl == 0:
                            event.pnl = round(net_pnl, 0)
                            event.pnl_pct = round(pnl_pct, 2)
                            updated_count += 1
            
            if updated_count > 0:
                from core.dao import TradeDAO
                for event in sorted_events:
                     if event.side == "SELL" and event.pnl is not None:
                          TradeDAO.update_pnl(event.event_id, event.pnl, event.pnl_pct)
                
                logger.info(f"Locally calculated PnL for {updated_count} SELL events using FIFO.")
                
        except Exception as e:
            logger.error(f"Local PnL Calculation Failed: {e}")

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
