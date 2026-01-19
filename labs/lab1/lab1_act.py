import logging
import math

logger = logging.getLogger(__name__)

def sell(symbol, broker, portfolio, market_data, telegram=None, **kwargs):
    """
    [매도 실행]
    Action 파라미터(kwargs) 우선 적용
    - qty: 지정 수량 매도
    - qty_pct: 보유량의 % 매도 (0.5 = 50%)
    """
    # 보유 수량 조회
    pos = portfolio.get_position(symbol)
    if not pos:
         # 안전장치: API 잔고 확인
         balance = broker.get_balance()
         holdings = balance.get('holdings', [])
         found = next((h for h in holdings if h['pdno'] == symbol), None)
         qty = int(found['hldg_qty']) if found else 0
    else:
         qty = pos.qty
    
    if qty <= 0:
        logger.warning(f"[{symbol}] 매도할 수량이 없습니다.")
        return

    # [Action Logic] 동적 파라미터 처리
    sell_qty = qty # 기본: 전량
    
    if 'qty' in kwargs:
        sell_qty = int(kwargs['qty'])
    elif 'qty_pct' in kwargs:
        pct = float(kwargs['qty_pct'])
        sell_qty = int(qty * pct)
    
    # 0 이하 또는 보유량 초과 보정
    if sell_qty <= 0: sell_qty = 0
    if sell_qty > qty: sell_qty = qty

    if sell_qty == 0:
        return

    logger.info(f"  >>> {symbol} 매도 주문 전송 (qty={sell_qty}, 보유={qty})")
    if broker.sell_market(symbol, qty=sell_qty, tag="LAB1"):
        logger.info(f"  >>> {symbol} 매도 주문 성공")
        
        # [Optimistic Update]
        order_info = {
             "side": "SELL",
             "symbol": symbol,
             "qty": sell_qty,
             "price": 0,
             "tag": "LAB1"
        }
        portfolio.on_order_sent(order_info, market_data)

        # [Telegram Alert] (Engine Upgrade)
        if telegram:
             # 매도 시 현재가 조회 (알림용)
            cur_price = market_data.get_last_price(symbol)
            stock_name = market_data.get_stock_name(symbol)
            telegram.send_trade_event(
                event_type="SELL", 
                symbol=symbol, 
                price=cur_price, 
                qty=sell_qty, 
                side="SELL", 
                stock_name=stock_name,
                position_info={"new_qty": qty - sell_qty} # approximate remaining
            )
    else:
        logger.error(f"  >>> {symbol} 매도 주문 실패")

def buy(symbol, broker, portfolio, market_data, telegram=None, **kwargs):
    """
    [매수 실행]
    Action 파라미터(kwargs) 우선 적용
    - target_pct: 총 자산 대비 목표 비중 (0.1 = 10%)
    - buy_amt: 지정 금액 매수 (원)
    - buy_qty: 지정 수량 매수
    """
    try:
        name = market_data.get_stock_name(symbol)

        current_price = market_data.get_last_price(symbol)
        if current_price <= 0:
            logger.error(f"[{name}({symbol})] 현재가 조회 실패, 매수 중단")
            return

        # 1. 자산 데이터 및 상태 조회
        total_asset = portfolio.total_asset
        if total_asset <= 0: total_asset = portfolio.cash # fallback
        buying_power = portfolio.buying_power
        
        pos = portfolio.get_position(symbol)
        has_position = (pos is not None and pos.qty > 0)
        current_qty = pos.qty if has_position else 0
        current_val = current_qty * current_price
        
        # 2. 파라미터 해석 (Dynamic) - 사용자가 지정한 로직 우선
        buy_qty = 0
        mode = "DYNAMIC_ACTION"
        
        if kwargs:
            # A. 목표 비중 지정 (예: 자산의 10%까지 채워라)
            if 'target_pct' in kwargs:
                target_pct = float(kwargs['target_pct'])
                target_amt = total_asset * target_pct
                target_qty = int(target_amt // current_price)
                buy_qty = target_qty - current_qty # 부족분 매수
                mode = f"TARGET_PCT({target_pct*100}%)"
                
            # B. 매수 금액 지정 (예: 100만원 어치 사라)
            elif 'buy_amt' in kwargs:
                amt = float(kwargs['buy_amt'])
                buy_qty = int(amt // current_price)
                mode = f"BUY_AMT({int(amt):,})"
                
            # C. 매수 수량 지정 (예: 10주 사라)
            elif 'buy_qty' in kwargs:
                buy_qty = int(kwargs['buy_qty'])
                mode = f"BUY_QTY({buy_qty})"
                
            # 계산된 수량이 0 이하면 (이미 목표 달성 등) 리턴
            if buy_qty <= 0:
                holding_pct = (current_val / total_asset * 100) if total_asset > 0 else 0
                logger.info(f"[{name}({symbol})] {mode} - 추가 매수 불필요 (보유: {current_qty}주, 금액: {int(current_val):,}원, 비중: {holding_pct:.2f}%)")
                return

        else:
            # 파라미터가 없으면 실행 불가
            logger.warning(f"[{name}({symbol})] 실행 액션(Action Dictionary) 없음. 매수 스킵.")
            return

        # 3. 계산된 수량이 유효한지 확인
        if buy_qty <= 0:
            return

        # 4. 자금력 확인
        buying_power = portfolio.buying_power
        # 수수료/슬리피지 고려 (0.015%)
        estimated_cost = buy_qty * current_price * 1.00015
        
        if estimated_cost > buying_power:
            # 자금 부족 시 가능한 만큼만 매수
            adj_qty = int(buying_power // (current_price * 1.00015))
            if adj_qty <= 0:
                logger.warning(f"[{name}({symbol})] 주문 가능 자금 부족 (필요: {int(estimated_cost):,}, 가용: {int(buying_power):,})")
                return
            logger.info(f"[{name}({symbol})] 자금 부족으로 수량 조정 ({buy_qty} -> {adj_qty})")
            buy_qty = adj_qty

        # 5. 주문 실행
        logger.info(f"[{name}({symbol})] [{mode}] 매수 주문: {buy_qty}주 (현재: {current_qty}주, 가격: {int(current_price):,})")
        
        if broker.buy_market(symbol, qty=buy_qty, tag="LAB1"):
             logger.info(f"  >>> [{name}({symbol})] 매수 주문 성공")
             
             # Optimistic Update
             order_info = {
                 "side": "BUY",
                 "symbol": symbol,
                 "qty": buy_qty,
                 "price": current_price,
                 "tag": "LAB1"
             }
             portfolio.on_order_sent(order_info, market_data)

             # [Telegram Alert] (Engine Upgrade)
             if telegram:
                telegram.send_trade_event(
                    event_type="BUY", 
                    symbol=symbol, 
                    price=current_price, 
                    qty=buy_qty, 
                    side="BUY", 
                    stock_name=name,
                    position_info={"new_qty": current_qty + buy_qty, "new_avg_price": current_price}
                )
        else:
            logger.error(f"  >>> [{name}({symbol})] 매수 주문 실패")

    except Exception as e:
        logger.error(f"[{name}({symbol})] 매수 실행 중 오류: {e}")

def _check_trend_valid(symbol, market_data):
    """
    [추세 확인 Helper]
    고점/저점 상승 구조 또는 단순 이평 배열 확인
    여기서는 간단히 일봉상 정배열(Close > MA20 > MA60) 또는 MA20 상승 기울기 확인
    """
    try:
        df = market_data.get_bars(symbol, timeframe="1d", lookback=30)
        if df.empty or len(df) < 20: 
            return True # 데이터 없으면 관대하게 처리 (실험실 특성)
            
        # 1. MA20 상승 확인
        ma20 = df['close'].rolling(20).mean()
        if ma20.iloc[-1] > ma20.iloc[-2]:
            return True
            
        return False
    except:
        return True # 에러 시 안전하게 True (매수 기회 우선)
