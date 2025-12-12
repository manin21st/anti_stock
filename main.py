import logging
import threading
import sys
import os
from core.engine import Engine
from strategies.ma_trend import MovingAverageTrendStrategy
from strategies.bollinger_mr import BollingerMeanReversion
from strategies.breakout import PreviousHighBreakout
from strategies.vwap_scalping import VWAPScalping
from web.server import start_server

# Setup Logging
# Setup Logging
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Stream Handler (Console)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
root_logger.addHandler(stream_handler)

# File Handler
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

file_handler = logging.FileHandler(os.path.join(log_dir, "anti_stock.log"), encoding='utf-8')
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

def main():
    logger.info("Starting Anti-Stock Trading System...")
    
    # Initialize Engine
    engine = Engine()
    
    # Register Strategies
    engine.register_strategy(MovingAverageTrendStrategy, "ma_trend")
    engine.register_strategy(BollingerMeanReversion, "bollinger_mr")
    engine.register_strategy(PreviousHighBreakout, "breakout")
    engine.register_strategy(VWAPScalping, "vwap_scalping")
    
    # Start Web Server in a separate thread
    server_thread = threading.Thread(target=start_server, args=(engine,), daemon=True)
    server_thread.start()
    logger.info("Web Interface started at http://localhost:8000")
    
    # Start Engine (Blocking)
    try:
        engine.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        engine.stop()

if __name__ == "__main__":
    main()
