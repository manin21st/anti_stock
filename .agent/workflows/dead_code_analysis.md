---
description: 소스 코드 정적 분석을 통해 사용되지 않는 함수나 메서드(Dead Code)를 식별합니다.
---

# Dead Code Analysis Workflow

특정 파일 내의 함수나 메서드가 프로젝트 전체에서 실제로 사용되고 있는지 분석하여, 정리 대상(Dead Code)을 식별하는 워크플로우입니다.

## Step 1: 대상 파일 분석 (Analyze Target File)
1.  분석할 **대상 파일 경로**가 명확한지 확인합니다.
2.  `view_file_outline` 도구를 사용하여 대상 파일의 모든 클래스, 메서드, 함수 목록을 추출합니다.
3.  분석할 함수 이름들의 리스트를 메모리에 저장합니다. (`__init__` 등 매직 메서드는 제외)

## Step 2: 전체 검색 수행 (Global Search) - ⚠️ 중요
**"소스의 일부만 보고 사용 안 함으로 오판"하는 실수를 방지하기 위해 반드시 전체를 검색해야 합니다.**

추출한 각 함수 이름에 대해 다음을 반복합니다:
1.  **`grep_search` 필수 설정**:
    *   **SearchPath**: 반드시 **프로젝트 루트**(`c:\DigitalTwin\anti_stock`)를 지정하십시오. (특정 하위 폴더 지정 금지)
    *   **MatchPerLine**: `true` (호출 라인 확인용)
    *   **CaseInsensitive**: `true` (대소문자 실수 방지)
2.  **결과 교차 검증 (Cross-Verification)**:
    *   검색 결과가 **"0건"**이거나 **"정의부(def)만 존재"**하는 경우, 즉시 결론 내리지 마십시오.
    *   해당 함수명의 **일부 키워드**로 다시 한번 검색하거나, `server.py`, `main.py` 등 진입점 파일에서 직접 확인하십시오.
    *   *이전 실수 사례*: `sync_trade_history`가 `server.py`에 있었으나 하위 폴더 검색 누락으로 놓침.
3.  **결과 필터링**:
    *   함수 정의부(definition) 라인은 제외합니다.
    *   대상 파일 내부에서의 호출(재귀, 내부 호출)은 **Internal**로 분류합니다.
    *   다른 파일에서의 호출은 **Active(External)**로 분류합니다.

## Step 3: 분석 및 분류 (Analyze & Categorize)
각 함수를 다음 카테고리 중 하나로 분류합니다:
*   **✅ Active (External)**: `main.py`, `server.py` 등 다른 외부 모듈에서 호출됨.
*   **🔒 Internal Only**: 해당 파일 내부에서만 사용됨. (Private 메서드화 고려 대상)
*   **🚫 Unused (Dead Code)**: 정의부 외에 호출되는 곳이 전혀 없음.
    *   *예외*: 오버라이딩 메서드(`on_market_data` 등)이거나, 프레임워크에 의해 동적으로 호출되는 경우(FastAPI route 등)는 제외.

## Step 4: 보고서 작성 (Generate Report)
분석 결과를 마크다운 형식으로 사용자에게 보고합니다.

### 보고서 양식 예시
```markdown
## 🔍 Dead Code 분석 보고서
**대상 파일**: `core/engine.py`
**검사 범위**: 전체 프로젝트 루트 (`c:\DigitalTwin\anti_stock`) - `web/`, `core/`, `strategies/` 포함

### 🚫 사용되지 않음 (삭제 검토)
이 함수들은 코드베이스 어디에서도 호출되지 않습니다.
- `load_trade_history`: 사용처 없음
- `temp_helper`: 사용처 없음

### 🔒 내부 전용 (Private 추천)
이 함수들은 외부에서 호출되지 않고 내부적으로만 사용됩니다.
- `_calculate_risk`: `execute` 함수에서만 사용됨

### ✅ 정상 사용 (External)
- `run`: `main.py`에서 호출됨
```
