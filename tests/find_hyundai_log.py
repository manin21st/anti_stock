
encoding = 'utf-8'
target_file = r'c:\DigitalTwin\anti_stock\logs\anti_stock.log'

try:
    with open(target_file, 'r', encoding=encoding) as f:
        for line in f:
            if '2025-12-16' in line and '005380' in line and ('매수' in line or '매도' in line or 'Order' in line or 'Risk' in line):
                print(line.strip())
except Exception as e:
    print(f"Error: {e}")
