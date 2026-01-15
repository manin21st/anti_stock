import pandas as pd
import os
import sys
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

# 프로젝트 루트 경로 추가 (core 모듈 import를 위해)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import interface as ka

logger = logging.getLogger(__name__)

class DataLoader:
    """
    [데이터 로더]
    로컬 CSV 파일에서 데이터를 읽거나, KIS API를 통해 데이터를 다운로드하여 저장하는 역할을 담당합니다.
    """
    def __init__(self, data_dir: str = "data"):
        # 데이터 저장 경로 설정 (기본: 프로젝트 루트/data)
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), data_dir)
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        
        # 인증 확인 (필요한 경우)
        # ka.auth()는 보통 메인 애플리케이션에서 호출되지만, 
        # 단독 스크립트로 실행될 경우를 대비해 여기서 체크할 수도 있습니다.
        pass

    def load_data(self, symbol: str, start_date: str = None, end_date: str = None, timeframe: str = "D") -> pd.DataFrame:
        """
        로컬 CSV 파일에서 데이터를 로드합니다.
        
        Args:
            symbol (str): 종목코드 (예: '005930')
            start_date (str, optional): 시작 날짜 (YYYYMMDD)
            end_date (str, optional): 종료 날짜 (YYYYMMDD)
            timeframe (str): 주기 ('D': 일봉, '1m': 1분봉)
            
        Returns:
            pd.DataFrame: 데이터프레임 (date, open, high, low, close, volume 등)
        """
        file_path = self._get_file_path(symbol, timeframe)
        if not os.path.exists(file_path):
            logger.debug(f"[{symbol}] 데이터 파일 없음 (주기: {timeframe})")
            return pd.DataFrame()

        try:
            # CSV 읽기 (날짜/시간은 문자열 유지를 위해 dtype 지정)
            df = pd.read_csv(file_path, dtype={'date': str, 'time': str})
            
            # 날짜 필터링
            if start_date:
                df = df[df['date'] >= start_date]
            if end_date:
                df = df[df['date'] <= end_date]
            
            # 정렬 (날짜 -> 시간 순)
            sort_cols = ['date', 'time'] if 'time' in df.columns else ['date']
            df = df.sort_values(sort_cols).reset_index(drop=True)
            return df
        except Exception as e:
            logger.error(f"[{symbol}] 데이터 로드 실패: {e}")
            return pd.DataFrame()

    def download_data(self, symbol: str, start_date: str, end_date: str, timeframe: str = "D") -> pd.DataFrame:
        """
        KIS API를 통해 데이터를 다운로드하고 로컬 파일에 병합(저장)합니다.
        자동으로 부족한 기간의 데이터를 API로 요청하여 채워 넣습니다.
        
        Args:
            symbol (str): 종목코드
            start_date (str): 시작 날짜 (YYYYMMDD)
            end_date (str): 종료 날짜 (YYYYMMDD)
            timeframe (str): 'D' (일봉) 또는 '1m', '3m' 등 (분봉)
        """
        logger.info(f"데이터 다운로드 시작: {symbol} ({start_date} ~ {end_date}, 주기: {timeframe})")
        
        # 0. API 인증 상태 확인 및 자동 인증 시도
        try:
            env = ka.getTREnv()
            if env is None or isinstance(env, tuple):
                 # 인증이 안 되어 있다면 기본 VPS(모의/실전) 환경으로 인증 시도
                 ka.auth(svr="vps") 
        except:
             pass

        if timeframe == "D":
            return self._download_daily_data(symbol, start_date, end_date)
        else:
            # 분봉 데이터 (기본 1분봉으로 수집)
            return self._download_minute_data(symbol, start_date, end_date)

    def _get_file_path(self, symbol: str, timeframe: str = "D") -> str:
        """저장할 파일 경로 생성 (일봉: _daily.csv, 분봉: _1min.csv)"""
        suffix = "daily" if timeframe == "D" else "1min" # 모든 분봉은 1분봉 데이터 기반
        return os.path.join(self.data_dir, f"{symbol}_{suffix}.csv")

    def _download_daily_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """[내부] 일봉 데이터 다운로드 로직"""
        # 기존에 저장된 데이터 로드
        existing_df = self.load_data(symbol, timeframe="D")
        
        all_df_list = []
        current_end_dt = end_date
        
        # 과거 데이터부터 역순으로 조회하며 수집
        while True:
            # API 호출 (일봉)
            res = ka.fetch_daily_chart(symbol, start_date, current_end_dt)
            if res.isOK():
                chunk_df = pd.DataFrame(res.getBody().output2)
                if chunk_df.empty: break
                    
                # 컬럼명 매핑 (API 응답 Key -> 내부 표준 Key)
                chunk_df = chunk_df.rename(columns={
                    "stck_bsop_date": "date",
                    "stck_oprc": "open", "stck_hgpr": "high", "stck_lwpr": "low", "stck_clpr": "close", "acml_vol": "volume"
                })
                
                # 숫자형으로 변환
                cols = ["open", "high", "low", "close", "volume"]
                chunk_df[cols] = chunk_df[cols].apply(pd.to_numeric)
                all_df_list.append(chunk_df)
                
                # 조회된 데이터 중 가장 오래된 날짜 확인
                oldest_date = chunk_df['date'].min()
                if oldest_date <= start_date: break # 시작일 도달 시 종료
                    
                # 다음 조회 종료일 설정 (가장 오래된 날짜 하루 전)
                oldest_dt_obj = datetime.strptime(oldest_date, "%Y%m%d")
                current_end_dt = (oldest_dt_obj - timedelta(days=1)).strftime("%Y%m%d")
                if current_end_dt < start_date: break
            else:
                logger.error(f"API 오류: {res.getErrorMessage()}")
                break
        
        # 데이터 병합 및 저장 호출
        return self._save_and_merge(symbol, existing_df, all_df_list, "D", start_date, end_date)

    def _download_minute_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """[내부] 분봉 데이터 다운로드 로직 (1분봉 기준)"""
        existing_df = self.load_data(symbol, timeframe="1m")
        all_df_list = []
        
        try:
            s_dt = datetime.strptime(start_date, "%Y%m%d")
            e_dt = datetime.strptime(end_date, "%Y%m%d")
        except:
            return pd.DataFrame()
             
        current_date_obj = e_dt
        
        # 날짜별로 반복 (최신순 -> 과거순)
        while current_date_obj >= s_dt:
            target_date = current_date_obj.strftime("%Y%m%d")
            
            # 주말(토, 일)은 건너뜀
            if current_date_obj.weekday() >= 5:
                current_date_obj -= timedelta(days=1)
                continue

            logger.info(f"[{symbol}] 분봉 데이터 수집 중: {target_date}...")
            
            target_time = "153000" # 장 마감 시간부터 역순 조회
            day_df_list = []
            
            while True:
                # API 호출 (과거 분봉)
                res = ka.fetch_past_minute_chart(symbol, target_date, target_time)
                
                if not res or not res.isOK():
                     logger.error(f"분봉 API 오류: {res.getErrorMessage() if res else '응답 없음'}")
                     break

                o2 = res.getBody().output2
                if not o2: break # 데이터 없음
                
                chunk = pd.DataFrame(o2)
                chunk = chunk.rename(columns={
                    "stck_bsop_date": "date",
                    "stck_cntg_hour": "time",
                    "stck_prpr": "close", "stck_oprc": "open", "stck_hgpr": "high", "stck_lwpr": "low", "cntg_vol": "volume"
                })
                
                chunk = chunk[["date", "time", "open", "high", "low", "close", "volume"]]
                cols = ["open", "high", "low", "close", "volume"]
                chunk[cols] = chunk[cols].apply(pd.to_numeric)
                
                day_df_list.append(chunk)
                
                # 다음 조회 시간 설정 (1분 전으로 이동)
                oldest_time = chunk['time'].min() # 예: "150000"
                
                if oldest_time <= "090000": # 장 시작 시간 도달
                    break
                    
                t_obj = datetime.strptime(oldest_time, "%H%M%S")
                next_t_obj = t_obj - timedelta(minutes=1)
                target_time = next_t_obj.strftime("%H%M%S")
                
                if target_time < "090000":
                    break
                    
                # Rate Limiting은 Core 레벨의 RateLimiterService에서 자동 처리됨
                pass 
            
            if day_df_list:
                day_all = pd.concat(day_df_list)
                all_df_list.append(day_all)
            
            # 하루 전으로 이동
            current_date_obj -= timedelta(days=1)
            
        return self._save_and_merge(symbol, existing_df, all_df_list, "1m", start_date, end_date)

    def _save_and_merge(self, symbol, existing_df, new_dfs, timeframe, start, end):
        """[공통] 기존 데이터와 신규 데이터를 병합하고 중복 제거 후 파일로 저장"""
        if new_dfs:
            new_df = pd.concat(new_dfs)
            if not existing_df.empty:
                full_df = pd.concat([existing_df, new_df])
            else:
                full_df = new_df
                
            # 중복 제거 및 정렬
            unique_cols = ['date'] if timeframe=="D" else ['date', 'time']
            full_df = full_df.drop_duplicates(subset=unique_cols).sort_values(unique_cols).reset_index(drop=True)
            
            file_path = self._get_file_path(symbol, timeframe)
            full_df.to_csv(file_path, index=False)
            logger.info(f"[{symbol}] 저장 완료: {len(full_df)}행 -> {file_path}")
            
            # 요청된 기간의 데이터만 필터링하여 반환
            return full_df[(full_df['date'] >= start) & (full_df['date'] <= end)]
        
        return pd.DataFrame()


    def check_availability(self, symbol: str, start_date: str, end_date: str, timeframe: str = "D") -> bool:
        """
        요청한 기간의 데이터가 로컬에 존재하는지 확인합니다.
        (백테스트 실행 전 데이터 준비 여부 확인용)
        """
        df = self.load_data(symbol, start_date, end_date, timeframe=timeframe)
        if df.empty:
            return False
        
        # 간단히 데이터 존재 여부만 확인 (엄격한 날짜 커버리지 체크는 아님)
        return len(df) > 0
