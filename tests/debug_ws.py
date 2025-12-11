
import asyncio
import websockets
import json
import sys

async def test_backtest_ws():
    uri = "ws://localhost:8000/ws/backtest"
    
    # Payload matching the structure expected by server.py
    # payload = await websocket.receive_json()
    # strategy_id = data.get("strategy_id")
    # symbol = data.get("symbol")
    # start_date = data.get("start_date")
    # end_date = data.get("end_date")
    # initial_cash = int(data.get("initial_cash", 100000000))
    # params = data.get("params", {}) 

    data = {
        "strategy_id": "ma_trend",
        "symbol": "005930",
        "start": "20241201",
        "end": "20241210",
        "initial_cash": 100000000,
        "params": {}
    }

    try:
        print(f"Connecting to {uri}...")
        async with websockets.connect(uri) as websocket:
            print("Connected. Sending payload...")
            await websocket.send(json.dumps(data))
            
            while True:
                try:
                    message = await websocket.recv()
                    msg_data = json.loads(message)
                    msg_type = msg_data.get("type")
                    
                    if msg_type == "progress":
                        print(f"Progress: {msg_data.get('data')}%", end="\r")
                    elif msg_type == "trade_event":
                        print(f"\nTrade: {msg_data.get('data')}")
                    elif msg_type == "result":
                        print("\nBacktest Finished!")
                        print(msg_data.get('result'))
                        break
                    elif msg_type == "error":
                        print(f"\nERROR RECEIVED: {msg_data.get('message')}")
                        break
                    else:
                        print(f"\nUnknown message: {message}")
                        
                except websockets.exceptions.ConnectionClosed:
                    print("\nConnection closed by server")
                    break
    except Exception as e:
        print(f"\nFailed to connect or run: {e}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_backtest_ws())
