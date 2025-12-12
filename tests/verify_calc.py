
# Simulation of the Strategy Logic Change

def check_logic(name, current_price, avg_price, config_stop_decimal):
    print(f"--- Case: {name} ---")
    print(f"Price: {current_price}, Avg: {avg_price}")
    
    # 1. PnL Calculation (As Ratio/Decimal)
    # Removing '* 100' to match the Decimal Config
    pnl_ratio = (current_price - avg_price) / avg_price 
    
    print(f"PnL Ratio: {pnl_ratio:.4f} ({pnl_ratio*100:.2f}%)")
    print(f"Stop Config: {config_stop_decimal} ({config_stop_decimal*100:.2f}%)")
    
    # 2. Logic Check
    # Stop Loss: PnL <= -StopLoss
    # Ex: -0.02 <= -0.02 -> Trigger
    if pnl_ratio <= -config_stop_decimal:
        print(">> STOP LOSS TRIGGERED [O]")
    else:
        print(">> HOLD [X]")
    print("")

# Test Cases
# Config: Stop Loss 2% -> 0.02 in file
CFG_STOP = 0.02

# Case 1: 1.5% Loss (Should HOLD)
check_logic("1.5% Loss", 9850, 10000, CFG_STOP)

# Case 2: 2.0% Loss (Should TRIGGER)
check_logic("2.0% Loss", 9800, 10000, CFG_STOP)

# Case 3: 2.5% Loss (Should TRIGGER)
check_logic("2.5% Loss", 9750, 10000, CFG_STOP)

# Case 4: Profit (Should HOLD)
check_logic("1.0% Profit", 10100, 10000, CFG_STOP)
