import sys
print(f"Python executable: {sys.executable}")
try:
    import itsdangerous
    print(f"itsdangerous is installed: {itsdangerous.__version__}")
except ImportError:
    print("itsdangerous is NOT installed")

try:
    from starlette.middleware.sessions import SessionMiddleware
    print("SessionMiddleware import successful")
except ImportError as e:
    print(f"SessionMiddleware import failed: {e}")
except Exception as e:
    print(f"An error occurred: {e}")
