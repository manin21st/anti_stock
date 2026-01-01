import logging
import uuid
import time
from datetime import datetime
from typing import List, Dict, Optional
import pandas as pd

from core.visualization import TradeEvent
from core.dao import TradeDAO

logger = logging.getLogger(__name__)

class TradeManager:
    def __init__(self, telegram_bot=None):
        self.trade_history: List[TradeEvent] = []
        self.telegram = telegram_bot
        self.load_trade_history()

    def load_trade_history(self):
        """Load trade history from Database"""
        try:
            trades = TradeDAO.get_trades(limit=1000)

            # Convert SQLAlchemy Models to TradeEvent objects
            self.trade_history = []
            for t in trades:
                self.trade_history.append(TradeEvent(
                    event_id=t.event_id,
                    timestamp=t.timestamp,
                    symbol=t.symbol,
                    strategy_id=t.strategy_id,
                    event_type="DB_LOADED", # Or infer from meta
                    side=t.side,
                    price=t.price,
                    qty=t.qty,
                    exec_amt=t.exec_amt if t.exec_amt else (t.price * t.qty),
                    order_id=t.order_id,
                    pnl=t.pnl,
                    pnl_pct=t.pnl_pct,
                    meta=t.meta
                ))
            logger.debug(f"Loaded {len(self.trade_history)} recent trade events from Database")
        except Exception as e:
            logger.error(f"Failed to load trade history: {e}")

    def record_order_event(self, order_info: Dict):
        """Callback from Broker when order is sent"""
        try:
            event = TradeEvent(
                event_id=str(uuid.uuid4()),
                timestamp=datetime.now(),
                symbol=order_info["symbol"],
                strategy_id=order_info["tag"],
                event_type="ORDER_SUBMITTED",
                side=order_info["side"],
                price=float(order_info["price"]),
                qty=int(order_info["qty"]),
                order_id=order_info["order_no"],
                meta={"type": order_info["type"], "event_type": "ORDER_SUBMITTED"}
            )

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

            self.trade_history.insert(0, event) # Prepend for recent
            logger.info(f"Recorded Order Event: {event.event_type} {event.symbol}")

        except Exception as e:
            logger.error(f"Failed to record order event: {e}")

    def record_position_event(self, change_info: Dict, market_data=None):
        """Callback from Portfolio when position changes (Fills)"""
        try:
            event_type = change_info["type"]

            side = "BUY" if "BUY" in event_type else "SELL"
            if event_type == "POSITION_CLOSED":
                side = "SELL"

            if float(change_info["price"]) <= 0:
                return

            # XPnL Calculation (Client-side)
            pnl = None
            pnl_pct = None
            fees = 0
            old_avg_price = 0

            if side == "SELL":
                exec_qty = change_info.get("exec_qty", 0)
                exec_price = change_info.get("exec_price", 0)
                old_avg_price = change_info.get("old_avg_price", 0)

                if exec_qty > 0 and old_avg_price > 0:
                    # Fee Calculation (Conservative: 0.25%)
                    total_sell_amt = exec_price * exec_qty
                    fees = total_sell_amt * 0.0025

                    gross_pnl = (exec_price - old_avg_price) * exec_qty
                    net_pnl = gross_pnl - fees

                    pnl = round(net_pnl, 0)
                    pnl_pct = round(((exec_price - old_avg_price) / old_avg_price) * 100, 2)

                    logger.info(f"[PnL Calculated] {change_info['symbol']} PnL: {pnl} ({pnl_pct}%) [Avg: {old_avg_price} -> Sell: {exec_price}]")

            if "meta" not in change_info:
                change_info["meta"] = {}
            if side == "SELL":
                if pnl is not None:
                     change_info["fees"] = round(fees, 0)
                     change_info["old_avg_price"] = round(old_avg_price, 2)

            event = TradeEvent(
                event_id=str(uuid.uuid4()),
                timestamp=datetime.now(),
                symbol=change_info["symbol"],
                strategy_id=change_info.get("tag", ""),
                event_type=event_type,
                side=side,
                price=float(change_info["price"]),
                qty=int(change_info["qty"]),
                order_id=f"fill_{int(time.time()*1000)}",
                pnl=pnl,
                pnl_pct=pnl_pct,
                meta=change_info
            )

            if "exec_qty" in change_info:
                event.qty = change_info["exec_qty"]

            self.trade_history.insert(0, event)

            TradeDAO.insert_trade({
                "event_id": event.event_id,
                "timestamp": event.timestamp,
                "symbol": event.symbol,
                "strategy_id": event.strategy_id,
                "side": event.side,
                "price": event.price,
                "qty": event.qty,
                "exec_amt": event.price * event.qty,
                "pnl": event.pnl,
                "pnl_pct": event.pnl_pct,
                "order_id": event.order_id,
                "meta": event.meta
            })

            logger.info(f"Recorded Position Event: {event.event_type} {event.symbol} (PnL: {pnl})")

            # Telegram Alert
            if self.telegram:
                stock_name = market_data.get_stock_name(change_info["symbol"]) if market_data else change_info["symbol"]
                self.telegram.send_trade_event(
                    event_type=event_type,
                    symbol=change_info["symbol"],
                    price=float(change_info["price"]),
                    qty=int(event.qty),
                    side=side,
                    stock_name=stock_name,
                    position_info=change_info
                )
        except Exception as e:
            logger.error(f"Failed to record position event: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def sync_trade_history(self, start_date: str, end_date: str):
        """Syncs local trade history with Broker API"""
        from core import kis_api as ka
        try:
            logger.info(f"Syncing trade history from {start_date} to {end_date}...")

            all_trades = []
            ctx_area_fk = ""
            ctx_area_nk = ""
            prev_nk = ""

            page_count = 0
            empty_page_count = 0
            MAX_PAGES = 200

            while True:
                page_count += 1
                if page_count > MAX_PAGES:
                    logger.warning(f"Reached MAX_PAGES ({MAX_PAGES}) limit. Stopping sync.")
                    break

                resp = ka.fetch_daily_ccld(start_date, end_date, ctx_area_fk=ctx_area_fk, ctx_area_nk=ctx_area_nk)

                if not resp.isOK():
                    logger.error(f"API Error: {resp.getErrorCode()} {resp.getErrorMessage()}")
                    break

                body = resp.getBody()

                def get_attr_case_insensitive(obj, attr_name, default=None):
                    if hasattr(obj, '_fields'):
                        for field in obj._fields:
                            if field.lower() == attr_name.lower():
                                return getattr(obj, field)
                    elif isinstance(obj, dict):
                         for key in obj.keys():
                             if key.lower() == attr_name.lower():
                                 return obj[key]
                    return default

                output1 = get_attr_case_insensitive(body, 'output1', [])

                if output1:
                    all_trades.extend(output1)
                    empty_page_count = 0
                else:
                    empty_page_count += 1

                if empty_page_count >= 5:
                    logger.warning("Too many consecutive empty pages with next token. Stopping sync.")
                    break

                ctx_area_nk = get_attr_case_insensitive(body, 'ctx_area_nk100', "").strip()
                ctx_area_fk = get_attr_case_insensitive(body, 'ctx_area_fk100', "").strip()

                logger.info(f"[DEBUG] Pagination: fk=[{ctx_area_fk}], nk=[{ctx_area_nk}], count={len(output1)} (Page {page_count})")

                if not ctx_area_nk:
                    break

                if ctx_area_nk == prev_nk:
                    logger.warning(f"Infinite loop detected: Pagination token {ctx_area_nk} did not change. Stopping sync.")
                    break
                prev_nk = ctx_area_nk

                time.sleep(0.2)

            if not all_trades:
                logger.info("No execution history found from API.")
                return 0

            df1 = pd.DataFrame(all_trades)

            if df1.empty:
                logger.info("No execution history found from API (Empty DataFrame).")
                return 0

            local_odnos = set(t.order_id for t in self.trade_history if t.order_id)
            new_count = 0

            for _, row in df1.iterrows():
                def get_val(row_series, candidates, default=None):
                    for cand in candidates:
                         if cand in row_series:
                             return row_series[cand]
                         if cand.upper() in row_series:
                             return row_series[cand.upper()]
                         if cand.lower() in row_series:
                             return row_series[cand.lower()]
                    return default

                odno = str(get_val(row, ['odno', 'ODNO']))
                if odno == 'None' or not odno:
                     continue

                if odno in local_odnos:
                    continue

                symbol = str(get_val(row, ['pdno', 'PDNO']))

                qty_candidates = ['tot_ccld_qty', 'TOT_CCLD_QTY', 'ccld_qty', 'CCLD_QTY']
                qty = int(get_val(row, qty_candidates, 0))

                price = float(get_val(row, ['avg_prvs', 'AVG_PRVS'], 0.0))
                date_str = str(get_val(row, ['ord_dt', 'ORD_DT'], ""))
                time_str = str(get_val(row, ['ord_tmd', 'ORD_TMD'], "000000"))
                side_code = str(get_val(row, ['sll_buy_dvsn_cd', 'SLL_BUY_DVSN_CD'], ""))
                side = "BUY" if side_code == "02" else "SELL"

                if not date_str:
                     continue

                try:
                    full_dt_str = f"{date_str}{time_str}"
                    ts = datetime.strptime(full_dt_str, "%Y%m%d%H%M%S")
                except ValueError:
                     try:
                        ts = datetime.strptime(date_str, "%Y%m%d")
                     except:
                        ts = datetime.now()

                strategy_id = "ma_trend"

                event = TradeEvent(
                    event_id=str(uuid.uuid4()),
                    timestamp=ts,
                    symbol=symbol,
                    strategy_id=strategy_id,
                    event_type="ORDER_FILLED_SYNC",
                    side=side,
                    price=price,
                    qty=qty,
                    order_id=odno,
                    meta={"source": "api_sync"}
                )
                self.trade_history.append(event)
                new_count += 1

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

            if new_count > 0:
                self.trade_history.sort(key=lambda x: x.timestamp if isinstance(x.timestamp, datetime) else datetime.fromisoformat(str(x.timestamp)))
                logger.info(f" synced {new_count} new trades from Broker API.")
            else:
                logger.info("All trades already exist locally.")

            # --- Sync Realized PnL ---
            try:
                logger.info(f"Syncing Period PnL from {start_date} to {end_date}...")
                pnl_resp = ka.fetch_period_profit(start_date, end_date)

                if pnl_resp and pnl_resp.isOK():
                    pnl_body = pnl_resp.getBody()
                    pnl_list = getattr(pnl_body, 'output1', [])

                    pnl_map = {}

                    def safe_float(val):
                        if val is None or val == "": return 0.0
                        if isinstance(val, (int, float)): return float(val)
                        try:
                            clean_val = str(val).replace(',', '').strip()
                            if not clean_val: return 0.0
                            return float(clean_val)
                        except Exception:
                            return 0.0

                    for item in pnl_list:
                        def g(obj, keys, default=None):
                            if isinstance(obj, dict):
                                for k in keys:
                                    if k in obj: return obj[k]
                            else:
                                for k in keys:
                                    if hasattr(obj, k): return getattr(obj, k)
                            return default

                        dt = str(g(item, ['tr_dt', 'TR_DT', 'ord_dt', 'ORD_DT'], ""))
                        sym = str(g(item, ['pdno', 'PDNO', 'shtn_pdno'], ""))

                        pnl_raw = g(item, ['rlzg_pl', 'RLZG_PL', 'cisa_pl', 'CISA_PL'], 0)
                        pnl = safe_float(pnl_raw)

                        if dt and sym:
                            pnl_map[(dt, sym)] = pnl_map.get((dt, sym), 0.0) + pnl

                    if pnl_map:
                        logger.info(f"Fetched PnL data for {len(pnl_map)} day-symbol pairs.")
                    else:
                        logger.info("Fetched PnL data but result map is empty.")

                    # Assign PnL to local Sell events
                    day_sell_events = {}

                    for event in self.trade_history:
                        if event.side == "SELL":
                            d_str = event.timestamp.strftime("%Y%m%d")
                            k = (d_str, event.symbol)
                            if k not in day_sell_events:
                                day_sell_events[k] = []
                            day_sell_events[k].append(event)

                    updated_pnl_count = 0
                    for k, events in day_sell_events.items():
                        if k in pnl_map:
                            daily_pnl = pnl_map[k]
                            events.sort(key=lambda x: x.timestamp)

                            last_event = events[-1]

                            if last_event.pnl != daily_pnl:
                                last_event.pnl = daily_pnl
                                updated_pnl_count += 1

                    if updated_pnl_count > 0:
                        for k, events in day_sell_events.items():
                             if k in pnl_map:
                                 daily_pnl = pnl_map[k]
                                 last_event = events[-1]
                                 TradeDAO.update_pnl(last_event.event_id, daily_pnl, 0.0)

                        logger.info(f"Updated PnL for {updated_pnl_count} trade events.")
                    else:
                        logger.info("No PnL updates needed.")

                else:
                    msg = pnl_resp.getErrorMessage() if pnl_resp else 'None'
                    code = pnl_resp.getErrorCode() if pnl_resp else 'Unknown'
                    logger.warning(f"PnL Fetch Failed: [{code}] {msg}. Falling back to local FIFO PnL calculation.")
                    self._calculate_pnl_from_local_history()

            except Exception as e:
                logger.error(f"PnL Sync Logic Error: {e}")
                import traceback
                logger.error(traceback.format_exc())

            return new_count

        except KeyboardInterrupt:
            logger.warning("Sync operation interrupted by user.")
            return 0
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise e
        finally:
            self.load_trade_history()

    def _calculate_pnl_from_local_history(self):
        """
        Calculate Realized PnL for SELL events using FIFO method from local trade history.
        This is a fallback when API PnL is unavailable.
        """
        try:
            sorted_events = sorted(self.trade_history, key=lambda x: x.timestamp)

            inventory = {}
            updated_count = 0

            for event in sorted_events:
                sym = event.symbol
                if sym not in inventory:
                    inventory[sym] = []

                if event.side == "BUY":
                    inventory[sym].append([event.price, event.qty])

                elif event.side == "SELL":
                    sell_qty = event.qty
                    sell_price = event.price

                    cost_basis = 0.0
                    matched_qty = 0

                    while sell_qty > 0 and inventory[sym]:
                        bucket = inventory[sym][0]
                        b_price = bucket[0]
                        b_qty = bucket[1]

                        take_qty = min(sell_qty, b_qty)

                        cost_basis += (take_qty * b_price)
                        matched_qty += take_qty

                        if b_qty > take_qty:
                            bucket[1] -= take_qty
                            sell_qty = 0
                        else:
                            inventory[sym].pop(0)
                            sell_qty -= take_qty

                    if matched_qty > 0:
                        if matched_qty == 0:
                            avg_buy_price = 0
                        else:
                            avg_buy_price = cost_basis / matched_qty

                        gross_pnl = (sell_price - avg_buy_price) * matched_qty

                        fee = (sell_price * matched_qty) * 0.0025
                        net_pnl = gross_pnl - fee
                        
                        if avg_buy_price > 0:
                            pnl_pct = ((sell_price - avg_buy_price) / avg_buy_price) * 100
                        else:
                            pnl_pct = 0.0

                        if event.pnl is None or event.pnl == 0:
                            event.pnl = round(net_pnl, 0)
                            event.pnl_pct = round(pnl_pct, 2)
                            updated_count += 1
                    else:
                        logger.warning(f"Skipping PnL for {sym} (Sell {sell_qty}): No matching BUY history found locally.")

            if updated_count > 0:
                for event in sorted_events:
                     if event.side == "SELL" and event.pnl is not None:
                          TradeDAO.update_pnl(event.event_id, event.pnl, event.pnl_pct)

                logger.info(f"Locally calculated PnL for {updated_count} SELL events using FIFO.")

        except Exception as e:
            logger.error(f"Local PnL Calculation Failed: {e}")
