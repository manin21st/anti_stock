
import unittest
from unittest.mock import MagicMock
import logging
import sys
import os

if sys.platform == 'win32':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

# Add project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("test")

import lab1_act

class MockPosition:
    def __init__(self, qty, avg_price):
        self.qty = qty
        self.avg_price = avg_price

class MockPortfolio:
    def __init__(self, total_asset=100000000, cash=100000000):
        self.total_asset = total_asset
        self.cash = cash
        self.buying_power = cash
        self.positions = {}

    def get_position(self, symbol):
        return self.positions.get(symbol)

    def on_order_sent(self, order_info, market_data):
        # Mock optimistic update
        pass

class MockBroker:
    def buy_market(self, symbol, qty, tag=""):
        logger.info(f"   [매수체결] {symbol} {qty}주")
        return True
    
    def sell_market(self, symbol, qty, tag=""):
        logger.info(f"   [매도체결] {symbol} {qty}주")
        return True

class MockMarketData:
    def __init__(self):
        self.prices = {} # symbol -> price
        self.history = {} # symbol -> df

    def get_last_price(self, symbol):
        return self.prices.get(symbol, 0)
    
    def get_bars(self, symbol, timeframe="1d", lookback=30):
        return self.history.get(symbol)
        
    def get_stock_name(self, symbol):
        return "삼성전자" if symbol == "005930" else "테스트종목"

class TestLab1Act(unittest.TestCase):
    def setUp(self):
        self.symbol = "005930"
        self.broker = MockBroker()
        self.portfolio = MockPortfolio(total_asset=100_000_000) # 1억
        self.market_data = MockMarketData()

    def test_01_initial_entry(self):
        print("\n=== [Scenario 1] 신규 진입 (1차 매수) ===")
        # 상황: 보유 없음, 현재가 10,000원
        # 기대: 총자산 20%의 40% = 8% 매수 (8,000,000원 / 10,000원 = 800주)
        
        self.market_data.prices[self.symbol] = 10000
        
        lab1_act.buy(self.symbol, self.broker, self.portfolio, self.market_data)
        # Check logs visually

    def test_02_averaging_down_2nd(self):
        print("\n=== [Scenario 2] 물타기 1차 (손실 -4%) ===")
        # 상황: 기보유 8,000,000원 (800주, 평단 10,000), 현재가 9,600원 (-4%)
        # 기대: 누적 14% 목표 (14,000,000원)
        #       - 현재보유평가: 800 * 9,600 = 7,680,000
        #       - 목표금액: 100,000,000 * 0.14 = 14,000,000
        #       - 필요매수: 6,320,000 / 9,600 = 약 658주
        
        self.market_data.prices[self.symbol] = 9600
        self.portfolio.positions[self.symbol] = MockPosition(qty=800, avg_price=10000)
        
        lab1_act.buy(self.symbol, self.broker, self.portfolio, self.market_data)

    def test_03_averaging_down_3rd(self):
        print("\n=== [Scenario 3] 물타기 2차 (손실 -7%) ===")
        # 상황: 기보유 누적 14% 가정 (약 1458주, 평단 9800원 가정), 현재가 9,114원 (-7%)
        # 기대: 누적 20% 목표 (20,000,000원)
        
        current_price = 9100
        avg_price = 9800 # 가상의 평단
        qty = 1458
        
        self.market_data.prices[self.symbol] = current_price
        self.portfolio.positions[self.symbol] = MockPosition(qty=qty, avg_price=avg_price)
        
        lab1_act.buy(self.symbol, self.broker, self.portfolio, self.market_data)

    def test_04_pyramiding_trend_ok(self):
        print("\n=== [Scenario 4] 불타기 (수익 +6%, 추세 양호) ===")
        # 상황: 수익 구간 진입, +6% 수익 중
        # 기대: 비중 30%까지 확대
        
        import pandas as pd
        # Mocking Trend Data (Upward MA20)
        # Create a dataframe where MA20 is rising
        prices = [10000 + i*100 for i in range(30)] # continuously rising
        df = pd.DataFrame({'close': prices})
        self.market_data.history[self.symbol] = df
        
        current_price = 10600
        avg_price = 10000
        qty = 800 # 800만원 어치 보유 중 가정
        
        self.market_data.prices[self.symbol] = current_price
        self.portfolio.positions[self.symbol] = MockPosition(qty=qty, avg_price=avg_price)
        
        lab1_act.buy(self.symbol, self.broker, self.portfolio, self.market_data)

    def test_05_pyramiding_trend_fail(self):
        print("\n=== [Scenario 5] 불타기 시도 (수익 +6%이나 추세 꺾임) ===")
        # 상황: 수익은 났으나 차트가 꺾임 -> 매수 안해야 함
        
        import pandas as pd
        # Mocking Trend Data (Downward MA20)
        prices = [12000 - i*100 for i in range(30)] # continuously falling
        df = pd.DataFrame({'close': prices})
        self.market_data.history[self.symbol] = df
        
        current_price = 10600
        avg_price = 10000
        qty = 800
        
        self.market_data.prices[self.symbol] = current_price
        self.portfolio.positions[self.symbol] = MockPosition(qty=qty, avg_price=avg_price)
        
        lab1_act.buy(self.symbol, self.broker, self.portfolio, self.market_data)

if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
