import os

path = r'c:\ax-dev\anti_stock\.agent\rules\anti-stock.md'
target = r'''### Encoding Policy & Windows Support (Encoding Fix)
- Windows 환경에서 발생하는 한글 깨짐 문제(CP949 vs UTF-8 불일치)는 개별 스크립트 수정이 아닌 `core` 패키지 초기화를 통해 해결한다.
- **모든 Python 진입점(Entry Point) 스크립트**는 로깅이나 출력을 시작하기 전에 반드시 `core` 패키지를 최상단에서 임포트해야 한다.
- 표준 해결 코드는 이미 `core/__init__.py`에 적용되어 있으며, 다음과 같다:
  ```python
  import sys
  import os
  if os.name == 'nt':
      try:
          # Python 3.7+ 지원
          if hasattr(sys.stdout, 'reconfigure') and sys.stdout.encoding.lower() != 'utf-8':
              sys.stdout.reconfigure(encoding='utf-8')
          if hasattr(sys.stderr, 'reconfigure') and sys.stderr.encoding.lower() != 'utf-8':
              sys.stderr.reconfigure(encoding='utf-8')
      except Exception:
          pass
  ```
- 새로운 스크립트 작성 시 로깅 설정(`logging.basicConfig`) 전에 `import core`가 존재하는지 반드시 확인한다.'''

replacement = r'''### Encoding Policy & Windows Support (Encoding Fix)
- Windows 환경에서 발생하는 한글 깨짐 문제(CP949 vs UTF-8 불일치)는 특정 패키지(`core`)에 의존하지 않고 Python 표준 기능을 사용하여 해결한다.
- **모든 Python 진입점(Entry Point) 스크립트**는 로깅이나 출력을 시작하기 전에 반드시 다음 코드를 최상단에 포함해야 한다:
  ```python
  import sys
  if sys.platform == 'win32':
      if hasattr(sys.stdout, 'reconfigure'):
          sys.stdout.reconfigure(encoding='utf-8')
      if hasattr(sys.stderr, 'reconfigure'):
          sys.stderr.reconfigure(encoding='utf-8')
  ```
- 이는 프로젝트 내부/외부 어디서든 독립적으로 실행 가능한 범용적인 해결책이다.
- 새로운 스크립트 작성 시 로깅 설정(`logging.basicConfig`) 전에 이 코드가 존재하는지 반드시 확인한다.'''

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Normalize line endings just in case
content = content.replace('\r\n', '\n')
target = target.replace('\r\n', '\n')
replacement = replacement.replace('\r\n', '\n')

if target in content:
    new_content = content.replace(target, replacement)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Successfully updated rules.")
else:
    print("Target content not found.")
    # Debugging: Print first 50 chars of target and content snippet
    print("Target start:", repr(target[:50]))
    print("Content snippet:", repr(content[2000:2500])) # Rough guess location
