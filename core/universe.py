import logging
import time
from datetime import datetime
from typing import List, Dict, Optional
from core.dao import WatchlistDAO
from core.scanner import Scanner
from core.market_data import MarketData
from core.portfolio import Portfolio

logger = logging.getLogger(__name__)

class Universe:
    def __init__(self, system_config: Dict, market_data: MarketData, scanner: Scanner, portfolio: Portfolio):
        self.system_config = system_config
        self.market_data = market_data
        self.scanner = scanner
        self.portfolio = portfolio
        self.watchlist = []
        self.last_scan_time = 0
        self.cached_watchlist = []

    def load_watchlist(self):
        """Load watchlist from Database"""
        try:
            self.watchlist = WatchlistDAO.get_all_symbols()
            logger.debug(f"Loaded Watchlist: {len(self.watchlist)} items from Database")
        except Exception as e:
            logger.error(f"Failed to load watchlist: {e}")
            self.watchlist = []

    def migrate_legacy_universe(self, legacy_universe: List[str], update_config_callback):
        """Migrate legacy 'universe' config to watchlist.json"""
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
            update_config_callback({"universe": []})
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
        self.update_universe()

    def _is_trading_hour(self) -> bool:
        """Check if current time is within trading hours"""
        # Dev mode bypass
        if self.system_config.get("env_type") == "dev":
            return True
            
        market_type = self.system_config.get("market_type", "KRX")
        now = datetime.now()
        
        if market_type == "KRX":
            # Weekend Check
            if now.weekday() >= 5: return False
            
            # Time Check (09:00 ~ 15:30)
            current_time = now.time()
            start = now.replace(hour=9, minute=0, second=0, microsecond=0).time()
            end = now.replace(hour=15, minute=30, second=0, microsecond=0).time()
            return start <= current_time <= end
        
        elif market_type == "NXT":
            # NXT Time (08:00 ~ 20:00)
            current_time = now.time()
            start = now.replace(hour=8, minute=0, second=0, microsecond=0).time()
            end = now.replace(hour=20, minute=0, second=0, microsecond=0).time()
            return start <= current_time <= end
            
        return True # Default open

    def update_universe(self):
        """Update stock universe based on config or scanner"""
        
        # [User Request] Strict Market Hour Check for Scanner Logic
        if not self._is_trading_hour():
            logger.info("장 운영 시간이 아니므로 스캐너 실행을 건너뜁니다.")
            return

        universe = []

        # Increase scanner interval check to 120s to be safe
        if self.system_config.get("use_auto_scanner", False):
            # Also check if we just scanned recently (double check timestamp)
            if time.time() - self.last_scan_time < 60:
                return

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

                api_watchlist = self.cached_watchlist

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
