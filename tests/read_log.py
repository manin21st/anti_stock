import os
try:
    with open('logs/anti_stock.log', 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
        print(''.join(lines[-100:]))
except Exception as e:
    print(f"Error reading log: {e}")
