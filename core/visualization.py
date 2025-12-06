from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# Debug logging to file
debug_handler = logging.FileHandler("api_debug.log")
debug_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
debug_handler.setFormatter(formatter)
logger.addHandler(debug_handler)

@dataclass
class TradeEvent:
    event_id: str
    timestamp: datetime
    symbol: str
    strategy_id: str
    event_type: str  # ORDER_FILLED, STOP_LOSS, TAKE_PROFIT, etc.
    side: str        # BUY, SELL
    price: float
    qty: int
    order_id: str
    position_id: Optional[str] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    meta: Optional[Dict[str, Any]] = None

    def to_dict(self):
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "symbol": self.symbol,
            "strategy_id": self.strategy_id,
            "event_type": self.event_type,
            "side": self.side,
            "price": self.price,
            "qty": self.qty,
            "order_id": self.order_id,
            "position_id": self.position_id,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "meta": self.meta or {}
        }

class TradeVisualizationService:
    def __init__(self, engine):
        self.engine = engine

    def get_chart_data(self, symbol: str, timeframe: str = "1m", lookback: int = 300) -> Dict[str, Any]:
        """
        Get chart data including candles and trade markers.
        """
        logger.info(f"TradeVisualizationService: Requesting chart data for {symbol} {timeframe} (lookback={lookback})")

        # 1. Get Candle Data
        candles = []
        if hasattr(self.engine, 'market_data'):
            try:
                # Map timeframe to MarketData format if needed
                # MarketData expects "1m", "3m", "5m", "1d"
                # Frontend sends "1m", "3m", "5m", "D" -> "1d"
                md_timeframe = timeframe
                if timeframe == "D":
                    md_timeframe = "1d"
                
                logger.info(f"Calling market_data.get_bars({symbol}, {md_timeframe})")
                df = self.engine.market_data.get_bars(symbol, md_timeframe, lookback=lookback)
                logger.info(f"MarketData returned {len(df) if df is not None else 'None'} bars")
                
                if not df.empty:
                    # Convert DataFrame to list of dicts for Lightweight Charts
                    # Expected: { time: '2019-04-11', open: 80.01, high: 96.63, low: 76.6, close: 88.65 }
                    # or { time: 1554940800, ... } (seconds)
                    
                    for _, row in df.iterrows():
                        # Handle time format
                        # Daily: YYYYMMDD -> YYYY-MM-DD string
                        # Minute: HHMMSS -> We need full datetime for chart
                        
                        chart_time = None
                        if md_timeframe == "1d":
                            d = str(row['date'])
                            chart_time = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                        else:
                            # Minute bars have 'time' column (HHMMSS) or 'datetime' index if resampled
                            if 'datetime' in row:
                                chart_time = row['datetime'].timestamp() # Seconds
                            elif 'time' in row:
                                # Assume today
                                t = str(row['time'])
                                now = datetime.now()
                                dt = datetime(now.year, now.month, now.day, int(t[:2]), int(t[2:4]), int(t[4:6]))
                                chart_time = dt.timestamp()
                            
                        if chart_time:
                            candles.append({
                                "time": chart_time,
                                "open": row['open'],
                                "high": row['high'],
                                "low": row['low'],
                                "close": row['close'],
                                "volume": row['volume']
                            })
                    
                    # Calculate RSI
                    delta = df['close'].diff()
                    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                    rs = gain / loss
                    df['rsi'] = 100 - (100 / (1 + rs))
                    
                    # Add RSI data to response
                    # We need to match the time with candles
                    rsi_data = []
                    for _, row in df.iterrows():
                        chart_time = None
                        # ... (reuse time logic or just iterate zipped)
                        # To be safe and simple, let's just re-use the time logic or map it.
                        # Since we iterate df again, it's fine.
                        
                        # Copy-paste time logic for brevity or refactor? 
                        # Refactoring is better but I'll duplicate for safety in this patch.
                        if md_timeframe == "1d":
                            d = str(row['date'])
                            chart_time = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                        else:
                            if 'datetime' in row:
                                chart_time = row['datetime'].timestamp()
                            elif 'time' in row:
                                t = str(row['time'])
                                now = datetime.now()
                                dt = datetime(now.year, now.month, now.day, int(t[:2]), int(t[2:4]), int(t[4:6]))
                                chart_time = dt.timestamp()
                        
                        if chart_time and not pd.isna(row['rsi']):
                            rsi_data.append({
                                "time": chart_time,
                                "value": row['rsi']
                            })

                    # Calculate Moving Averages
                    ma_periods = [5, 10, 20, 60, 120, 200]
                    ma_data = {}
                    for period in ma_periods:
                        df[f'ma_{period}'] = df['close'].rolling(window=period).mean()
                        
                        series_data = []
                        for _, row in df.iterrows():
                            # Reuse time logic (simplified for brevity, ideally refactor time extraction)
                            chart_time = None
                            if md_timeframe == "1d":
                                d = str(row['date'])
                                chart_time = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                            else:
                                if 'datetime' in row:
                                    chart_time = row['datetime'].timestamp()
                                elif 'time' in row:
                                    t = str(row['time'])
                                    now = datetime.now()
                                    dt = datetime(now.year, now.month, now.day, int(t[:2]), int(t[2:4]), int(t[4:6]))
                                    chart_time = dt.timestamp()
                            
                            if chart_time and not pd.isna(row[f'ma_{period}']):
                                series_data.append({
                                    "time": chart_time,
                                    "value": row[f'ma_{period}']
                                })
                        ma_data[f'ma_{period}'] = series_data

            except Exception as e:
                logger.error(f"Failed to fetch candles: {e}")

        # 2. Get Trade Markers from Engine's trade history
        markers = []
        if hasattr(self.engine, 'trade_history'):
            for event in self.engine.trade_history:
                if event.symbol == symbol:
                    markers.append(event.to_dict())

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": candles, 
            "rsi": rsi_data if 'rsi_data' in locals() else [],
            "ma_data": ma_data if 'ma_data' in locals() else {},
            "markers": markers
        }
