
encoding = 'utf-8'
target_file = r'c:\DigitalTwin\anti_stock\logs\anti_stock.log'

try:
    with open(target_file, 'r', encoding=encoding) as f:
        for line in f:
            if '2025-12-16' in line and '13:' in line and '034020' in line:
                print(line.strip())
except Exception as e:
    print(f"Error: {e}")
