from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import uuid

Base = declarative_base()

class Trade(Base):
    __tablename__ = 'trades'

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(36), unique=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime, index=True)
    symbol = Column(String(20), index=True)
    strategy_id = Column(String(50))
    side = Column(String(10))  # BUY, SELL
    price = Column(Float)
    qty = Column(Integer)
    exec_amt = Column(Float)
    pnl = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    order_id = Column(String(50), nullable=True)
    meta = Column(JSON, nullable=True)

    def __repr__(self):
        return f"<Trade(symbol={self.symbol}, side={self.side}, qty={self.qty}, price={self.price})>"

class Watchlist(Base):
    __tablename__ = 'watchlist'

    symbol = Column(String(20), primary_key=True)
    name = Column(String(100), nullable=True)
    added_at = Column(DateTime, default=func.now())

class SystemConfig(Base):
    __tablename__ = 'system_config'

    key = Column(String(50), primary_key=True)
    value = Column(String(255))
    value = Column(String(255))
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

class Checklist(Base):
    __tablename__ = 'checklist'

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(String(255), nullable=False)
    is_done = Column(Integer, default=0) # 0: Active, 1: Done
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
