import sys
import os

# Windows 환경에서 한글 깨짐 방지를 위한 인코딩 설정
if os.name == 'nt':
    try:
        # Python 3.7+ 지원
        if hasattr(sys.stdout, 'reconfigure') and sys.stdout.encoding.lower() != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8')
        if hasattr(sys.stderr, 'reconfigure') and sys.stderr.encoding.lower() != 'utf-8':
            sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
