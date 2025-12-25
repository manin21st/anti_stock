import logging
import pandas as pd
from typing import Dict, Optional, Callable
from datetime import datetime, timedelta

from core.market_data import MarketData
from core.broker import Broker
from core.portfolio import Portfolio
from core.risk_manager import RiskManager
from utils.data_loader import DataLoader

logger = logging.getLogger(__name__)

class Backtester:
    def __init__(self, config: Dict, strategy_classes: Dict):
        self.config = config
        self.strategy_classes = strategy_classes

    def run_backtest(self, strategy_id: str, symbol: str, start_date: str, end_date: str, initial_cash: int = 100000000, strategy_config: Dict = None, progress_callback=None) -> Dict:
        """
        Run backtest for a specific strategy and symbol.
        Returns a dictionary with result metrics and history.
        """
        logger.info(f"Starting Backtest: {strategy_id} on {symbol} ({start_date}~{end_date})")

        # 1. Setup Isolated Environment
        sim_market = MarketData(is_simulation=True)
        sim_broker = Broker()
        sim_portfolio = Portfolio()
        sim_risk = RiskManager(sim_portfolio, self.config) # Pass config here? RiskManager typically needs it.

        # Configure Simulation
        sim_broker.set_simulation_mode(True, initial_cash)
        sim_portfolio.cash = float(initial_cash)
        sim_portfolio.total_asset = float(initial_cash)

        # Determine Timeframe early
        temp_cfg = self.config.get(strategy_id, {}).copy()
        if strategy_config:
            temp_cfg.update(strategy_config)
        tf = temp_cfg.get("timeframe", "D")

        # Load Data
        data_loader = DataLoader()

        try:
            buffer_days = 60 if tf == "D" else 5

            s_dt = datetime.strptime(start_date, "%Y%m%d")
            buffer_date = (s_dt - timedelta(days=buffer_days)).strftime("%Y%m%d")
        except ValueError:
            try:
                buffer_days = 60 if tf == "D" else 5

                s_dt = datetime.strptime(start_date, "%Y-%m-%d")
                buffer_date = (s_dt - timedelta(days=buffer_days)).strftime("%Y%m%d")
                start_date = s_dt.strftime("%Y%m%d")
                end_date = end_date.replace("-", "")
            except:
                buffer_date = start_date

        logger.info(f"Loading data from local storage: {buffer_date} ~ {end_date} (TF: {tf})")
        df = data_loader.load_data(symbol, buffer_date, end_date, timeframe=tf)
        if df.empty:
            return {"error": "No data found. Please run download first."}

        # 2. Initialize Strategy
        if strategy_id not in self.strategy_classes:
            return {"error": f"Strategy {strategy_id} not registered."}

        st_class = self.strategy_classes[strategy_id]

        st_cfg = temp_cfg
        st_cfg["id"] = strategy_id

        strategy = st_class(
            config=st_cfg,
            broker=sim_broker,
            risk_manager=sim_risk,
            portfolio=sim_portfolio,
            market_data=sim_market
        )

        # 3. Execution Loop
        history = []
        daily_stats = []

        tf = st_cfg.get("timeframe", "D")

        if tf == "D":
            dates = df['date'].unique()
            dates.sort()
            data_map = df.set_index('date').to_dict('index')

            total_days = len(dates)
            for i, date in enumerate(dates):
                sim_market.set_simulation_date(date)
                day_data = data_map[date]

                if progress_callback:
                    current_price = day_data['close']
                    pos = sim_portfolio.get_position(symbol)
                    qty = int(pos.qty) if pos else 0
                    avg_price = float(pos.avg_price) if pos else 0.0
                    buy_amt = qty * avg_price
                    eval_amt = qty * current_price
                    eval_pnl = eval_amt - buy_amt

                    cur_total_asset = sim_portfolio.cash + eval_amt
                    total_return = (cur_total_asset - float(initial_cash)) / float(initial_cash) * 100

                    status = {
                        "percent": int((i / total_days) * 100),
                        "qty": qty,
                        "avg_price": avg_price,
                        "buy_amt": buy_amt,
                        "current_price": current_price,
                        "eval_amt": eval_amt,
                        "eval_pnl": eval_pnl,
                        "return_rate": total_return,
                        "trade_count": len(history)
                    }
                    progress_callback("progress", status)

                self._run_backtest_step(sim_broker, sim_portfolio, strategy, symbol, day_data, date, history, is_intraday=False, progress_callback=progress_callback)

                daily_stats.append(self._calculate_daily_stat(date, sim_portfolio))

        else:
            logger.info(f"Running Intraday Backtest for {tf} timeframe...")

            df['date'] = df['date'].astype(str)
            df['time'] = df['time'].astype(str).str.zfill(6)

            df['datetime'] = pd.to_datetime(df['date'] + df['time'], format="%Y%m%d%H%M%S")
            df = df.set_index('datetime').sort_index()

            rule = tf.replace("m", "min")

            resampled = df.resample(rule).agg({
                'date': 'first',
                'time': 'last',
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()

            current_date_str = None

            total_bars = len(resampled)
            for i, (dt, row) in enumerate(resampled.iterrows()):
                if progress_callback and i % 10 == 0:
                    current_price = row['close']
                    pos = sim_portfolio.get_position(symbol)
                    qty = int(pos.qty) if pos else 0
                    avg_price = float(pos.avg_price) if pos else 0.0
                    buy_amt = qty * avg_price
                    eval_amt = qty * current_price
                    eval_pnl = eval_amt - buy_amt

                    cur_total_asset = sim_portfolio.cash + eval_amt
                    total_return = (cur_total_asset - float(initial_cash)) / float(initial_cash) * 100

                    status = {
                        "percent": int((i / total_bars) * 100),
                        "qty": qty,
                        "avg_price": avg_price,
                        "buy_amt": buy_amt,
                        "current_price": current_price,
                        "eval_amt": eval_amt,
                        "eval_pnl": eval_pnl,
                        "return_rate": total_return,
                        "trade_count": len(history)
                    }
                    progress_callback("progress", status)

                date_str = row['date']
                time_str = row['time']

                sim_market.set_simulation_date(f"{date_str}{time_str}")

                bar = row.to_dict()
                bar['time'] = row['time']

                self._run_backtest_step(sim_broker, sim_portfolio, strategy, symbol, bar, date_str, history, is_intraday=True, progress_callback=progress_callback)

        # 4. Calculate Metrics
        start_asset = initial_cash
        end_asset = sim_portfolio.total_asset
        total_return = (end_asset - start_asset) / start_asset * 100

        max_drawdown = 0 # Placeholder or implement MDD calculation

        return {
            "metrics": {
                "total_return": round(total_return, 2),
                "total_asset": int(end_asset),
                "mdd": round(max_drawdown, 2),
                "trade_count": len(history),
            },
            "history": history,
            "daily_stats": daily_stats
        }

    def _calculate_daily_stat(self, date, portfolio):
        return {
            "date": date,
            "total_asset": portfolio.total_asset,
            "cash": portfolio.cash,
            "holdings_val": portfolio.total_asset - portfolio.cash,
            "pnl_daily": 0
        }

    def _run_backtest_step(self, broker, portfolio, strategy, symbol, bar, date, history, is_intraday, progress_callback=None):
        current_prices = {symbol: bar['open']}
        if is_intraday:
            current_prices[symbol] = bar['open']

        def on_sim_order(info):
            info['timestamp'] = f"{date} {bar.get('time', '')}"
            history.append(info)
            if progress_callback:
                 progress_callback("trade_event", info)
        broker.on_order_sent = [on_sim_order]

        broker.process_simulation_orders(current_prices)

        try:
            strategy.on_bar(symbol, bar)
        except Exception as e:
            logger.error(f"Backtest Error on {date}: {e}")
