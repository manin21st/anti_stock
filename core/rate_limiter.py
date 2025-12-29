import threading
import time
import logging
import os
import random
import requests
from collections import deque
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class RateLimiterService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(RateLimiterService, cls).__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        # Configurable TPS Limit (Default: 2.0)
        try:
            self.tps_limit = float(os.environ.get("TPS_LIMIT", 2.0))
        except ValueError:
            self.tps_limit = 2.0

        # Pacing: Minimum interval between requests to prevent burst
        # even if tokens are available.
        self.min_interval = 1.0 / max(self.tps_limit, 0.1)
        self.last_dispatch_time = 0.0

        self.lock = threading.Lock()

        # TPS Server Config
        self.server_url = os.environ.get("TPS_SERVER_URL", "http://localhost:9000")
        self.use_server = False # Will be determined by connection success
        self.server_alive = True
        self.server_fail_count = 0
        self.logged_server_error = False
        self.stopped = False # Shutdown flag

        # Generate Client ID (Hostname + PID)
        import socket
        try:
            hostname = socket.gethostname()
        except:
            hostname = "unknown"
        self.client_id = f"{hostname}-{os.getpid()}"
        
        # Metrics
        self.pending_count = 0
        self.request_history = deque(maxlen=600) # Store timestamps of processed requests

        logger.info(f"[RateLimiter] Service Initialized. TPS={self.tps_limit} (Min Interval: {self.min_interval:.4f}s)")

    def configure(self, tps_limit: float = None, server_url: str = None):
        """Dynamic Configuration"""
        with self.lock:
            if tps_limit is not None:
                self.tps_limit = float(tps_limit)
                self.min_interval = 1.0 / max(self.tps_limit, 0.1)
                logger.info(f"[RateLimiter] Limit updated to {self.tps_limit:.1f} TPS (Interval: {self.min_interval:.4f}s)")
            
            if server_url is not None and server_url != self.server_url:
                self.server_url = server_url.rstrip('/')
                self.server_alive = True 
                self.logged_server_error = False
                logger.info(f"[RateLimiter] Server URL updated to: {self.server_url}")

    def stop(self):
        """Signal to stop accepting requests (Graceful Shutdown)"""
        with self.lock:
            self.stopped = True
        logger.info("[RateLimiter] Service Stopping...")

    def _request_token_from_server(self) -> Optional[bool]:
        """
        Request a token from the centralized server.
        Returns: True (Granted), False (Denied/Wait), None (Error/Offline)
        """
        try:
            headers = {"X-Client-ID": self.client_id}
            # Timeout should be short to avoid blocking too long on network jitter
            resp = requests.get(f"{self.server_url}/token", headers=headers, timeout=1.0)

            if resp.status_code == 200:
                if not self.server_alive:
                    self.server_alive = True
                    logger.info(f"[RateLimiter] TPS Server Reconnected: {self.server_url}")
                    self.logged_server_error = False
                return True
            elif resp.status_code == 429:
                return False
            else:
                return False

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if not self.logged_server_error:
                logger.warning(f"[RateLimiter] TPS Server Unreachable ({self.server_url}). Waiting for reconnection...")
                self.logged_server_error = True
            self.server_alive = False
            return None
        except Exception:
            return None

    def wait_for_ready(self):
        """Block until TPS Server is connected (Strict Mode)"""
        if os.environ.get("SKIP_TPS_CHECK", "0") == "1":
            logger.warning("[RateLimiter] Skipping TPS check (Env SKIP_TPS_CHECK=1)")
            return

        logger.info("[RateLimiter] TPS 서버 연결 대기 중... (Strict Mode)")
        while not self.stopped:
            # Try to fetch token just to check connectivity
            status = self._request_token_from_server()
            if status is not None:
                logger.info("[RateLimiter] TPS 서버 연결 성공!")
                return
            time.sleep(1.0) 

    def get_stats(self) -> Dict[str, Any]:
        """Fetch statistics"""
        # Estimate local tokens
        # Note: This is a loose estimation since we don't track tokens locally in centralized mode
        elapsed = time.time() - self.last_dispatch_time
        estimated_tokens = min(self.tps_limit, elapsed * self.tps_limit)

        stats = {
            "pending": self.pending_count,
            "processed_1min": 0,
            "current_tps": self.tps_limit,
            "server_alive": self.server_alive,
            "estimated_local_tokens": estimated_tokens
        }

        # Calculate RPM locally
        now = time.time()
        with self.lock:
            while self.request_history and now - self.request_history[0] > 60:
                self.request_history.popleft()
            stats["processed_1min"] = len(self.request_history)

        # Try to get server stats if online
        try:
            headers = {"X-Client-ID": self.client_id}
            resp = requests.get(f"{self.server_url}/stats", headers=headers, timeout=0.5)
            if resp.status_code == 200:
                server_stats = resp.json()
                stats.update(server_stats)
                stats["status"] = "running"
            else:
                stats["status"] = "error"
                stats["message"] = f"HTTP {resp.status_code}"
        except Exception as e:
            stats["status"] = "offline"
            stats["message"] = str(e)

        return stats

    def execute(self, func, *args, **kwargs):
        """
        Executes the function with Rate Limiting and Pacing.
        """
        # If stopped, reject immediate
        if self.stopped:
            logger.warning("[RateLimiter] Service is stopped. Request rejected.")
            return None

        # --- Backtest Bypass Hook ---
        # If the caller provides a special flag or if we detect backtest mode otherwise.
        # Ideally, kis_api wrapper handles backtest bypassing BEFORE calling this.
        # But if we rely on this service, we assume we are in Real/Paper mode.
        
        max_retries = 3
        attempt = 0
        should_retry = True
        
        with self.lock:
             self.pending_count += 1
        
        try:
            while should_retry:
                # 1. Pacing Check (Local Throttling)
                # Ensure we don't send requests faster than min_interval
                with self.lock:
                    now = time.time()
                    elapsed = now - self.last_dispatch_time
                    wait_time = self.min_interval - elapsed
                
                if wait_time > 0:
                     # logger.debug(f"[RateLimiter] Pacing wait: {wait_time:.4f}s")
                     time.sleep(wait_time)

                # 2. Token Acquisition (Server Authority)
                token_granted = False
                while not token_granted and not self.stopped:
                    server_status = self._request_token_from_server()
                    if server_status is True:
                        token_granted = True
                    elif server_status is False:
                         # 429: Server has no tokens. Wait a bit.
                         time.sleep(0.1)
                    else:
                         # Server offline.
                         if not self.logged_server_error:
                             logger.warning("[RateLimiter] Connection lost. Waiting...")
                             self.logged_server_error = True
                         time.sleep(1.0)
                
                if self.stopped:
                    return None

                # 3. Execution
                # Update dispatch time immediately before execution
                with self.lock:
                    self.last_dispatch_time = time.time()

                result = None
                exception = None
                is_rate_limit = False # EGW00201
                is_expired_token = False # EGW00123

                try:
                    result = func(*args, **kwargs)

                    # Check for Rate Limit Error (EGW00201)
                    if hasattr(result, 'getErrorCode') and result.getErrorCode() == "EGW00201":
                        is_rate_limit = True
                    elif hasattr(result, 'getErrorMessage'):
                        msg = result.getErrorMessage()
                        if msg and "EGW00201" in msg:
                            is_rate_limit = True

                    # Check for Expired Token (EGW00123)
                    # Note: We rely on caller to handle re-auth or we handle it here if we have access to auth logic?
                    # Since RateLimiterService is decoupled, it shouldn't know about 'ka.auth'.
                    # We will return the result and let the Wrapper handle re-auth, 
                    # OR we define a callback for re-auth.
                    # For now, let's keep the logic simple: decoupling means we might lose the auto-reauth 
                    # unless we pass it as a callback or handle it in kis_api wrapper loop.
                    # -> Decision: kis_api wrapper should handle EGW00123 retry loop? 
                    # Actually, the original code handled it inside execute. 
                    # To split cleanly, RateLimiter should only handle Rate.
                    # But removing auto-reauth here breaks existing behavior.
                    # For this refactor, I will support a 'retry_on_expired' callback if needed, 
                    # or better: rely on the fact that result contains the error and the caller (kis_api) 
                    # should check it.
                    # HOWEVER, to minimize code changes in kis_api wrappers, 
                    # I will allow passing an 'auth_callback' or similar? 
                    # Or just return the error and let kis_api wrapper retry?
                    # The original code did: catch EGW00123 -> ka.auth -> retry.
                    # I'll stick to handling Pacing/Rate here. EGW00201 retry IS rate limiting logic.
                    # EGW00123 is Auth logic.
                    # I will leave EGW00123 handling to the caller or simply return the result.
                    # But EGW00201 (Rate Limit) IS my job.
                    pass

                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                    exception = e
                    # Network error -> might be rate limit or just floaty network
                    if attempt < max_retries:
                        is_rate_limit = True
                    else:
                        raise e
                except Exception as e:
                    raise e
                
                # Handling EGW00201 (Burst Leak)
                # Even with Pacing, if we still hit EGW00201, we must backoff.
                if is_rate_limit:
                    if attempt >= max_retries:
                        logger.error(f"[RateLimiter] Max retries ({max_retries}) exceeded for EGW00201.")
                        # Return result as is (let caller see error)
                        return result
                    
                    attempt += 1
                    # Adaptive Throttling: Increase min_interval dynamically?
                    # For now, just backoff
                    backoff = 2.0 + random.uniform(0.0, 1.0)
                    logger.warning(f"[RateLimiter] EGW00201 hit despite pacing. Backing off {backoff:.2f}s...")
                    time.sleep(backoff)
                    continue

                if exception:
                     # If we got here, it's a network retry that wasn't strictly 00201 but failed
                     if attempt < max_retries:
                         time.sleep(1.0)
                         attempt += 1
                         continue
                     else:
                         raise exception

                # Success
                with self.lock:
                    self.request_history.append(time.time())
                return result

        finally:
             with self.lock:
                  self.pending_count -= 1

# Singleton Instance
params_limiter = RateLimiterService()
