from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import asyncio
import logging
import json
import os
import sys
import yaml
import random
import string
from utils.data_loader import DataLoader

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.visualization import TradeVisualizationService

logger = logging.getLogger(__name__)

app = FastAPI()

# Security: Session Middleware moved to after auth_middleware

# Mount static files
app.mount("/static", StaticFiles(directory="web/static"), name="static")
templates = Jinja2Templates(directory="web/templates")

# Global variables
engine_instance = None
server_loop = None
visualization_service = None

# Authentication State
AUTH_OTP = None

def generate_otp():
    global AUTH_OTP
    AUTH_OTP = "".join([str(random.randint(0, 9)) for _ in range(6)])
    print("\n" + "="*40)
    print(f" [LOGIN OTP] 인증코드: {AUTH_OTP}")
    print("="*40 + "\n")
    return AUTH_OTP

# Logger setup to capture logs for streaming
class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.logs = []
        self.websockets = []

    def emit(self, record):
        try:
            log_entry = self.format(record)
            self.logs.append(log_entry)
            if len(self.logs) > 1000:
                self.logs.pop(0)
            
            # Broadcast to websockets safely
            if server_loop and server_loop.is_running():
                for ws in self.websockets:
                    asyncio.run_coroutine_threadsafe(ws.send_text(log_entry), server_loop)
        except Exception:
            # Prevent logging errors from crashing the app
            pass

list_handler = ListHandler()
list_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(list_handler)

# Also attach to uvicorn loggers
logging.getLogger("uvicorn").addHandler(list_handler)
logging.getLogger("uvicorn.access").addHandler(list_handler)

@app.on_event("startup")
async def startup_event():
    global server_loop
    server_loop = asyncio.get_running_loop()
    generate_otp() # Generate initial OTP on startup

# Middleware for Authentication
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Public routes
    if request.url.path in ["/login", "/api/login", "/favicon.ico"] or request.url.path.startswith("/static"):
        return await call_next(request)
    
    # Check session
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
    
    return await call_next(request)

# Security: Session Middleware (Must be added last to be executed first)
# In production, SECRET_KEY should be loaded from env vars
SECRET_KEY = "anti-stock-secret-key-change-me"
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/api/login")
async def login(request: Request):
    data = await request.json()
    input_otp = data.get("otp")
    
    if input_otp == AUTH_OTP:
        request.session["user"] = "admin"
        return {"status": "ok"}
    else:
        return {"status": "error", "message": "인증코드가 올바르지 않습니다."}

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/config")
async def get_config():
    if engine_instance:
        return engine_instance.config
    return {}

@app.post("/api/config")
async def update_config(request: Request):
    data = await request.json()
    if engine_instance:
        # data format: { "active_strategy": "...", "strategy_config": { ... } } or just config fragment
        
        # If active_strategy is provided, update it in system config or root config
        if "active_strategy" in data:
            engine_instance.config["active_strategy"] = data["active_strategy"]
            
        # If other config provided (strategy params)
        for key, value in data.items():
            if key != "active_strategy":
                engine_instance.update_strategy_config({key: value})

        # Save to file
        with open("config/strategies.yaml", "w", encoding="utf-8") as f:
            yaml.dump(engine_instance.config, f)
        return {"status": "ok"}
    return {"status": "error", "message": "Engine not initialized"}

@app.get("/api/system_config")
async def get_system_config():
    if engine_instance:
        return engine_instance.system_config
    return {}

@app.post("/api/system_config")
async def update_system_config(request: Request):
    data = await request.json()
    if engine_instance:
        engine_instance.system_config.update(data)
        # Save to file (assuming system_config is part of strategies.yaml or separate)
        # For now, we just update in memory and maybe save to strategies.yaml under 'system' key
        if "system" not in engine_instance.config:
            engine_instance.config["system"] = {}
        engine_instance.config["system"].update(data)
        
        with open("config/strategies.yaml", "w", encoding="utf-8") as f:
            yaml.dump(engine_instance.config, f)
        return {"status": "ok"}
    return {"status": "error", "message": "Engine not initialized"}

@app.get("/api/status")
async def get_status():
    if engine_instance:
        try:
            # Return all loaded strategies (since we only load the active one)
            active_strategies = list(engine_instance.strategies.keys())
            # print(f"DEBUG: Status - Strategies: {active_strategies}, Trading: {engine_instance.is_trading}")
            
            portfolio_data = {
                "cash": engine_instance.portfolio.cash,
                "deposit_d1": engine_instance.portfolio.deposit_d1,
                "deposit_d2": engine_instance.portfolio.deposit_d2,
                "total_asset": engine_instance.portfolio.total_asset,
                "positions": [
                    {
                        "symbol": p.symbol,
                        "name": p.name,
                        "qty": p.qty,
                        "avg_price": p.avg_price,
                        "current_price": p.current_price,
                        "pnl_pct": (p.current_price - p.avg_price)/p.avg_price*100 if p.avg_price > 0 else 0
                    } for p in engine_instance.portfolio.positions.values()
                ]
            }
            # print(f"DEBUG: Status - Portfolio Cash: {portfolio_data['cash']}")
            
            return {
                "is_running": engine_instance.is_trading, # UI expects is_running to mean "trading active"
                "active_strategies": active_strategies,
                "portfolio": portfolio_data
            }
        except Exception as e:
            print(f"DEBUG: Error in get_status: {e}")
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
            
    print("DEBUG: engine_instance is None")
    return {"status": "stopped"}

@app.get("/api/logs/download")
async def download_logs():
    from fastapi.responses import FileResponse
    log_file = "anti_stock.log"
    if os.path.exists(log_file):
        return FileResponse(log_file, media_type='text/plain', filename="anti_stock.log")
    return {"status": "error", "message": "Log file not found"}

@app.get("/api/chart/data")
async def get_chart_data(symbol: str, timeframe: str = "1m", lookback: int = 300):
    if visualization_service:
        try:
            data = visualization_service.get_chart_data(symbol, timeframe, lookback)
            return data
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Service not initialized"}

@app.get("/manual", response_class=HTMLResponse)
async def get_manual(request: Request):
    return templates.TemplateResponse("manual.html", {"request": request})

@app.post("/api/control")
async def control_engine(action: dict):
    # action: { "command": "start" | "stop" | "restart" }
    cmd = action.get("command")
    if engine_instance:
        import threading
        if cmd == "start":
            engine_instance.start_trading()
        elif cmd == "stop":
            engine_instance.stop_trading()
        elif cmd == "restart":
            # Restart triggers re-init in the main loop
            engine_instance.restart()
    return {"status": "ok"}

@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    list_handler.websockets.append(websocket)
    try:
        # Send recent logs
        for log in list_handler.logs[-50:]:
            await websocket.send_text(log)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        list_handler.websockets.remove(websocket)

def start_server(engine):
    global engine_instance, visualization_service
    engine_instance = engine
    visualization_service = TradeVisualizationService(engine)
    import uvicorn
    # Run in a separate thread
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    server.run()

@app.post("/api/debug/inject_trades")
async def inject_trades(request: Request):
    """
    Debug endpoint to inject dummy trade data for testing.
    Creates 5 random trade events for the last hour.
    """
    if engine_instance:
        try:
            from core.visualization import TradeEvent
            from datetime import datetime, timedelta
            import uuid
            import random

            # Default symbol for testing
            symbol = "005930" 
            
            # Generate 5 events
            base_time = datetime.now()
            
            new_events = []
            for i in range(5):
                # Random time within last 60 minutes
                event_time = base_time - timedelta(minutes=random.randint(1, 60))
                side = random.choice(["BUY", "SELL"])
                price = 60000 + random.randint(-1000, 1000)
                qty = random.randint(1, 10)
                
                event = TradeEvent(
                    event_id=str(uuid.uuid4()),
                    timestamp=event_time,
                    symbol=symbol,
                    strategy_id="debug_manual",
                    event_type="ORDER_FILLED",
                    side=side,
                    price=float(price),
                    qty=qty,
                    order_id=f"debug_{uuid.uuid4().hex[:8]}",
                    meta={"type": "LIMIT"}
                )
                new_events.append(event)
            
            # Append to engine history
            engine_instance.trade_history.extend(new_events)
            logger.info(f"DEBUG: Injected {len(new_events)} dummy trades for {symbol}")
            
            return {"status": "ok", "message": f"Injected {len(new_events)} trades", "count": len(new_events)}
        except Exception as e:
            logger.error(f"Failed to inject trades: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Engine not initialized"}

# Backtest APIs

@app.post("/api/backtest/check_data")
async def check_data(request: Request):
    data = await request.json()
    symbol = data.get("symbol")
    start = data.get("start")
    end = data.get("end")
    
    loader = DataLoader()
    exists = loader.check_availability(symbol, start, end)
    return {"status": "ok", "exists": exists}

@app.post("/api/backtest/download")
async def download_data(request: Request):
    data = await request.json()
    symbol = data.get("symbol")
    start = data.get("start")
    end = data.get("end")
    
    loader = DataLoader()
    try:
        df = loader.download_data(symbol, start, end)
        return {"status": "ok", "count": len(df)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/backtest/run")
async def run_backtest_api(request: Request):
    if not engine_instance:
         return {"status": "error", "message": "Engine not initialized"}

    data = await request.json()
    strategy_id = data.get("strategy_id")
    symbol = data.get("symbol")
    start = data.get("start")
    end = data.get("end")
    initial_cash = int(data.get("initial_cash", 100000000))
    
    try:
        result = engine_instance.run_backtest(strategy_id, symbol, start, end, initial_cash)
        if "error" in result:
             return {"status": "error", "message": result["error"]}
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error(f"Backtest API Failed: {e}")
        import traceback
        with open("debug_stack.txt", "w", encoding="utf-8") as f:
            f.write(str(e) + "\n" + traceback.format_exc())
        logger.error(traceback.format_exc())
        return {"status": "error", "message": repr(e)}
