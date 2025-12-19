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
from datetime import datetime
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
    # Disable access log to prevent "GET /api/status" spam
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="warning", access_log=False)
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

# TPS Server Proxy & Monitoring
@app.get("/api/tps/stats")
async def get_tps_stats():
    import requests
    try:
        # Resolve TPS URL from Engine Config
        tps_base_url = "http://localhost:9000"
        if engine_instance:
             tps_base_url = engine_instance.system_config.get("tps_server_url", "http://localhost:9000")
        
        # Proxy to TPS Server
        resp = requests.get(f"{tps_base_url}/stats", timeout=0.5)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        # If server is down
        return {"status": "error", "message": "TPS Server Unreachable"}
    return {"status": "error", "message": "Connect Error"}

@app.get("/api/tps/logs/download")
async def download_tps_logs():
    from fastapi.responses import FileResponse
    log_file = os.path.join("logs", "tps_server.log")
    if os.path.exists(log_file):
        # Serve file
        filename = f"tps_server_{datetime.now().strftime('%Y%m%d_%H%M')}.log"
        return FileResponse(log_file, media_type='text/plain', filename=filename)
    return {"status": "error", "message": "TPS Log file not found"}

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
    Get trade history from Engine
    """
    if engine_instance:
        try:
            trades = engine_instance.trade_history
            
            # Convert to list of dicts suitable for JSON
            data = []
            
            # Date Filtering (start, end are YYYYMMDD or YYYY-MM-DD)
            # Normalize to datetime for comparison
            s_dt = None
            e_dt = None
            if start:
                start = start.replace("-", "")
                try: s_dt = datetime.strptime(start, "%Y%m%d")
                except: pass
            if end:
                end = end.replace("-", "")
                try: 
                    # End date is inclusive, so set to end of day if we compare timestamps
                    e_dt_base = datetime.strptime(end, "%Y%m%d")
                    e_dt = e_dt_base.replace(hour=23, minute=59, second=59)
                except: pass
                
            for t in trades:
                # 1. Filter by Symbol
                if symbol and t.symbol != symbol:
                    continue
                
                # 2. Filter by Date
                if s_dt and t.timestamp < s_dt:
                    continue
                if e_dt and t.timestamp > e_dt:
                    continue
                
                # 3. Filter out invalid/ghost entries (Price 0)
                if t.price <= 0:
                    continue
                
                item = t.__dict__.copy()
                
                # Format Timestamp for display
                if isinstance(t.timestamp, datetime):
                    item['timestamp'] = t.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    item['timestamp'] = str(t.timestamp)
                    
                data.append(item)
            
            # Sort descending (latest first)
            data.sort(key=lambda x: x['timestamp'], reverse=True)
            
            # Calculate summary metrics on the filtered set
            total_pnl = 0
            win_count = 0
            loss_count = 0
            total_count = len(data)
            
            # Only count closed trades (SELL) for PnL stats? Or assume PnL is tracked in Sell events?
            # TradeEvent doesn't explicitly store PnL unless we put it in meta or calculate it.
            # In engine.py record_position_event, we didn't explicitly add PnL to TradeEvent (it's in change_info but not mapped to a top-level field).
            # We should check if 'position_info' in meta has 'pnl' or 'realized_pnl'.
            # Looking at portfolio.py, SELL event has 'realized_pnl' in change_info.
            
            for item in data:
                # Inject Stock Name if missing
                if 'name' not in item or not item['name']:
                    if engine_instance and engine_instance.market_data:
                        item['name'] = engine_instance.market_data.get_stock_name(item['symbol'])
                
                # PnL Logic: Currently disabled for pure sync as we lack cost basis.
                # Future: Implement inquire-ccld-pnl for accurate PnL history.
                pass

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
             await websocket.send_json({"type": "result", "result": result})
             
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
