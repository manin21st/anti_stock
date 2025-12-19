
import unittest
from unittest.mock import MagicMock, patch
import os
import sys

# Add project root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.engine import Engine
from core import kis_api as ka

class TestTPSLimitUpdate(unittest.TestCase):
    def setUp(self):
        # Mock Config Loading
        self.mock_config = {
            "system": {
                "env_type": "paper",
                "market_type": "KRX",
                "tps_limit": 2.0
            },
            "strategies": {}
        }
        
    @patch('core.engine.TelegramBot')
    @patch('core.engine.Scanner')
    @patch('core.engine.RiskManager')
    @patch('core.engine.Portfolio')
    @patch('core.engine.Broker')
    @patch('core.engine.MarketData')
    @patch('core.engine.Engine._load_config')
    @patch('core.engine.Engine._merge_config')
    @patch('core.kis_api.auth')
    @patch('core.kis_api.auth_ws')
    def test_tps_initialization_and_update(self, mock_auth_ws, mock_auth, mock_merge, mock_load, 
                                          mock_md, mock_broker, mock_pf, mock_rm, mock_scanner, mock_telegram):
        # Setup Mocks
        mock_load.return_value = self.mock_config
        
        # 1. Initialize Engine
        engine = Engine()
        
        # Verify initial TPS Limit
        self.assertEqual(ka.rate_limiter.tps_limit, 2.0, "Initial TPS Limit should be 2.0")
        print(f"[TEST] Initial TPS Limit: {ka.rate_limiter.tps_limit}")
        
        # 2. Update System Config (TPS -> 5.0)
        new_config = {"tps_limit": 5.0}
        engine.system_config.update(new_config) # Simulate merge
        
        # 3. Restart Engine
        engine.restart()
        
        # Verify Updated TPS Limit
        self.assertEqual(ka.rate_limiter.tps_limit, 5.0, "TPS Limit should be updated to 5.0 after restart")
        print(f"[TEST] Updated TPS Limit: {ka.rate_limiter.tps_limit}")
        
        # 4. Update System Config (TPS -> 0.5)
        new_config = {"tps_limit": 0.5}
        engine.system_config.update(new_config)
        engine.restart()
        self.assertEqual(ka.rate_limiter.tps_limit, 0.5, "TPS Limit should be updated to 0.5")
        print(f"[TEST] Updated TPS Limit: {ka.rate_limiter.tps_limit}")

if __name__ == '__main__':
    unittest.main()
