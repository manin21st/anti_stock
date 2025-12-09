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

### 3. 서비스 관리 및 로그 확인 (필수)
서비스가 등록된 후에는 아래 명령어들로 상태를 확인하고 관리할 수 있습니다.

```bash
# 상태 확인 (Active: active (running) 인지 확인)
sudo systemctl status anti_stock

# 서비스 중지
sudo systemctl stop anti_stock

# 서비스 시작
sudo systemctl start anti_stock

# 서비스 재시작 (코드 업데이트 후 필수)
sudo systemctl restart anti_stock

# 실시간 로그 확인 (실행 중인 프로그램의 출력 보기)
journalctl -u anti_stock -f
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

## 10. 방화벽 설정 (접속 불가 시)
만약 `http://<서버_IP>:8000` 접속이 안 된다면 클라우드 방화벽(Security Group/ACG) 설정을 확인해야 합니다.

### 네이버 클라우드 플랫폼 (Naver Cloud)
1. 콘솔에서 **Server > ACG** 메뉴로 이동하거나, 서버 상세 정보의 **ACG 수정** 버튼 클릭.
2. 적용된 ACG를 선택하고 **Inbound 규칙** 설정.
3. 규칙 추가:
    *   **프로토콜**: TCP
    *   **접근 소스**: 0.0.0.0/0
    *   **목적지 포트**: 8000
    *   **허용/거부**: 허용
4. **적용** 버튼 클릭.

### AWS EC2
1. **Security Groups** 설정으로 이동.
2. **Inbound Rules** 편집.
3. **Add Rule**: Custom TCP, Port 8000, Source 0.0.0.0/0.

## 11. 도메인 연결 (Cloudflare & Nginx)
Cloudflare를 통해 `https://botocks.bhsong.org` 처럼 도메인으로 접속하려면, **Nginx(웹 서버)**를 설치하여 포트를 연결해 주어야 합니다. (Cloudflare Proxy는 8000번 포트를 기본 지원하지 않음)

### 1. Nginx 설치
```bash
sudo apt install nginx -y
```

### 2. Nginx 설정
설정 파일을 생성합니다.
```bash
sudo nano /etc/nginx/sites-available/anti_stock
```

아래 내용을 붙여넣으세요 (`server_name`에 본인 도메인 입력):
```nginx
server {
    listen 80;
    server_name botocks.bhsong.org;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 웹소켓 지원 (로그/차트 실시간 업데이트용)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 3. 설정 적용
```bash
# 심볼릭 링크 생성
sudo ln -s /etc/nginx/sites-available/anti_stock /etc/nginx/sites-enabled/

# 기본 설정 제거 (선택 사항)
sudo rm /etc/nginx/sites-enabled/default

# Nginx 재시작
sudo systemctl restart nginx
```

### 4. Cloudflare 설정
1. **DNS**: `botocks` A 레코드의 Proxy Status를 **Proxied (주황색 구름)**으로 설정.
2. **SSL/TLS**: **Full** 모드 권장 (또는 Flexible).

이제 `http://botocks.bhsong.org` (또는 https)로 접속하면 8000번 포트 없이 접속 가능합니다.

## 12. Nginx 설치 오류 해결 (IPv6 문제)
만약 `apt install nginx` 중 `Address family not supported by protocol` 오류가 발생한다면, 서버에서 IPv6가 비활성화되어 있기 때문입니다.

**해결 방법:**
1. 기본 설정 파일 편집:
   ```bash
   sudo nano /etc/nginx/sites-available/default
   ```
2. IPv6 관련 설정 주석 처리:
   ```nginx
   # listen [::]:80 default_server;  <-- 이 줄 앞에 #을 붙여 주석 처리
   ```
3. 설치 재개:
   ```bash
   sudo apt --fix-broken install
   ```

## 13. UI 멈춤 현상 해결 (WebSocket 보안 문제)
HTTPS(도메인)로 접속 시 UI가 멈추거나 로그가 안 뜬다면, 브라우저가 보안상 `ws://` (비암호화 웹소켓) 연결을 차단하기 때문입니다.

**해결 방법:**
1. `web/static/app.js` 파일에서 WebSocket 연결 코드가 `wss://`를 지원하도록 수정되었는지 확인합니다. (최신 코드에 반영됨)
2. 서버에서 코드를 최신화합니다:
   ```bash
   git pull
   ```
3. 서버 프로세스를 재시작합니다.
4. 브라우저 캐시를 강력 새로고침(Ctrl+F5)합니다.
