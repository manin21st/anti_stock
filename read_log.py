try:
    with open('anti_stock.log', 'r', encoding='utf-8', errors='ignore') as f:
        import os
        size = os.path.getsize('anti_stock.log')
        pos = max(0, size - 5000)
        f.seek(pos)
        data = f.read()
        
    with open('log_tail.txt', 'w', encoding='utf-8') as f_out:
        f_out.write(data)
        
    print("Successfully wrote log_tail.txt")
except Exception as e:
    with open('log_tail.txt', 'w', encoding='utf-8') as f_out:
        f_out.write(f"ERROR: {e}")
    print(f"Error: {e}")
