print("Importing Engine...")
try:
    from core.engine import Engine
    print("Engine imported successfully")
except Exception as e:
    print(f"Import failed: {e}")
except KeyboardInterrupt:
    print("Import interrupted")
