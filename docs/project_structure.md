# 프로젝트 파일 구조 (Project Structure)

이 문서는 `Anti-Stock` 시스템의 디렉토리 및 핵심 파일들의 역할과 구조를 설명합니다.

---

## 📂 최상위 디렉토리 (Root)
| 파일명 | 역할 |
|---|---|
| `main.py` | **프로그램 진입점 (Entry Point)**. 시스템 초기화 및 메인 엔진 구동 |
| `tps_server.py` | API 속도 제한(TPS)을 관리하는 로컬 서버 (별도 프로세스로 실행) |
| `DEPLOYMENT.md` | 배포 및 실행 가이드 |

---

## 📂 core/ (핵심 로직)
시스템의 뼈대를 이루는 모듈들이 모여 있습니다.

| 파일명 | 역할 | 관련 로직 |
|---|---|---|
| `engine.py` | **중앙 통제실**. 전체 시스템 순환 루프(Loop) 및 상태 관리 | [logic_flow.md](logic_flow.md) |
| `broker.py` | **증권사 통신**. 주문 전송, 잔고 조회 등 실제 API 호출 담당 | 1회성, 후처리 |
| `kis_api.py` | 한국투자증권(KIS) REST API 래퍼 (Wrapper) | 통신 |
| `market_data.py` | **시세 수집**. 1분봉/현재가 데이터 폴링 및 가공 | 반복(장 중) |
| `portfolio.py` | **계좌/잔고 관리**. 보유 종목 및 수익률 계산, 매도 판단 지원 | 후처리 |
| `config.py` | **설정 행위자(Config)**. 시스템 및 전략 설정 관리 | 공통 |
| `risk.py` | **리스크 행위자(Risk)**. 주문 전 미수/비중/한도 체크 (안전장치) | 진입 판단 |
| `trade.py` | **거래 행위자(Trader)**. 매매 기록(Log) 관리 및 UI 이벤트 통보 | 후처리 |
| `universe.py` | **유니버스 행위자(Universe)**. 감시 대상 종목 선정 및 구독 관리 | 1회성/반복 |
| `scanner.py` | **조건 검색**. 시장 종목 스캔 로직 | 유니버스 보조 |
| `backtester.py` | 전략 시뮬레이션 및 과거 데이터 테스트 엔진 | 분석 |
| `database.py` | SQLite DB 연결 및 세션 관리 | 공통 |
| `dao.py` | DB 쿼리(CRUD) 실행 객체들 | 공통 |
| `models.py` | DB 테이블 스키마 정의 (Trade, Config 등) | 공통 |

---

## 📂 strategies/ (매매 전략)
실제 매수/매도 판단을 내리는 두뇌입니다.

| 파일명 | 역할 |
|---|---|
| `base.py` | 모든 전략의 부모 클래스. 공통 기능(로깅, 설정 등) 제공 |
| `ma_trend.py` | **이동평균 추세 추종 전략** (현재 핵심 사용 전략) |
| `bollinger_mr.py` | 볼린저 밴드 반전(Mean Reversion) 전략 |
| `breakout.py` | 돌파 매매 전략 |

---

## 📂 web/ (대시보드 UI)
웹 브라우저로 시스템을 제어하고 모니터링하는 인터페이스입니다.

| 위치 | 설명 |
|---|---|
| `server.py` | Flask 웹 서버 구동 |
| `templates/` | `index.html`(대시보드), `journal.html`(매매일지) 등 화면 파일 |
| `static/` | CSS, JS 등 정적 리소스 |

---

## 📂 config/ (설정)
| 파일명 | 역할 |
|---|---|
| `strategies.yaml` | **전략 설정**. 사용할 전략, 리스크 비율, 매매 타임프레임 등 정의 |
| `secrets.yaml` | **보안 설정**. API Key, 계좌번호 등 (절대 공유 금지) |

---

## 📂 utils/ (도구)
| 파일명 | 역할 |
|---|---|
| `data_loader.py` | 백테스트용 과거 차트 데이터 다운로드 및 로드 |
| `telegram.py` | 텔레그램 알림 발송 봇 |
