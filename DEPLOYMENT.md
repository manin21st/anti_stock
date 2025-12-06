# 클라우드 서버(VPS) 배포 가이드

이 문서는 Anti-Stock 자동매매 프로그램을 클라우드 서버(예: AWS EC2, Vultr, DigitalOcean 등)에 배포하는 방법을 안내합니다.

## 1. 사전 준비
*   **클라우드 서버**: Ubuntu 22.04 LTS 또는 24.04 LTS 권장.
*   **Python 버전**: 3.10 이상 (3.11 권장).
*   **GitHub 계정**: 코드가 업로드된 저장소 접근 권한.

## 2. 서버 접속 및 기본 설정
터미널(SSH)을 통해 서버에 접속합니다.
```bash
ssh root@<서버_IP_주소>
```

시스템 패키지를 업데이트하고 필요한 도구를 설치합니다.
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install git python3-pip python3-venv -y
```

## 3. 프로젝트 클론 (Clone)
GitHub에서 프로젝트를 내려받습니다.
```bash
git clone https://github.com/manin21st/anti_stock.git
cd anti_stock
```

## 4. 가상환경 설정
프로젝트별 독립된 Python 환경을 생성합니다.
```bash
# 가상환경 생성
python3 -m venv venv

# 가상환경 활성화
source venv/bin/activate
```

## 5. 의존성 설치
`requirements.txt`에 명시된 라이브러리를 설치합니다.
```bash
pip install -r requirements.txt
```

## 6. 설정 파일 확인
`config/strategies.yaml` 등의 설정 파일이 올바른지 확인합니다.
(보안상 `portfolio_state.json` 등은 초기화 상태일 수 있습니다.)

## 7. 서버 실행 (백그라운드)
서버 연결이 끊겨도 프로그램이 계속 실행되도록 `nohup` 또는 `systemd`를 사용합니다.

### 방법 A: 간단 실행 (nohup)
```bash
# 로그를 파일에 남기며 백그라운드 실행
nohup python main.py > server.log 2>&1 &

# 실행 확인
ps aux | grep python
```

### 방법 B: 서비스 등록 (Systemd) - 권장
서버 재부팅 시 자동 실행되도록 설정합니다.

1. 서비스 파일 생성: `sudo nano /etc/systemd/system/anti_stock.service`
```ini
[Unit]
Description=Anti-Stock Trading Bot
After=network.target

[Service]
User=root
WorkingDirectory=/root/anti_stock
ExecStart=/root/anti_stock/venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

2. 서비스 시작 및 등록:
```bash
sudo systemctl daemon-reload
sudo systemctl start anti_stock
sudo systemctl enable anti_stock
```

## 8. 접속 확인
브라우저에서 `http://<서버_IP_주소>:8000`으로 접속하여 로그인 페이지가 뜨는지 확인합니다.
(방화벽 설정에서 8000번 포트가 열려 있어야 합니다.)

## 9. 로그인 인증
최초 실행 시 생성된 OTP를 확인하려면 로그를 봐야 합니다.
```bash
# 실시간 로그 확인
tail -f anti_stock.log
# 또는
cat server.log
```
로그에 출력된 `[LOGIN OTP]` 6자리를 입력하여 로그인합니다.
