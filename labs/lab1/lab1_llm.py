import sys

# Windows 환경에서 한글 출력이 깨지는 것을 방지하기 위한 설정
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

import os
import warnings
# Deprecation Warning 숨기기 (google.generativeai)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

import google.generativeai as genai
from typing import Optional

import yaml

# [설정] 프로젝트 루트 경로 찾기 (labs/lab1/lab1_llm.py 기준)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SECRETS_PATH = os.path.join(BASE_DIR, "config", "secrets.yaml")

def load_api_key():
    """config/secrets.yaml에서 API 키를 로드합니다."""
    try:
        if os.path.exists(SECRETS_PATH):
            with open(SECRETS_PATH, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return data.get('llm', {}).get('google_api_key')
    except Exception as e:
        print(f"[경고] secrets.yaml 로드 실패: {e}")
    return os.getenv("GOOGLE_API_KEY")

API_KEY = load_api_key()

class ConditionGenerator:
    """
    자연어 설명을 입력받아 lab1_cond.py에서 실행 가능한 
    Python 조건식(boolean expression)으로 변환하는 LLM 에이전트입니다.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or API_KEY
        if not self.api_key:
            print(f"[경고] API 키가 설정되지 않았습니다. ({SECRETS_PATH})")
            # 실제 실행 시 에러를 방지하기 위해 더미 키 설정 (동작은 안 함)
            self.api_key = "YOUR_API_KEY_HERE"
        
        # Gemini 모델 설정
        try:
            genai.configure(api_key=self.api_key)
            # gemini-2.0-flash에서 429 Quota 에러 발생. 
            # 목록에 있는 안정적인 별칭 모델 사용 (gemini-flash-latest)
            self.model = genai.GenerativeModel('gemini-flash-latest')
        except Exception as e:
            print(f"[오류] 모델 초기화 실패: {e}")
            self.model = None

    def list_available_models(self):
        """
        사용 가능한 모델 목록을 출력합니다.
        """
        try:
            print("--- 사용 가능한 모델 목록 ---")
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    print(f"- {m.name}")
            print("---------------------------")
        except Exception as e:
            print(f"모델 목록 조회 실패: {e}")

    def _get_system_prompt(self) -> str:
        """
        LLM에게 부여할 역할 및 문맥(사용 가능한 변수 등)을 정의합니다.
        """
        prompt = """
[역할]
당신은 Python 주식 거래 시스템의 전략 조건을 작성하는 전문가입니다.
사용자가 자연어로 전략 조건(예: "가격이 20일 이동평균선보다 높다")을 설명하면,
이를 시스템에서 즉시 실행 가능한 Python 조건식(Boolean Expression)으로 변환하세요.

[사용 가능한 변수 목록]
이 변수들은 코드 내에서 이미 정의되어 있다고 가정합니다.
오직 아래 변수들만 사용해야 합니다.

1. 시세 데이터
   - price (int): 현재가
   - volume (int): 현재 거래량
   - prev_price (int): 전일 종가 (또는 이전 봉 종가)
   - prev_volume (int): 전일 거래량

2. 보조 지표 (이동평균선 등)
   - ma_short (float): 단기 이평선 값 (예: 5일선)
   - ma_long (float): 장기 이평선 값 (예: 20일선)
   - prev_ma_short (float): 이전 봉의 단기 이평선
   - prev_ma_long (float): 이전 봉의 장기 이평선
   - avg_volume_long (float): 장기 평균 거래량

3. 수익률 정보
   - pnl_pct (float): 현재 수익률 (단위: %, 예: 3.5 = 3.5% 수익)

[제약 사항]
1. 결과는 오직 Python 조건식 문자열(String) 하나만 출력하세요. 설명이나 마크다운(```)을 포함하지 마세요.
2. 조건식은 True 또는 False로 평가될 수 있어야 합니다.
3. import 문을 사용하지 마세요.
4. 알 수 없는 변수나 함수를 사용하지 마세요.
5. 복잡한 로직은 괄호()를 사용하여 명확히 표현하세요.

[예시]
입력: 현재가가 20일 이평선 위에 있다
출력: price > ma_long

입력: 거래량이 10000주 이상이고 수익률이 5% 이상일 때
출력: volume >= 10000 and pnl_pct >= 5.0

입력: 골든 크로스 (단기 이평이 장기 이평을 상향 돌파)
출력: prev_ma_short <= prev_ma_long and ma_short > ma_long
"""
        return prompt.strip()

    def generate_condition(self, user_description: str) -> str:
        """
        사용자의 자연어 설명을 받아 파이썬 조건식을 반환합니다.
        """
        if not self.model:
            return "Error: 모델이 초기화되지 않았습니다."

        system_prompt = self._get_system_prompt()
        full_prompt = f"{system_prompt}\n\n[사용자 입력]\n{user_description}\n\n[출력]\n"

        import time
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(full_prompt)
                # 불필요한 공백 및 마크다운 제거
                result = response.text.replace('```python', '').replace('```', '').strip()
                return result
            except Exception as e:
                # 429 에러 체크 (Rate Limit)
                if "429" in str(e):
                    print(f"[경고] API 호출 한도 초과 (429). {retry_delay}초 후 재시도합니다... ({attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # 지수 백오프
                else:
                    return f"Error: 변환 중 오류 발생 ({e})"
        
        return "Error: API 호출 실패 (재시도 횟수 초과)"

# --- 실행 테스트 (Main) ---
if __name__ == "__main__":
    agent = ConditionGenerator()
    # agent.list_available_models() # 디버깅용
    
    print("=== 조건식 생성 에이전트 테스트 ===")
    print("종료하려면 'q'를 입력하세요.\n")
    
    while True:
        user_input = input("조건 입력 > ")
        if user_input.lower() in ['q', 'quit', 'exit']:
            break
            
        if not user_input.strip():
            continue
            
        print("생성 중...", end='', flush=True)
        py_code = agent.generate_condition(user_input)
        print(f"\r[결과]: {py_code}")
        print("-" * 40)
