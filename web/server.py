from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse, StreamingResponse
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
from datetime import datetime
import io
import pandas as pd
from utils.data_loader import DataLoader

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.visualization import TradeVisualizationService
from core.dao import TradeDAO, WatchlistDAO, ChecklistDAO
from core import interface as ka

logger = logging.getLogger(__name__)

app = FastAPI()


# Security: Session Middleware moved to after auth_middleware

# Mount static files
app.mount("/static", StaticFiles(directory="web/static"), name="static")
templates = Jinja2Templates(directory=["web/templates", "labs/lab1"])

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

    if engine_instance and hasattr(engine_instance, 'telegram'):
        engine_instance.telegram.send_otp(AUTH_OTP)

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
        return RedirectResponse(url="/login", status_code=303)

    return await call_next(request)

# PWA Static Routes
@app.get("/manifest.json")
@app.get("/static/manifest.json")
async def get_manifest():
    return FileResponse("web/static/manifest.json", media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})

@app.get("/sw.js")
@app.get("/static/sw.js")
async def get_sw():
    return FileResponse("web/static/sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})

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
    title = "Anti Stock Trading" # Default
    if engine_instance:
        env_type = engine_instance.system_config.get("env_type", "paper")
        if env_type in ["prod", "real"]:
            title = "Bot Stock Trading"
        else:
            title = "Anti Stock Trading"
            
    return templates.TemplateResponse("index.html", {"request": request, "app_title": title})

# Watchlist & Stock Master APIs
@app.get("/api/stocks")
async def get_all_stocks():
    """Get all stocks (Master Data)"""
    if engine_instance and engine_instance.market_data:
        return engine_instance.market_data.get_master_list()
    return []

@app.get("/api/watchlist")
async def get_watchlist():
    """Get Saved Watchlist from DB (Non-blocking)"""
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, WatchlistDAO.get_all_symbols)
    except Exception as e:
        logger.error(f"Failed to get watchlist: {e}")
        return []

@app.post("/api/watchlist")
async def update_watchlist(request: Request):
    """Update Watchlist"""
    data = await request.json()
    new_list = data.get("watchlist", [])
    if engine_instance:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, engine_instance.update_watchlist, new_list)
        return {"status": "ok", "count": len(new_list)}
    return {"status": "error", "message": "Engine not initialized"}

@app.post("/api/watchlist/import")
async def import_watchlist():
    """Import from Broker"""
    if engine_instance:
        try:
            loop = asyncio.get_running_loop()
            total, added = await loop.run_in_executor(None, engine_instance.import_broker_watchlist)
            return {"status": "ok", "total": total, "added": added}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Engine not initialized"}

@app.post("/api/market/data")
async def get_market_data_batch(request: Request):
    """
    Get detailed market data for a list of symbols.
    Includes: Current Price, Change Rate, MA20, Sparkline (30d)
    This might be slow if too many symbols. Limit recommended.
    """
    data = await request.json()
    symbols = data.get("symbols", [])

    if engine_instance and engine_instance.market_data:
        md = engine_instance.market_data

        def _fetch_batch_data():
            import time
            results = []
            for symbol in symbols:
                # [Throttle] Pace requests to prevent "Global Rate Limit" bursts
                time.sleep(0.2)

                try:
                    # 1. Basic Info (Name, Price)
                    name = md.get_stock_name(symbol)

                    # Fetch Daily Bars for MA20 & Sparkline (Cached)
                    # Lookback 30 days
                    # This is the heavy part (DB/API I/O)
                    df = md.get_bars(symbol, timeframe="1d", lookback=30)

                    current_price = 0
                    change_rate = 0
                    ma20 = 0
                    sparkline = []

                    # Check Holding Status
                    is_held = False
                    if engine_instance and engine_instance.portfolio:
                        if symbol in engine_instance.portfolio.positions:
                            is_held = True

                    if not df.empty:
                        # Sparkline: Close prices
                        sparkline = df['close'].tolist()

                        # MA20: Calculate from last 20 close prices
                        if len(df) >= 20:
                            ma20 = df['close'].tail(20).mean()
                        else:
                            ma20 = df['close'].mean() # Approx

                        last_bar = df.iloc[-1]
                        current_price = float(last_bar['close'])

                        # Calculate change rate (vs prev day)
                        if len(df) >= 2:
                            prev_close = float(df.iloc[-2]['close'])
                            if prev_close > 0:
                                change_rate = (current_price - prev_close) / prev_close * 100

                    item = {
                        "no": 0, # Frontend will assign
                        "name": name,
                        "code": symbol,
                        "price": current_price,
                        "change_rate": round(change_rate, 2),
                        "ma20": round(ma20, 0),
                        "sparkline": sparkline,
                        "is_held": is_held
                    }
                    results.append(item)

                except Exception as e:
                    logger.error(f"Error fetching data for {symbol}: {e}")
                    results.append({
                        "code": symbol,
                        "error": str(e),
                        "name": md.get_stock_name(symbol)
                    })
            return results

        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, _fetch_batch_data)

        return {"status": "ok", "data": results}

    return {"status": "ok", "data": []}

@app.get("/api/config")
async def get_config():
    if engine_instance:
        cfg = engine_instance.config.copy()

        # Filter out system keys to provide a clean list of strategies
        # User wants 'common' to be editable, so we include it.
        system_keys = ["system", "database", "active_strategy"]
        strategies_list = [k for k in cfg.keys() if k not in system_keys and isinstance(cfg[k], dict)]

        cfg["strategies_list"] = strategies_list
        return cfg
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

from fastapi.responses import JSONResponse

@app.get("/api/system/settings")
async def get_system_settings():
    if engine_instance:
        cfg = engine_instance.system_config.copy()
        return JSONResponse(content=cfg)
    return JSONResponse(content={})

@app.post("/api/system_config")
async def update_system_config(request: Request):
    data = await request.json()
    if engine_instance:
        # Delegate update and saving to Engine to handle config splitting (strategies vs secrets)
        engine_instance.update_system_config(data)
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
                "positions": sorted([
                    {
                        "symbol": p.symbol,
                        "name": p.name,
                        "qty": p.qty,
                        "avg_price": p.avg_price,
                        "current_price": p.current_price,
                        "pnl_pct": (p.current_price - p.avg_price)/p.avg_price*100 if p.avg_price > 0 else 0,
                        "holding_days": int((datetime.now().timestamp() - p.first_acquired_at) / 86400) if p.first_acquired_at > 0 else 0
                    } for p in engine_instance.portfolio.positions.values()
                ], key=lambda x: x['name'])
            }


            # Calculate Total Evaluation Amount (Sum of Current Value of Stocks)
            total_eval_amt = sum(p.current_price * p.qty for p in engine_instance.portfolio.positions.values())
            portfolio_data["total_eval_amt"] = total_eval_amt
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
    log_file = os.path.join("logs", "anti_stock.log")
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

@app.get("/manual/backtest_process", response_class=HTMLResponse)
async def get_backtest_process(request: Request):
    return templates.TemplateResponse("backtest_process.html", {"request": request})

@app.get("/lab1", response_class=HTMLResponse)
async def get_lab1(request: Request):
    return templates.TemplateResponse("lab1.html", {"request": request})

@app.get("/api/lab1/config")
async def get_lab1_config():
    """Read strategies_sandbox.yaml -> lab1_cond.yaml"""
    config_path = os.path.join("labs", "lab1", "lab1_cond.yaml")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

@app.post("/api/lab1/config")
async def update_lab1_config(request: Request):
    """Write strategies_sandbox.yaml -> lab1_cond.yaml"""
    try:
        data = await request.json()
        config_path = os.path.join("labs", "lab1", "lab1_cond.yaml")
        # Ensure directory exists (though it should)
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)
            
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Failed to save lab1 config: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/lab1/llm")
async def generate_llm_condition(request: Request):
    """
    Generate Python condition from natural language using lab1_llm.py
    """
    try:
        data = await request.json()
        description = data.get("text")
        if not description:
            return {"status": "error", "message": "설명 텍스트가 필요합니다."}

        # Dynamic import to avoid top-level dependency if possible or just straightforward import
        # Since lab1_llm.py is in labs/lab1, we need to adjust path or treat as package
        from labs.lab1.lab1_llm import ConditionGenerator
        
        agent = ConditionGenerator()
        code = agent.generate_condition(description)
        
        if code.startswith("Error"):
            return {"status": "error", "message": code}
            
        return {"status": "ok", "code": code}
    except ImportError:
        return {"status": "error", "message": "lab1_llm 모듈을 찾을 수 없거나 의존성(google-generativeai)이 설치되지 않았습니다."}
    except Exception as e:
        logger.error(f"LLM Generation Error: {e}")
        return {"status": "error", "message": str(e)}

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

@app.post("/api/order/sell_immediate")
async def sell_immediate(request: Request):
    """Sell a stock immediately at market price"""
    data = await request.json()
    symbol = data.get("symbol")
    qty = data.get("qty")
    
    if not symbol or not qty:
        return {"status": "error", "message": "Symbol and quantity are required"}
    
    if engine_instance and engine_instance.broker:
        try:
            # qty can be passed as string from JS, so convert to int
            success = engine_instance.broker.sell_market(symbol, int(qty), tag="manual_sell")
            if success:
                return {"status": "ok"}
            else:
                return {"status": "error", "message": "Order failed"}
        except Exception as e:
            logger.error(f"Manual sell failed: {e}")
            return {"status": "error", "message": str(e)}
            
    return {"status": "error", "message": "Engine or Broker not initialized"}

@app.get("/api/checklist")
async def get_checklist():
    # Remove inner import - ChecklistDAO is already imported at top level

    # Use ChecklistDAO directly, which now returns dicts
    # Run in executor to avoid blocking main thread with DB IO
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, ChecklistDAO.get_all)
    return {"status": "ok", "data": data}

@app.post("/api/checklist")
async def add_checklist_item(request: Request):
    data = await request.json()
    text = data.get("text")
    if not text:
        return {"status": "error", "message": "Text is required"}

    loop = asyncio.get_running_loop()
    item = await loop.run_in_executor(None, ChecklistDAO.add_item, text)

    if item:
        return {"status": "ok", "data": item} # item is now a dict
    return {"status": "error", "message": "Failed to save to DB"}

@app.post("/api/checklist/{item_id}/toggle")
async def toggle_checklist_item(item_id: int):
    # Retrieve current status first? Or pass new status?
    # Simpler: Pass new status in body or just toggle?
    # The UI usually knows the new desired state.
    # Let's use a body for explicit state, but 'toggle' implies switching.
    # Let's support explicit update via body.
    # Wait, GET/POST strictly?
    # Let's make it robust: Read body for 'is_done'.
    pass

@app.post("/api/checklist/update")
async def update_checklist_item(request: Request):
    data = await request.json()
    item_id = data.get("id")
    is_done = data.get("is_done")

    loop = asyncio.get_running_loop()
    success = await loop.run_in_executor(None, ChecklistDAO.update_status, item_id, is_done)
    return {"status": "ok" if success else "error"}

@app.delete("/api/checklist/{item_id}")
async def delete_checklist_item(item_id: int):
    loop = asyncio.get_running_loop()
    success = await loop.run_in_executor(None, ChecklistDAO.delete_item, item_id)
    return {"status": "ok" if success else "error"}

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
    
    # Read port from system config (merged from json)
    port = int(engine.system_config.get("server_port", 8000))

    # Run in a separate thread
    # Disable access log to prevent "GET /api/status" spam
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning", access_log=False)
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

            # Update memory
            engine_instance.trade_history.append(event)
            logger.info(f"DEBUG: Injected {len(new_events)} dummy trades for {symbol}")

            return {"status": "ok", "message": f"Injected {len(new_events)} trades", "count": len(new_events)}
        except Exception as e:
            logger.error(f"Failed to inject trades: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Engine not initialized"}

# TPS Server Proxy & Monitoring - Legacy implementations removed to avoid duplication
# New implementation uses kis_api.rate_limiter directly


# Backtest APIs

@app.post("/api/backtest/check_data")
async def check_data(request: Request):
    data = await request.json()
    symbol = data.get("symbol")
    start = data.get("start")
    end = data.get("end")
    strategy_id = data.get("strategy_id")

    # Enable Timeframe detection
    timeframe = "D"
    if strategy_id:
        try:
             import yaml
             config_path = os.path.join(os.getcwd(), "config", "strategies.yaml")
             if os.path.exists(config_path):
                 with open(config_path, "r", encoding="utf-8") as f:
                     config = yaml.safe_load(f)
                     if config and strategy_id in config:
                         timeframe = config[strategy_id].get("timeframe", "D")
        except:
             pass

    loader = DataLoader()
    exists = loader.check_availability(symbol, start, end, timeframe=timeframe)
    return {"status": "ok", "exists": exists}

@app.post("/api/backtest/download")
async def download_data(request: Request):
    data = await request.json()
    symbol = data.get("symbol")
    start = data.get("start")
    end = data.get("end")
    strategy_id = data.get("strategy_id")
    
    # Enable Timeframe detection
    timeframe = "D"
    if strategy_id:
        try:
             import yaml
             config_path = os.path.join(os.getcwd(), "config", "strategies.yaml")
             if os.path.exists(config_path):
                 with open(config_path, "r", encoding="utf-8") as f:
                     config = yaml.safe_load(f)
                     if config and strategy_id in config:
                         timeframe = config[strategy_id].get("timeframe", "D")
        except:
             pass

    loader = DataLoader()
    try:
        df = loader.download_data(symbol, start, end, timeframe=timeframe)
        return {"status": "ok", "count": len(df)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/backtest/export")
async def export_backtest_data(request: Request):
    try:
        body = await request.json()
        symbol = body.get("symbol")
        start_date = body.get("start")
        end_date = body.get("end")
        strategy_id = body.get("strategy_id")
        initial_cash = int(body.get("initial_cash", 100000000))

        # 1. Load Data & Calculate Indicators
        data_loader = DataLoader()

        st_conf = {}
        if engine_instance:
             st_conf = engine_instance.config.get(strategy_id, {})

        tf = st_conf.get("timeframe", "D")

        try:
             import datetime
             from datetime import timedelta
             buffer_days = 60 if tf == "D" else 5
             s_dt = datetime.datetime.strptime(start_date, "%Y%m%d")
             buffer_date = (s_dt - timedelta(days=buffer_days)).strftime("%Y%m%d")
        except:
             buffer_date = start_date

        # Try loading local data first to avoid API rate limits
        df = data_loader.load_data(symbol, buffer_date, end_date, timeframe=tf)

        # Only download if local data is missing
        if df.empty:
            logger.info(f"Local data missing for export, attempting download: {symbol}")
            df = data_loader.download_data(symbol, buffer_date, end_date, timeframe=tf)

        if df.empty:
            return {"status": "error", "message": "No data found"}

        # Calculate Indicators
        df['ma5'] = df['close'].rolling(window=5).mean().fillna(0)
        df['ma20'] = df['close'].rolling(window=20).mean().fillna(0)
        df['vol_ma20'] = df['volume'].rolling(window=20).mean().fillna(0)
        df = df.fillna(0)

        # 2. Run Backtest
        if engine_instance:
            result = engine_instance.run_backtest(strategy_id, symbol, start_date, end_date, initial_cash)
        else:
            return {"status": "error", "message": "Engine not initialized"}

        if "error" in result:
             return {"status": "error", "message": result["error"]}

        history = result.get("history", [])

        # 3. Merge History into DataFrame
        df['action'] = ""
        df['trade_qty'] = 0
        df['trade_price'] = 0

        # Map history to dict keyed by timestamp
        for trade in history:
            ts = trade['timestamp']
            parts = ts.split(" ")
            DATE = parts[0]
            TIME = parts[1] if len(parts) > 1 else None

            # Simple matching for Daily
            mask = (df['date'] == DATE)
            if TIME and 'time' in df.columns:
                 # Intraday match: ensure time column exists and matches
                 mask = mask & (df['time'] == TIME)

            if mask.any():
                idx = df[mask].index[0]
                existing_action = df.at[idx, 'action']
                new_action = trade['side']
                if existing_action:
                    df.at[idx, 'action'] = f"{existing_action},{new_action}"
                else:
                    df.at[idx, 'action'] = new_action

                df.at[idx, 'trade_qty'] = trade['qty']
                df.at[idx, 'trade_price'] = trade['price']

        # 4. Generate Excel
        import io
        import pandas as pd
        from fastapi.responses import StreamingResponse

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Backtest_Data', index=False)

            metrics = result.get("metrics", {})
            m_df = pd.DataFrame([metrics])
            m_df.to_excel(writer, sheet_name='Metrics', index=False)

        output.seek(0)

        filename = f"backtest_{symbol}_{strategy_id}_{start_date}_{end_date}.xlsx"
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"'
        }

        return StreamingResponse(output, headers=headers, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    except Exception as e:
        logger.error(f"Export Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}

@app.post("/api/backtest/data")
async def get_backtest_data(request: Request):
    data = await request.json()
    symbol = data.get("symbol")
    start = data.get("start")
    end = data.get("end")

    try:
        loader = DataLoader()

        # Determine timeframe from strategy config if provided
        strategy_id = data.get("strategy_id")
        timeframe = "D" # default

        if strategy_id:
            try:
                import yaml
                config_path = os.path.join(os.getcwd(), "config", "strategies.yaml")
                if os.path.exists(config_path):
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = yaml.safe_load(f)
                        if config and strategy_id in config:
                            timeframe = config[strategy_id].get("timeframe", "D")
            except Exception as e:
                logging.warning(f"Failed to load strategy config: {e}")

        # Load with a bit of buffer for accurate MAs if possible?
        # But UI usually requests specific range. calculate MA on visible range is fine for now.
        # Or load calculation buffer? DataLoader.load_data filters by date.
        # Standard practice: Load extra, calc MA, slice.
        # But DataLoader doesn't support "load extra" easily without knowing dates.
        # We will just calc on what we have. First 20 rows might have invalid MAs.
        df = loader.load_data(symbol, start, end, timeframe=timeframe)

        if not df.empty:
            # Calculate MAs
            df['ma5'] = df['close'].rolling(window=5).mean().fillna(0)
            df['ma20'] = df['close'].rolling(window=20).mean().fillna(0)
            df['vol_ma20'] = df['volume'].rolling(window=20).mean().fillna(0)

            # Convert to records (handle NaNs? fillna(0) done)
            # Replace NaN/Info with None for JSON standard compliance if needed, but to_dict handles it.
            # Handle Timestamp objects if any (to_dist 'records' keeps them?)
            # Usually need to convert index/date to string if it's not.
            # DataLoader usually returns 'date' column as string or datetime?
            # We need to ensure it's JSON serializable.
            # Assuming loader returns standardized dataframe.

            # Drop NaN rows at the start if necessary or keep them as 0
            df = df.fillna(0)

            records = df.to_dict('records')
            return {"status": "ok", "data": records}

        return {"status": "error", "message": "No data found"}

    except Exception as e:
        logging.error(f"Data Fetch Error: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}

@app.get("/api/journal/trades")
async def get_journal_trades(start: str = None, end: str = None, symbol: str = None):
    """
    Get trade history from DB
    """
    if engine_instance:
        try:
            # Check DB Connection state via simple count

            # Check DB Connection state via simple count
            # total = TradeDAO.get_all_trades_count()

            # Convert date strings to datetime objects for DAO
            s_dt = None
            e_dt = None
            if start:
                try:
                    s_dt = datetime.strptime(start.replace("-", ""), "%Y%m%d")
                except: pass
            if end:
                try:
                    e_dt_base = datetime.strptime(end.replace("-", ""), "%Y%m%d")
                    e_dt = e_dt_base.replace(hour=23, minute=59, second=59)
                except: pass


            # Use In-Memory Cache for Speed
            # Filter and sort in memory
            # This is much faster than DB query for small datasets (1000 items)
            trades = engine_instance.trade_history

            # Apply filters if needed
            if symbol or start or end:
                filtered = []
                for t in trades:
                    # Symbol/Name Filter
                    if symbol:
                        # Get Name
                        t_name = ""
                        if engine_instance.market_data:
                            t_name = engine_instance.market_data.get_stock_name(t.symbol)

                        # Check partial match for Symbol OR Name
                        # user input 'symbol' is the query
                        if (symbol not in t.symbol) and (symbol not in t_name):
                            continue

                    # Date Filter
                    if s_dt and t.timestamp < s_dt:
                        continue
                    if e_dt and t.timestamp > e_dt:
                        continue
                    filtered.append(t)
                trades = filtered

            # Sort by Timestamp DESC? (Already sorted in load?)
            # Usually memory list is sorted by time (newest first or last?)
            # engine.trade_history is prepended (newest at index 0).
            # So it is already sorted DESC.

            data = []
            for t in trades:
                # [FIX] Filter out Order Submission events (Duplicates)
                if t.price <= 0:
                    continue
                if t.event_type == "ORDER_SUBMITTED":
                    continue
                if t.meta and t.meta.get("event_type") == "ORDER_SUBMITTED":
                    continue

                # Convert SQLAlchemy Model to Dict
                item = {
                    "event_id": t.event_id,
                    "timestamp": t.timestamp,
                    "symbol": t.symbol,
                    "strategy_id": t.strategy_id,
                    "side": t.side,
                    "price": t.price,
                    "qty": t.qty,
                    "exec_amt": t.exec_amt,
                    "pnl": t.pnl,
                    "revenue_rate": t.pnl_pct, # Frontend expects revenue_rate or pnl_pct
                    "order_id": t.order_id,
                    "meta": t.meta
                }

                # Format Timestamp
                if isinstance(item['timestamp'], datetime):
                    item['timestamp'] = item['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
                else:
                    item['timestamp'] = str(item['timestamp'])

                # Inject Name
                if engine_instance.market_data:
                    item['name'] = engine_instance.market_data.get_stock_name(t.symbol)

                data.append(item)

            return {"status": "ok", "data": data}

        except Exception as e:
            logger.error(f"Journal Error: {e}")
            return {"status": "error", "message": str(e)}

    return {"status": "error", "message": "Engine not initialized"}

@app.post("/api/journal/sync")
async def sync_journal(request: Request):
    data = await request.json()
    start = data.get("start")
    end = data.get("end")

    if engine_instance:
        try:
            # Run in executor to avoid blocking
            loop = asyncio.get_running_loop()
            count = await loop.run_in_executor(None, lambda: engine_instance.sync_trade_history(start, end))

            return {"status": "ok", "message": f"Synced {count} trades.", "count": count}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return {"status": "error", "message": "Engine not initialized"}

@app.websocket("/ws/backtest")
async def backtest_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        # 1. Receive Configuration
        data = await websocket.receive_json()

        strategy_id = data.get("strategy_id")
        symbol = data.get("symbol")
        start = data.get("start")
        end = data.get("end")
        initial_cash = int(data.get("initial_cash", 100000000))

        if not engine_instance:
             await websocket.send_json({"type": "error", "message": "Engine not initialized"})
             return

        # Callback for progress and events
        def progress_callback(event_type, payload):
            # Run in main loop
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({"type": event_type, "data": payload}),
                server_loop
            )

        # 2. Run Backtest (Blocking, so run in Executor)
        # engine_instance.run_backtest is synchronous
        loop = asyncio.get_running_loop()

        result = await loop.run_in_executor(
            None,
            lambda: engine_instance.run_backtest(
                strategy_id, symbol, start, end, initial_cash,
                progress_callback=progress_callback
            )
        )

        # 3. Send Final Result
        if "error" in result:
             await websocket.send_json({"type": "error", "message": result["error"]})
        else:
             # Sanitize result to handle NumPy types
             safe_result = json_compatible(result)
             await websocket.send_json({"type": "result", "result": safe_result})

    except WebSocketDisconnect:
        logger.info("Backtest WebSocket disconnected")
    except Exception as e:
        logger.error(f"Backtest WS Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass

def json_compatible(obj):
    """
    Recursively convert NumPy types to Python native types for JSON serialization.
    """
    if isinstance(obj, dict):
        return {k: json_compatible(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [json_compatible(v) for v in obj]
    elif hasattr(obj, 'item'): # NumPy scalar
        return obj.item()
    elif hasattr(obj, 'tolist'): # NumPy array/Series
        return obj.tolist()
    else:
        return obj

@app.post("/api/backtest/export")
async def export_backtest_result(request: Request):
    """
    백테스트 결과를 엑셀로 내보냅니다.
    요청 바디: { "history": [...simulated trades...], "config": {...} }
    """
    try:
        data = await request.json()
        history = data.get("history", [])
        config = data.get("config", {})

        if not history:
             return JSONResponse({"status": "error", "message": "No history data to export"}, status_code=400)

        # 1. Convert to DataFrame
        df = pd.DataFrame(history)

        # 2. Rename & Reorder Columns
        # 기본 매매 정보
        col_map = {
            "timestamp": "일자/시간",
            "symbol": "종목코드",  # 종목명은 별도로 넣어야 함 (history에 있나? 보통 없으므로 로직 필요)
            "side": "구분", # 1: 매수, 2: 매도
            "qty": "수량",
            "price": "체결가",
            "pnl_pct": "수익률(%)",
            "tag": "태그",
            
            # 기술적 지표 (Simulated)
            "ma_short": "이평(Short)",
            "ma_long": "이평(Long)",
            "volume": "거래량",
            "avg_vol": "평균거래량(20)",
            "adx": "ADX",
            "slope": "기울기",
            
            # 판단 지표
            "rr_ratio": "RR(손익비)",
            "perf_weight": "비중가중치",
            "action": "Action",
            "msg": "로그(판단근거)"
        }
        
        # 실제 데이터에 있는 컬럼만 선택
        existing_cols = [c for c in col_map.keys() if c in df.columns]
        df = df[existing_cols].rename(columns=col_map)
        
        # 3. Value Formatting
        # 구분: 1->매수, 2->매도
        if "구분" in df.columns:
            df["구분"] = df["구분"].apply(lambda x: "매수" if str(x) == "1" or str(x) == "BUY" else "매도" if str(x) == "2" or str(x) == "SELL" else x)
            
        # 종목명 추가 (엔진이 있으면 조회, 없으면 패스)
        if engine_instance and "종목코드" in df.columns:
            # engine_instance.market_data might be available
             def get_name(code):
                 return engine_instance.market_data.get_stock_name(code)
             
             df.insert(1, "종목명", df["종목코드"].apply(get_name))

        # 4. Create Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Backtest_Result')
            
            # Configuration Sheet (User Request: Snapshot)
            if config:
                cfg_df = pd.DataFrame([{"Parameter": k, "Value": str(v)} for k, v in config.items()])
                cfg_df.to_excel(writer, index=False, sheet_name='Configuration')
                
            # Auto-adjust columns width (Basic)
            worksheet = writer.sheets['Backtest_Result']
            for i, col in enumerate(df.columns):
                width = max(df[col].astype(str).map(len).max(), len(col)) + 2
                worksheet.set_column(i, i, width)

        output.seek(0)
        
        # 5. Return Response
        filename = f"Backtest_Result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"'
        }
        return StreamingResponse(output, headers=headers, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    except Exception as e:
        logger.error(f"Export Error: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
