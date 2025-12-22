import time
import uvicorn
import logging
import os
import asyncio
from typing import Dict
from fastapi import FastAPI, Response, status, Request
from contextlib import asynccontextmanager

# Configuration
TPS_LIMIT = 5.0  # Total TPS limit across all clients (Reduced from 20.0)
BURST_LIMIT = 1   # Max accumulated tokens (Reduced from 20 to prevent bursts)
PORT = 9000
LOG_FILE = os.path.join("logs", "tps_server.log")
CLIENT_TIMEOUT = 180  # 3 minutes

# Ensure logs directory exists
os.makedirs("logs", exist_ok=True)

# Logging Setup
logger = logging.getLogger("tps_server")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# File Handler
file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Console Handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

class TokenBucket:
    def __init__(self, rate, capacity):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.time()
        self.lock = asyncio.Lock()

    def consume(self, amount=1):
        now = time.time()
        elapsed = now - self.last_refill
        
        # Refill
        if elapsed > 0:
            new_tokens = elapsed * self.rate
            self.tokens = min(self.capacity, self.tokens + new_tokens)
            self.last_refill = now
        
        # Consume
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False

class ClientManager:
    def __init__(self):
        self.clients: Dict[str, float] = {} # {client_id: last_seen}
        
    def touch(self, client_id: str):
        is_new = client_id not in self.clients
        self.clients[client_id] = time.time()
        return is_new

    def cleanup(self, timeout=CLIENT_TIMEOUT):
        now = time.time()
        expired = [cid for cid, last in self.clients.items() if now - last > timeout]
        for cid in expired:
            del self.clients[cid]
        return expired

bucket = TokenBucket(rate=TPS_LIMIT, capacity=BURST_LIMIT)
clients = ClientManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"TPS Server Attempting Start on Port {PORT} (Limit: {TPS_LIMIT}/s)")
    
    # Background Task for Cleanup
    stop_event = asyncio.Event()
    
    async def cleanup_loop():
        while not stop_event.is_set():
            try:
                # Wait for 60 seconds OR until stop_event is set
                await asyncio.wait_for(stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                # Timeout means 60s passed, run cleanup
                expired = clients.cleanup()
                if expired:
                    msg = f"[Event:Disconnect] Removed {len(expired)} inactive clients: {expired}. Stats: Clients={len(clients.clients)}"
                    logger.info(msg)
    
    task = asyncio.create_task(cleanup_loop())
    
    yield
    
    # Shutdown
    stop_event.set()
    await task
    logger.info("TPS Server Stopped")

app = FastAPI(title="Anti-Stock TPS Server", lifespan=lifespan)

def log_event(event_type: str, client_id: str, extra: str = ""):
    active_count = len(clients.clients)
    current_tokens = f"{bucket.tokens:.2f}"
    msg = f"[Event:{event_type}] Client={client_id}. {extra} Stats: Active={active_count}, Tokens={current_tokens}/{bucket.capacity}"
    logger.info(msg)

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Anti-Stock TPS Server Running"}

@app.get("/token")
def get_token(response: Response, request: Request, client_id: str = "unknown"):
    """
    Consumer requests a token.
    Header 'X-Client-ID' handled via query param or header? 
    Let's accept query param for simplicity or check header if param missing.
    """
    # Prefer header if available
    cid = request.headers.get("X-Client-ID", client_id)
    
    # Track Client
    is_new = clients.touch(cid)
    if is_new:
        log_event("Connect", cid, "New connection.")
        
    # Consume Token
    allowed = bucket.consume(1)
    
    if allowed:
        return {"status": "ok", "remaining": bucket.tokens}
    else:
        log_event("LimitExceeded", cid, f"Rate limit hit ({bucket.rate}/s).")
        response.status_code = status.HTTP_429_TOO_MANY_REQUESTS
        return {"status": "limit_exceeded", "wait": 1.0/bucket.rate}

@app.get("/stats")
def get_stats():
    # Force refill to show current status
    now = time.time()
    elapsed = now - bucket.last_refill
    if elapsed > 0:
        bucket.tokens = min(bucket.capacity, bucket.tokens + (elapsed * bucket.rate))
        bucket.last_refill = now # Note: Reading side-effects, but acceptable for display accuracy

    return {
        "status": "running",
        "current_tps": bucket.rate,
        "tokens_left": bucket.tokens,
        "active_clients": len(clients.clients),
        "client_list": list(clients.clients.keys())
    }

@app.post("/config")
def update_config(tps: float):
    bucket.rate = float(tps)
    bucket.capacity = float(tps)
    logger.info(f"[Config] TPS Limit updated to {bucket.rate}/s")
    return {"status": "updated", "tps": bucket.rate}

if __name__ == "__main__":
    # Ensure no other process holds the port
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
