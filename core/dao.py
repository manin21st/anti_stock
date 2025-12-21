import logging
from sqlalchemy import desc, func
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from core.database import db_manager
from core.models import Trade, Watchlist

logger = logging.getLogger(__name__)

class TradeDAO:
    @staticmethod
    def insert_trade(trade_data: Dict[str, Any]):
        """
        Insert a new trade record.
        """
        session = db_manager.get_session()
        try:
            # Check for duplicate event_id
            if 'event_id' in trade_data:
                exists = session.query(Trade).filter_by(event_id=trade_data['event_id']).first()
                if exists:
                    logger.warning(f"Trade event {trade_data['event_id']} already exists. Skipping.")
                    return

            trade = Trade(**trade_data)
            session.add(trade)
            session.commit()
            # logger.debug(f"Trade inserted: {trade}")
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to insert trade: {e}")
            raise e
        finally:
            session.close()

    @staticmethod
    def get_trades(start_date: datetime = None, end_date: datetime = None, symbol: str = None, limit: int = 100, offset: int = 0) -> List[Trade]:
        """
        Fetch trades with filters.
        """
        session = db_manager.get_session()
        try:
            query = session.query(Trade)
            
            if symbol:
                query = query.filter(Trade.symbol == symbol)
            
            if start_date:
                query = query.filter(Trade.timestamp >= start_date)
                
            if end_date:
                query = query.filter(Trade.timestamp <= end_date)
                
            # Sort by timestamp DESC
            query = query.order_by(desc(Trade.timestamp))
            
            if limit > 0:
                query = query.limit(limit).offset(offset)
                
            return query.all()
        finally:
            session.close()

    @staticmethod
    def get_all_trades_count() -> int:
        session = db_manager.get_session()
        try:
            return session.query(func.count(Trade.id)).scalar()
        finally:
            session.close()

    @staticmethod
    def update_pnl(event_id: str, pnl: float, pnl_pct: float):
        """
        Update PnL for a specific sell trade.
        """
        session = db_manager.get_session()
        try:
            trade = session.query(Trade).filter_by(event_id=event_id).first()
            if trade:
                trade.pnl = pnl
                trade.pnl_pct = pnl_pct
                session.commit()
                # logger.debug(f"Updated PnL for {event_id}")
            else:
                logger.warning(f"Trade {event_id} not found for PnL update.")
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update PnL: {e}")
        finally:
            session.close()

class WatchlistDAO:
    @staticmethod
    def add_symbol(symbol: str, name: str = ""):
        session = db_manager.get_session()
        try:
            exists = session.query(Watchlist).filter_by(symbol=symbol).first()
            if not exists:
                wl = Watchlist(symbol=symbol, name=name)
                session.add(wl)
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to add to watchlist: {e}")
        finally:
            session.close()

    @staticmethod
    def remove_symbol(symbol: str):
        session = db_manager.get_session()
        try:
            wl = session.query(Watchlist).filter_by(symbol=symbol).first()
            if wl:
                session.delete(wl)
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to remove from watchlist: {e}")
        finally:
            session.close()

    @staticmethod
    def get_all_symbols() -> List[str]:
        session = db_manager.get_session()
        try:
            results = session.query(Watchlist.symbol).all()
            return [r[0] for r in results]
        finally:
            session.close()
