
from datetime import datetime, timedelta
import uuid
import json
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

try:
    from core.visualization import TradeEvent
except ImportError:
    # Mock TradeEvent if import fails (standalone test)
    from dataclasses import dataclass
    from typing import Optional, Dict, Any

    @dataclass
    class TradeEvent:
        event_id: str
        timestamp: datetime
        symbol: str
        strategy_id: str
        event_type: str
        side: str
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

def debug_injection():
    print("--- Debugging Trade Injection ---")
    
    # Simulate injection logic
    base_time = datetime.now()
    event_time = base_time - timedelta(minutes=30)
    
    event = TradeEvent(
        event_id=str(uuid.uuid4()),
        timestamp=event_time,
        symbol="005930",
        strategy_id="debug_manual",
        event_type="ORDER_FILLED",
        side="BUY",
        price=60000.0,
        qty=5,
        order_id=f"debug_{uuid.uuid4().hex[:8]}",
        meta={"type": "LIMIT"}
    )
    
    # Serialize
    event_dict = event.to_dict()
    print(f"Raw Timestamp Object: {event.timestamp} (Type: {type(event.timestamp)})")
    print(f"Serialized Timestamp: '{event_dict['timestamp']}'")
    
    # Verify ISO format
    ts_str = event_dict['timestamp']
    if 'T' in ts_str:
        print("PASS: Timestamp contains 'T' separator.")
    else:
        print("FAIL: Timestamp missing 'T' separator.")
        
    # JSON Dump check
    json_str = json.dumps(event_dict)
    print(f"JSON Output: {json_str}")

if __name__ == "__main__":
    debug_injection()
