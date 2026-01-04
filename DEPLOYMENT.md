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
git clone --recursive https://github.com/manin21st/anti_stock.git
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

# 만약 "error: externally-managed-environment" 오류가 발생하면 아래 명령어를 사용하세요:
pip install -r requirements.txt --break-system-packages

```

## 6. 설정 파일 확인
`config/strategies.yaml` 등의 설정 파일이 올바른지 확인합니다.
(보안상 `portfolio_state.json` 등은 초기화 상태일 수 있습니다.)

## 7. 서버 실행 (백그라운드)
서버 연결이 끊겨도 프로그램이 계속 실행되도록 `systemd`를 사용합니다.

### 서비스 등록 (Systemd) - 권장
서버 재부팅 시 자동 실행되도록 설정합니다.

2. 서비스 파일 생성 (웹 서버): `sudo nano /etc/systemd/system/anti_stock.service`
```ini
[Unit]
Description=Anti-Stock Trading Bot (Web)
After=network.target

[Service]
User=root
WorkingDirectory=/root/anti_stock
ExecStart=/root/anti_stock/venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

3. 서비스 시작 및 등록:
```bash
sudo systemctl daemon-reload

# 웹 서버 서비스만 시작하면 TPS도 자동으로 같이 시작됩니다 (Wants 설정)
sudo systemctl enable anti_stock
sudo systemctl start anti_stock

# 이제 메인 서비스만 재시작해도 TPS 서버가 자동으로 같이 재시작됩니다 (PartOf 설정)
# sudo systemctl restart anti_stock
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
tail -f logs/anti_stock.log
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

# TPS 서버 (추가)
server {
    listen 80;
    server_name tps.bhsong.org;

    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
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
1. **DNS**: 
    - `botocks` A 레코드: Proxy Status **Proxied (주황색 구름)**.
    - `tps` A 레코드: Proxy Status **Proxied (주황색 구름)**.
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

## 14. 듀얼 인스턴스 구성 (모의/실전 동시 운영)
클라우드 서버 하나에서 **모의투자(anti_stock)**와 **실전투자(bot_stock)**를 동시에 운영하는 구성 방법입니다.
두 인스턴스는 동일한 GitHub 소스 코드를 사용하되, 서로 다른 폴더와 설정, 포트를 사용합니다.

### 1. 디렉토리 구조 생성 및 클론
```bash
# 홈 디렉토리로 이동
cd ~

# 1) 모의투자용 (기존): /root/anti_stock
# (이미 존재한다고 가정)

# 2) 실전투자용 (신규): /root/bot_stock
# 깃허브에서 동일한 소스를 'bot_stock' 이름으로 클론
git clone --recursive https://github.com/manin21st/anti_stock.git bot_stock
```

### 2. 실전투자용 환경 설정
실전투자 인스턴스(`bot_stock`)를 위한 독립적인 가상환경과 설정을 구성합니다.

1.  **가상환경 생성 및 의존성 설치**:
    ```bash
    cd ~/bot_stock
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    # (오류 발생 시: pip install -r requirements.txt --break-system-packages)
    ```

2.  **KIS API 실전투자 키 설정 (`~/KIS/config/kis_devlp.yaml`)**:
    실전투자를 위해서는 KIS API 설정 파일에 **실전투자용 앱키와 계좌번호**가 입력되어 있어야 합니다.
    (이 파일은 모든 인스턴스가 공유합니다.)
    
    `vi ~/KIS/config/kis_devlp.yaml` (또는 해당 경로의 파일)을 열어 확인하세요:

    ```yaml
    # 실전투자 (반드시 입력해야 함)
    my_app: "실전투자_앱키_붙여넣기"
    my_sec: "실전투자_시크릿키_붙여넣기"
    my_acct_stock: "실전계좌_8자리"
    
    # 모의투자 (기존 사용 중)
    paper_app: "모의투자_앱키"
    # ...
    ```

3.  **포트 및 환경 설정 수정 (`config/strategies.yaml`)**:
    
    **1) 모의투자 (`anti_stock`) 포트 변경 (8000 -> 9000)**
    기존 모의투자 서버의 포트를 9000으로 옮겨 실전투자 서버가 8000번(메인)을 쓸 수 있게 합니다.
    `vi ~/anti_stock/config/strategies.yaml`
    ```yaml
    system:
      server_port: 9000        # <-- 9000으로 변경 (모의투자)
      env_type: paper
      # ...
    ```
    변경 후 재시작: `sudo systemctl restart anti_stock`

    **2) 실전투자 (`bot_stock`) 설정 (Port 8000)**
    새로 만든 실전투자 서버는 기본 포트(8000)를 그대로 사용합니다.
    `vi ~/bot_stock/config/strategies.yaml`
    ```yaml
    system:
      server_port: 8000        # <-- 8000 (기본값, 실전투자 메인)
      env_type: prod           # <-- paper에서 prod로 변경
      market_type: KRX
      scanner_mode: volume
      universe: []
      use_auto_scanner: true
      watchlist_group_code: '000'
    ```
    *   **주의**: `database`와 `telegram` 설정은 `secrets.yaml`에 별도로 작성해야 합니다.

### 3. 서비스 파일 등록 (Bot Stock)
실전투자용 시스템 서비스를 별도로 등록하여 자동 실행되게 합니다.

**1) 웹 서버 서비스 생성 (`sudo nano /etc/systemd/system/bot_stock.service`)**
```ini
[Unit]
Description=Bot Stock Trading (Real)
After=network.target

[Service]
User=root
WorkingDirectory=/root/bot_stock
# 포트 인자는 system_config.json이 우선하지만, 명시적으로 적어도 됩니다.
ExecStart=/root/bot_stock/venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

**2) 서비스 시작 및 등록**
```bash
sudo systemctl daemon-reload
sudo systemctl enable bot_stock
sudo systemctl start bot_stock
```

### 4. 일괄 업데이트 스크립트 (`update_all.sh`)
두 인스턴스의 소스 코드를 한 번에 업데이트하고 재시작하는 스크립트입니다.

`vi ~/update_all.sh` 작성:
```bash
#!/bin/bash

echo "=================================="
echo "Updating Anti-Stock (Paper)..."
echo "=================================="
cd ~/anti_stock
git pull --recurse-submodules
sudo systemctl restart anti_stock

echo ""
echo "=================================="
echo "Updating Bot-Stock (Real)..."
echo "=================================="
cd ~/bot_stock
git pull --recurse-submodules
sudo systemctl restart bot_stock

echo "Update Completed!"
```

**사용법:**
```bash
chmod +x ~/update_all.sh
./update_all.sh
```

### 5. Nginx 설정 업데이트 (선택 사항)
실전투자를 메인 도메인(`botocks`)으로, 모의투자를 서브 포트나 별도 도메인으로 연결합니다.

```nginx
# 실전투자 (Main): 8000
server {
    listen 80;
    server_name botocks.bhsong.org;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}

# 모의투자 (Paper): 9000 -> antistock.bhsong.org
server {
    listen 80;
    server_name antistock.bhsong.org;

    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 웹소켓 지원
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 6. 포트 및 방화벽 확인
*   **실전투자**: `http://<IP>:8000` (또는 도메인)
*   **모의투자**: `http://<IP>:9000`
*   클라우드 방화벽(ACG/Security Group)에서 **9000** 포트도 허용("Inbound Allow")해주어야 합니다.

