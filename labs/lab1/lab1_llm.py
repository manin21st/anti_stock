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
사용자의 자연어 설명을 분석하여 "진입/청산 조건(Boolean Expression)"과 "실행 액션(Dictionary)"으로 분리하여 변환하세요.

[사용 가능한 변수 목록 (조건식용)]
1. 시세 데이터: price, volume, prev_price, prev_volume
2. 보조 지표: ma_short (단기이평), ma_long (장기이평), prev_ma_short, prev_ma_long, avg_volume_long
3. 자산/수익률: pnl_pct (수익률%), cash (보유현금), total_asset (총자산), rsi (RSI지표)

[실행 액션 파라미터 (Action Dictionary)]
- 매수 시: {'target_pct': 0.1} (자산 10% 매수), {'buy_amt': 1000000} (100만원 매수), {'buy_qty': 10} (10주 매수)
- 매도 시: {'qty_pct': 1.0} (전량 매도), {'qty_pct': 0.5} (절반 매도), {'qty': 10} (10주 매도)

[출력 형식]
반드시 아래와 같은 JSON 형식으로만 출력하세요. 마크다운(```)이나 추가 설명은 포함하지 마세요.
{
    "condition": "Python 조건식 (예: price > ma_short)",
    "action": "{Action Dictionary 문자열} (예: {'target_pct': 0.2})"
}

[예시]
입력: "골든크로스 발생 시 자산의 20% 매수"
출력: {"condition": "price > ma_short and prev_price <= prev_ma_short", "action": "{'target_pct': 0.2}"}

입력: "수익률이 -3% 이하이면 전량 손절"
출력: {"condition": "pnl_pct <= -3.0", "action": "{'qty_pct': 1.0}"}
"""
        return prompt.strip()

    def generate_condition(self, user_description: str) -> dict:
        """
        사용자의 자연어 설명을 받아 파이썬 조건식과 액션을 포함한 딕셔너리를 반환합니다.
        """
        if not self.model:
            return {"code": "Error: 모델이 초기화되지 않았습니다."}

        system_prompt = self._get_system_prompt()
        full_prompt = f"{system_prompt}\n\n[사용자 입력]\n{user_description}\n\n[출력]\n"

        import time
        import json
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(full_prompt)
                # 불필요한 공백 및 마크다운 제거
                result = response.text.replace('```json', '').replace('```', '').strip()
                
                try:
                    # JSON 파싱 시도
                    parsed = json.loads(result)
                    # 프론트엔드 호환성을 위해 code 필드도 추가 (하위 호환성)
                    if 'condition' in parsed:
                        parsed['code'] = parsed['condition']
                    return parsed
                except json.JSONDecodeError:
                    # JSON 파싱 실패 시, 기존처럼 단순 문자열로 가정하고 code에 담음
                    return {"code": result, "raw": result}

            except Exception as e:
                # 429 에러 체크 (Rate Limit)
                if "429" in str(e):
                    print(f"[경고] API 호출 한도 초과 (429). {retry_delay}초 후 재시도합니다... ({attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # 지수 백오프
                else:
                    return {"code": f"Error: 변환 중 오류 발생 ({e})"}
        
        return {"code": "Error: API 호출 실패 (재시도 횟수 초과)"}

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
