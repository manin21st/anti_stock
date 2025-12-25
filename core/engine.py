import logging
import time
import threading
from typing import Dict, List, Optional
import sys
import os
import uuid

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.market_data import MarketData
from core.broker import Broker
from core.portfolio import Portfolio
from core.risk_manager import RiskManager
from core.scanner import Scanner
from core.dao import TradeDAO, WatchlistDAO
from utils.telegram import TelegramBot
from core.config_manager import ConfigManager
from core.trade_manager import TradeManager
from core.backtester import Backtester
from datetime import datetime

logger = logging.getLogger(__name__)

class Engine:
    def __init__(self, config_path: str = "config/strategies.yaml"):
        # 1. Config Manager
        self.config_manager = ConfigManager(strategies_path=config_path)
        self.config = self.config_manager.config
        self.system_config = self.config_manager.get_system_config()
        
        # 2. Authenticate
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
            ka.auth_ws(svr=svr)
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
        
        # 3. Core Components
        self.market_data = MarketData()
        self.broker = Broker()
        self.portfolio = Portfolio()
        self.risk_manager = RiskManager(self.portfolio, self.config)
        self.scanner = Scanner()
        self.telegram = TelegramBot(self.system_config)
        self.telegram.send_system_alert("🚀 <b>System Started</b>\nAnti-Stock Engine Initialized.")
        
        # 4. Managers
        self.trade_manager = TradeManager(telegram_bot=self.telegram)
        self.backtester = Backtester(self.config, {}) # strategy_classes will be filled later

        self.strategies = {} # strategy_id -> Strategy Instance
        self.strategy_classes = {} # strategy_id -> Strategy Class
        
        # Link backtester to strategy classes
        self.backtester.strategy_classes = self.strategy_classes

        self.is_running = False
        self.is_trading = False
        self.restart_requested = False
        self.last_scan_time = 0
        self.last_sync_time = 0
        self._last_wait_log_time = 0
        
        # Subscribe to market data events
        self.market_data.subscribers.append(self.on_market_data)
        
        # Subscribe to Broker and Portfolio events via TradeManager
        self.broker.on_order_sent.append(self.trade_manager.record_order_event)
        # Pass market_data dynamically using lambda
        self.portfolio.on_position_change.append(lambda x: self.trade_manager.record_position_event(x, self.market_data))

        # Watchlist Management
        self.watchlist = []
        self._load_watchlist() 
        # Database Warm-up
        self._warmup_db()

    @property
    def trade_history(self):
        """Proxy to trade_manager.trade_history for backward compatibility"""
        return self.trade_manager.trade_history

    def _warmup_db(self):
        """Force DB connection establishment to avoid lazy loading delay on first UI request"""
        try:
            logger.debug("Warming up Database Connection...")
            from core.database import db_manager
            
            # Ensure tables exist (Critical for new features like Checklist)
            db_manager.create_tables()

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
        self.config_manager.update_system_config(new_config)
        
        # Reload components
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

    def update_strategy_config(self, new_config: Dict):
        """Update strategy configuration (Config only, applied on restart)"""
        self.config_manager.update_strategy_config(new_config)

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
            # [Strict Mode] Block until TPS Server is confirmed
            from core import kis_api as ka
            if hasattr(ka, 'rate_limiter') and ka.rate_limiter:
                ka.rate_limiter.wait_for_tps()
                
            logger.info("Engine loop started")
            
            # Re-authenticate if needed (e.g. on restart)
            env_type = self.system_config.get("env_type", "paper")
            svr = "vps" if env_type == "paper" else "prod"
            
            try:
                # On restart, we might want to re-auth to be safe
                if self.restart_requested:
                    logger.debug(f"DEBUG: Re-authenticating for {env_type} ({svr})")
                    ka.auth(svr=svr)
                
                # Re-instantiate strategies with fresh config
                self.strategies.clear()
                self.config_manager.reload() # Ensure config is fresh
                self.config = self.config_manager.config
                self.system_config = self.config_manager.get_system_config()
                
                active_strategy_id = self.config.get("active_strategy")
                logger.debug(f"Active strategy ID: {active_strategy_id}")
                
                if active_strategy_id and active_strategy_id in self.strategy_classes:
                    strategy_class = self.strategy_classes[active_strategy_id]
                    
                    # Strategy Config Precedence
                    strategy_config = self.config.get("common", {}).copy()
                    strategy_config.update(self.config.get(active_strategy_id, {}))
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
                            self._last_wait_log_time = int(time.time())
                        
                        if self._last_wait_log_time == 0:
                             logger.info("장 운영 시간이 아닙니다. 대기 중... (KRX: 09:00~15:30)")
                             self._last_wait_log_time = int(time.time())
                        
                        time.sleep(1)
                        continue
                    else:
                        if self._last_wait_log_time != 0:
                             self._last_wait_log_time = 0

                        if self.is_trading and not self.market_data.is_polling:
                             if hasattr(self.market_data, 'polling_symbols') and self.market_data.polling_symbols:
                                 logger.info("장 운영 시간입니다. 감시를 재개합니다.")
                                 self.market_data.start_polling()

                    # Periodic Scanner Update
                    if self.system_config.get("use_auto_scanner", False):
                        if time.time() - self.last_scan_time > 60: 
                            self._update_universe()
                            if self.is_trading and not self.market_data.is_polling:
                                self.market_data.start_polling()
                            
                            if hasattr(self.market_data, 'polling_symbols'):
                                symbols = self.market_data.polling_symbols
                                logger.info(f"[감시 종목 업데이트] 총 {len(symbols)}개: {', '.join(symbols[:10])}{' ...' if len(symbols)>10 else ''}")
                    
                    # Heartbeat
                    if time.time() - last_heartbeat > 3:
                        if int(time.time()) % 60 == 0:
                            n_monitoring = len(self.market_data.polling_symbols) if hasattr(self.market_data, 'polling_symbols') else 0
                            n_positions = len(self.portfolio.positions)
                            total_asset = int(self.portfolio.total_asset)
                            
                            logger.info(f"[시스템 정상] 감시: {n_monitoring}종목 | 보유: {n_positions}종목 | 총자산: {total_asset:,}원")
                        last_heartbeat = time.time()
                    
                    # Periodic Portfolio Sync (Every 5 seconds)
                    if time.time() - self.last_sync_time > 5:
                        try:
                            balance = self.broker.get_balance()
                            if balance:
                                self.portfolio.sync_with_broker(balance, notify=True, tag_lookup_fn=self._resolve_strategy_tag)

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
                continue
            
            if not self.is_running:
                break

    def _is_trading_hour(self) -> bool:
        """Check if current time is within trading hours"""
        if self.config.get("system", {}).get("env_type") == "dev":
            return True
            
        market_type = self.system_config.get("market_type", "KRX")
        now = datetime.now()
        
        if market_type == "KRX":
            if now.weekday() >= 5: return False
            current_time = now.time()
            start = now.replace(hour=9, minute=0, second=0, microsecond=0).time()
            end = now.replace(hour=15, minute=30, second=0, microsecond=0).time()
            return start <= current_time <= end
        elif market_type == "NXT":
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
                    items = self.scanner.get_trading_value_leaders(limit=50)
                else:
                    items = self.scanner.get_top_gainers(limit=50)
                
                scanned_symbols = []
                if items:
                    for item in items:
                        if isinstance(item, dict) and "symbol" in item:
                            scanned_symbols.append(item["symbol"])
                        else:
                            logger.warning(f"Scanner returned invalid item: {item}")

                logger.info(f"Scanner found {len(scanned_symbols)} stocks: {scanned_symbols}")
                
                api_watchlist = getattr(self, 'cached_watchlist', [])
                
                if self.watchlist:
                    full_watchlist = set(self.watchlist)
                else:
                    full_watchlist = set(api_watchlist)
                
                watchlist = list(full_watchlist)
                
                if watchlist:
                    watchlist = [str(x).zfill(6) for x in watchlist]
                    universe = [s for s in scanned_symbols if s in watchlist]
                    logger.info(f"Filtered by Watchlist: {len(universe)} stocks selected {universe}")
                else:
                    logger.warning("Auto-Scanner is on, but Watchlist is empty. No stocks selected.")
                    universe = []

            except Exception as e:
                logger.error(f"Scanner failed: {e}")
                universe = []
        else:
            universe = self.watchlist
            logger.info(f"Using manual universe (Watchlist): {universe}")
            
        subscription_list = set(universe) if universe else set()
        
        if self.watchlist:
            subscription_list.update(self.watchlist)
        
        if self.portfolio.positions:
            holdings = [str(s).zfill(6) for s in self.portfolio.positions.keys()]
            subscription_list.update(holdings)
            logger.info(f"Added {len(holdings)} holdings to subscription list: {holdings}")
            
        if subscription_list:
            final_list = [str(x).zfill(6) for x in subscription_list]
            self.market_data.subscribe_market_data(final_list)
        
        self.last_scan_time = time.time()

    def register_strategy(self, strategy_class, strategy_id: str):
        """Register a strategy class"""
        self.strategy_classes[strategy_id] = strategy_class
        # Also update backtester
        self.backtester.strategy_classes = self.strategy_classes

    def stop(self):
        self.is_running = False
        if hasattr(self, 'market_data'):
            self.market_data.stop_polling()
        logger.info("Engine stopped")

    def _resolve_strategy_tag(self, symbol: str) -> str:
        """Helper to find the last strategy that traded this symbol from history"""
        for event in reversed(self.trade_manager.trade_history):
            if event.symbol == symbol and event.event_type == "ORDER_SUBMITTED":
                 return event.strategy_id
        return ""

    def on_market_data(self, data: Dict):
        """Handle real-time market data"""
        if not self._is_trading_hour():
            return

        symbol = data.get("symbol")
        if not symbol:
            return
        
        if not self.is_trading:
            return

        self.portfolio.update_market_price(symbol, data.get("price", 0.0))

        for strategy in self.strategies.values():
            try:
                strategy.on_tick(symbol, data)
                
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
            except Exception as e:
                logger.error(f"Error in strategy execution: {e}")

    # Delegation methods
    def load_trade_history(self):
        self.trade_manager.load_trade_history()

    def sync_trade_history(self, start_date, end_date):
        return self.trade_manager.sync_trade_history(start_date, end_date)

    def run_backtest(self, strategy_id: str, symbol: str, start_date: str, end_date: str, initial_cash: int = 100000000, strategy_config: Dict = None, progress_callback=None) -> Dict:
        return self.backtester.run_backtest(strategy_id, symbol, start_date, end_date, initial_cash, strategy_config, progress_callback)
