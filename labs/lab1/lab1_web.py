import threading
import time
import webbrowser
import uvicorn
import logging
import sys
import os

# Configure uvicorn loggers to be less noisy
logging.getLogger("uvicorn").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

def start_server_thread(port: int = 8000):
    """
    백그라운드 스레드에서 Web Server를 실행하고, 브라우저를 엽니다.
    """
    # 1. 서버 실행 (스레드)
    server_thread = threading.Thread(target=_run_uvicorn, args=(port,), daemon=True)
    server_thread.start()
    
    # 2. 브라우저 오픈 (약간의 지연 후)
    threading.Timer(2.0, _open_browser, args=(port,)).start()

def _run_uvicorn(port: int):
    """Uvicorn 서버 실행"""
    logger.info(f"[UI] 서버 시작 중... (http://localhost:{port}/lab1)")
    
    # import app lazily inside thread to avoid circular imports or early init
    try:
        # sys.path hack to ensure we can import 'web'
        current_dir = os.path.dirname(os.path.abspath(__file__)) # labs/lab1
        root_dir = os.path.dirname(os.path.dirname(current_dir)) # DigitalTwin/anti_stock
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)
            
        from web.server import app
        
        # Run uvicorn
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    except Exception as e:
        logger.error(f"[UI] 서버 시작 실패: {e}")

def _open_browser(port: int):
    """브라우저 자동 실행"""
    url = f"http://localhost:{port}/lab1"
    try:
        webbrowser.open(url)
        logger.info(f"[UI] 브라우저 오픈: {url}")
    except Exception as e:
        logger.warning(f"[UI] 브라우저 오픈 실패: {e}")
