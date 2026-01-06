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
    def get_trades(start_date: datetime = None, end_date: datetime = None, symbol: str = None, env_type: str = None, limit: int = 100, offset: int = 0) -> List[Trade]:
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
            
            if env_type:
                 query = query.filter(Trade.env_type == env_type)
                
            # Sort by timestamp DESC
            query = query.order_by(desc(Trade.timestamp))
            
            if limit > 0:
                query = query.limit(limit).offset(offset)
                
            return query.all()
        finally:
            session.close()

    @staticmethod
    def get_first_trade(symbol: str, side: str = "BUY") -> Optional[Trade]:
        """
        Get the first trade for a symbol and side (e.g. First BUY).
        """
        session = db_manager.get_session()
        try:
            trade = session.query(Trade).filter(Trade.symbol == symbol, Trade.side == side).order_by(Trade.timestamp.asc()).first()
            return trade
        except Exception as e:
            logger.error(f"Failed to get first trade for {symbol}: {e}")
            return None
        finally:
            session.close()

    @staticmethod
    def get_last_entry_date(symbol: str) -> Optional[datetime]:
        """
        Calculate the timestamp when the current position was established.
        It replays trade history to find the last time position qty went from 0 to positive.
        """
        session = db_manager.get_session()
        try:
            # Get all trades sorted by time
            trades = session.query(Trade).filter(Trade.symbol == symbol).order_by(Trade.timestamp.asc()).all()
            
            current_qty = 0
            last_entry_time = None
            
            for trade in trades:
                if trade.side == "BUY":
                    if current_qty == 0:
                        last_entry_time = trade.timestamp
                    current_qty += trade.qty
                elif trade.side == "SELL":
                    current_qty -= trade.qty
                    if current_qty <= 0:
                        current_qty = 0
                        last_entry_time = None # Reset entry time when position is closed
            
            return last_entry_time
            
        except Exception as e:
            logger.error(f"Failed to calculate last entry date for {symbol}: {e}")
            return None
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

class ChecklistDAO:
    @staticmethod
    def get_all() -> List[Dict]:
        """Get all checklist items as dictionaries"""
        session = db_manager.get_session()
        try:
            from core.models import Checklist
            items = session.query(Checklist).order_by(Checklist.is_done.asc(), Checklist.created_at.desc()).all()

            # Convert to dict inside session to prevent detached instance access errors
            return [{
                "id": item.id,
                "text": item.text,
                "is_done": item.is_done,
                "created_at": item.created_at.strftime("%Y-%m-%d %H:%M:%S") if item.created_at else ""
            } for item in items]
        except Exception as e:
            logger.error(f"Failed to fetch checklist: {e}")
            return []
        finally:
            session.close()

    @staticmethod
    def add_item(text: str):
        session = db_manager.get_session()
        try:
            from core.models import Checklist
            item = Checklist(text=text, is_done=0)
            session.add(item)
            session.commit()

            # Refresh to get ID and Created At
            session.refresh(item)

            # Return dict directly
            return {
                "id": item.id,
                "text": item.text,
                "is_done": item.is_done,
                "created_at": item.created_at.strftime("%Y-%m-%d %H:%M:%S") if item.created_at else ""
            }
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to add checklist item: {e}")
            return None
        finally:
            session.close()
            
    @staticmethod
    def update_status(item_id: int, is_done: int):
        session = db_manager.get_session()
        try:
            from core.models import Checklist
            item = session.query(Checklist).get(item_id)
            if item:
                item.is_done = is_done
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update checklist item: {e}")
            return False
        finally:
            session.close()

    @staticmethod
    def delete_item(item_id: int):
        session = db_manager.get_session()
        try:
            from core.models import Checklist
            item = session.query(Checklist).get(item_id)
            if item:
                session.delete(item)
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to delete checklist item: {e}")
            return False
        finally:
            session.close()
