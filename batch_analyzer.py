import pandas as pd
import pandas_ta as ta
import yfinance as yf
import pyupbit
import json
import time
import traceback
from datetime import datetime
import os

# --- 설정 ---
ASSET_LIST = [
    # --- 코인 (Upbit) ---
    {"name": "비트코인", "ticker": "KRW-BTC", "source": "upbit", "category": "코인"},
    {"name": "솔라나", "ticker": "KRW-SOL", "source": "upbit", "category": "코인"},
    {"name": "리플", "ticker": "KRW-XRP", "source": "upbit", "category": "코인"},
    {"name": "도지코인", "ticker": "KRW-DOGE", "source": "upbit", "category": "코인"},
    
    # --- 스테이블 코인 ---
    {"name": "테더 (USDT)", "ticker": "KRW-USDT", "source": "upbit", "category": "스테이블 코인"},
    {"name": "USD 코인 (USDC)", "ticker": "KRW-USDC", "source": "upbit", "category": "스테이블 코인"},
    {"name": "다이 (DAI)", "ticker": "DAI-USD", "source": "yahoo", "category": "스테이블 코인"},
    {"name": "팩스 골드 (PAXG)", "ticker": "PAXG-USD", "source": "yahoo", "category": "스테이블 코인"},
    
    # --- 매그니피센트 7 (Yahoo) ---
    {"name": "애플", "ticker": "AAPL", "source": "yahoo", "category": "주식"},
    {"name": "마이크로소프트", "ticker": "MSFT", "source": "yahoo", "category": "주식"},
    {"name": "알파벳", "ticker": "GOOGL", "source": "yahoo", "category": "주식"},
    {"name": "아마존", "ticker": "AMZN", "source": "yahoo", "category": "주식"},
    {"name": "엔비디아", "ticker": "NVDA", "source": "yahoo", "category": "주식"},
    {"name": "메타", "ticker": "META", "source": "yahoo", "category": "주식"},
    {"name": "테슬라", "ticker": "TSLA", "source": "yahoo", "category": "주식"},
    
    # --- ETF (Yahoo) ---
    {"name": "SPY", "ticker": "SPY", "source": "yahoo", "category": "ETF"},
    {"name": "QQQ", "ticker": "QQQ", "source": "yahoo", "category": "ETF"},
    {"name": "TQQQ", "ticker": "TQQQ", "source": "yahoo", "category": "ETF"},
    {"name": "SOXL", "ticker": "SOXL", "source": "yahoo", "category": "ETF"},
    
    # --- 선물 (Yahoo) ---
    {"name": "금 선물", "ticker": "GC=F", "source": "yahoo", "category": "선물"},
    {"name": "달러 선물", "ticker": "DX=F", "source": "yahoo", "category": "선물"},
    {"name": "WTI 원유", "ticker": "CL=F", "source": "yahoo", "category": "선물"},
    {"name": "10년물 국채", "ticker": "ZN=F", "source": "yahoo", "category": "선물"}
]

INTERVALS = ["5분", "15분", "30분", "1시간", "4시간", "1일"]

# --- 데이터 수집 함수 ---
def get_data(ticker, source, interval_str):
    df = pd.DataFrame()
    try:
        # 매핑
        upbit_int_map = {"5분":"minute5", "15분":"minute15", "30분":"minute30", "1시간":"minute60", "4시간":"minute240", "1일":"day"}
        yahoo_int_map = {"5분":"5m", "15분":"15m", "30분":"30m", "1시간":"1h", "4시간":"1h", "1일":"1d"} # Yahoo 4시간 미지원 -> 1시간
        
        # 요청 개수 (EMA 200 계산을 위해 넉넉하게 늘림)
        req_count = 1000 
        
        if source == "upbit":
            target_interval = upbit_int_map.get(interval_str, "day")
            df = pyupbit.get_ohlcv(ticker, interval=target_interval, count=req_count)
        
        elif source == "yahoo":
            target_interval = yahoo_int_map.get(interval_str, "1d")
            # Yahoo Period 설정 (데이터 양 확보)
            target_period = "1mo" if target_interval in ["5m", "15m", "30m"] else "2y"
            
            df = yf.download(ticker, period=target_period, interval=target_interval, progress=False, auto_adjust=False)
            if not df.empty:
                # MultiIndex 컬럼 처리
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
                else:
                    df.columns = [c.lower() for c in df.columns]
                
                # 필요한 컬럼만 선택
                cols = ['open','high','low','close','volume']
                df = df[[c for c in cols if c in df.columns]]
                
    except Exception as e:
        print(f"Error fetching {ticker} ({interval_str}): {e}")
    
    return df

# --- 기존 전략 로직 (RSI v1, EMA Cross) ---
def run_strategy(df, strategy_type):
    if df is None or df.empty or len(df) < 200: # EMA 200 등을 위해 최소 데이터 확보
        return None

    df = df.copy()
    
    # 지표 계산
    if strategy_type == "RSI":
        df['RSI'] = ta.rsi(df['close'], length=14)
    elif strategy_type == "EMA":
        df['EMA_Fast'] = ta.ema(df['close'], length=25)
        df['EMA_Slow'] = ta.ema(df['close'], length=120)

    # 결과 저장용
    balance = 1000000
    initial_balance = 1000000
    position = None
    entry_price = 0
    trades = []
    
    # 백테스팅 루프
    for i in range(len(df)):
        if i < 120: continue # 지표 안정화 대기
        
        curr_close = df['close'].iloc[i]
        curr_time = str(df.index[i])
        
        # 1. 청산 (Exit)
        if position is not None:
            is_close = False
            pnl = 0
            
            if strategy_type == "RSI":
                # RSI v1: 반대 과매수/과매도 도달 시 청산 (단순화)
                curr_rsi = df['RSI'].iloc[i]
                if position == 'long' and curr_rsi > 70:
                    is_close = True
                    pnl = (curr_close - entry_price) / entry_price
                elif position == 'short' and curr_rsi < 30:
                    is_close = True
                    pnl = (entry_price - curr_close) / entry_price
                    
            elif strategy_type == "EMA":
                fast = df['EMA_Fast'].iloc[i]
                slow = df['EMA_Slow'].iloc[i]
                prev_fast = df['EMA_Fast'].iloc[i-1]
                prev_slow = df['EMA_Slow'].iloc[i-1]
                
                if position == 'long' and (prev_fast >= prev_slow and fast < slow):
                    is_close = True; pnl = (curr_close - entry_price) / entry_price
                elif position == 'short' and (prev_fast <= prev_slow and fast > slow):
                    is_close = True; pnl = (entry_price - curr_close) / entry_price

            if is_close:
                balance *= (1 + pnl)
                trades.append({'time': curr_time, 'type': 'Exit', 'pnl': pnl})
                position = None

        # 2. 진입 (Entry)
        if position is None:
            if strategy_type == "RSI":
                curr_rsi = df['RSI'].iloc[i]
                if not pd.isna(curr_rsi):
                    if curr_rsi < 30:
                        position = 'long'; entry_price = curr_close
                    elif curr_rsi > 70:
                        position = 'short'; entry_price = curr_close
                        
            elif strategy_type == "EMA":
                fast = df['EMA_Fast'].iloc[i]
                slow = df['EMA_Slow'].iloc[i]
                prev_fast = df['EMA_Fast'].iloc[i-1]
                prev_slow = df['EMA_Slow'].iloc[i-1]
                
                if prev_fast <= prev_slow and fast > slow:
                    position = 'long'; entry_price = curr_close
                elif prev_fast >= prev_slow and fast < slow:
                    position = 'short'; entry_price = curr_close

    return calculate_metrics(balance, initial_balance, trades, df, strategy_type)

# --- [NEW] RSI v2 전략 로직 ---
def run_strategy_rsi_v2(df):
    if df is None or df.empty or len(df) < 200:
        return None

    df = df.copy()
    
    # 1. 지표 계산
    df['RSI'] = ta.rsi(df['close'], length=14)
    df['EMA_200'] = ta.ema(df['close'], length=200) # 추세 필터용

    # 결과 변수
    balance = 1000000
    initial_balance = 1000000
    position = None
    entry_price = 0
    trades = []
    
    # 손절 설정 (2%)
    SL_PCT = 0.02

    # 백테스팅 루프
    for i in range(len(df)):
        if i < 200: continue # EMA 200 생성 대기
        
        curr_close = df['close'].iloc[i]
        curr_rsi = df['RSI'].iloc[i]
        prev_rsi = df['RSI'].iloc[i-1]
        curr_ema = df['EMA_200'].iloc[i]
        curr_time = str(df.index[i])
        
        # 지표 결측 체크
        if pd.isna(curr_rsi) or pd.isna(curr_ema): continue

        # ---------------------------
        # 1. 청산 (Exit) - 손절매 포함
        # ---------------------------
        if position is not None:
            is_close = False
            pnl = 0
            close_reason = ""

            if position == 'long':
                # A. 손절매 체크
                if curr_close <= entry_price * (1 - SL_PCT):
                    is_close = True
                    pnl = (curr_close - entry_price) / entry_price
                    close_reason = "Stop Loss"
                # B. 익절 (RSI 과매수 도달 시)
                elif curr_rsi > 70:
                    is_close = True
                    pnl = (curr_close - entry_price) / entry_price
                    close_reason = "Take Profit (RSI > 70)"
            
            elif position == 'short':
                # A. 손절매 체크
                if curr_close >= entry_price * (1 + SL_PCT):
                    is_close = True
                    pnl = (entry_price - curr_close) / entry_price
                    close_reason = "Stop Loss"
                # B. 익절 (RSI 과매도 도달 시)
                elif curr_rsi < 30:
                    is_close = True
                    pnl = (entry_price - curr_close) / entry_price
                    close_reason = "Take Profit (RSI < 30)"

            if is_close:
                balance *= (1 + pnl)
                trades.append({'time': curr_time, 'type': 'Exit', 'pnl': pnl, 'reason': close_reason})
                position = None

        # ---------------------------
        # 2. 진입 (Entry) - 추세 필터 & 확증 진입
        # ---------------------------
        if position is None:
            # A. 상승 추세 (가격 > EMA 200) -> Long만 진입
            if curr_close > curr_ema:
                # 눌림목 매수: 어제는 30 밑, 오늘은 30 위 (Cross Over)
                if prev_rsi < 30 and curr_rsi >= 30:
                    position = 'long'
                    entry_price = curr_close
            
            # B. 하락 추세 (가격 < EMA 200) -> Short만 진입
            elif curr_close < curr_ema:
                # 반등 매도: 어제는 70 위, 오늘은 70 아래 (Cross Under)
                if prev_rsi > 70 and curr_rsi <= 70:
                    position = 'short'
                    entry_price = curr_close

    return calculate_metrics(balance, initial_balance, trades, df, "RSI v2")

# --- 공통 결과 계산 함수 ---
def calculate_metrics(balance, initial_balance, trades, df, strategy_name):
    total_return = (balance - initial_balance) / initial_balance * 100
    win_trades = [t for t in trades if t['pnl'] > 0]
    win_rate = (len(win_trades) / len(trades) * 100) if trades else 0
    
    # 현재 상태 파악 (마지막 봉 기준)
    current_signal = "Hold"
    last_idx = -1
    
    if strategy_name == "RSI v2":
        # RSI v2 현재 신호 로직
        l_rsi = df['RSI'].iloc[last_idx]
        l_prev_rsi = df['RSI'].iloc[last_idx-1]
        l_close = df['close'].iloc[last_idx]
        l_ema = df['EMA_200'].iloc[last_idx] if 'EMA_200' in df.columns else 0
        
        if l_close > l_ema and l_prev_rsi < 30 and l_rsi >= 30:
            current_signal = "Buy (Trend Follow)"
        elif l_close < l_ema and l_prev_rsi > 70 and l_rsi <= 70:
            current_signal = "Sell (Trend Follow)"
            
    elif strategy_name == "RSI":
        l_rsi = df['RSI'].iloc[last_idx]
        if l_rsi < 30: current_signal = "Buy (OverSold)"
        elif l_rsi > 70: current_signal = "Sell (OverBought)"
        
    elif strategy_name == "EMA":
        fast = df['EMA_Fast'].iloc[last_idx]
        slow = df['EMA_Slow'].iloc[last_idx]
        if fast > slow: current_signal = "Hold (Bull)"
        else: current_signal = "Hold (Bear)"

    return {
        "return": total_return,
        "win_rate": win_rate,
        "trades": len(trades),
        "trade_history": trades,
        "current_signal": current_signal,
        "last_price": df['close'].iloc[-1]
    }

# --- 메인 실행 ---
def main():
    results = []
    print("Starting Batch Analysis...")
    
    # 현재 시간 저장 (모든 결과에 동일한 timestamp 적용)
    current_time = datetime.now().isoformat()
    
    # 총 작업 수: 자산 * 봉길이 * 전략수(3개)
    total_tasks = len(ASSET_LIST) * len(INTERVALS) * 3 
    completed = 0
    
    for asset in ASSET_LIST:
        ticker = asset['ticker']
        name = asset['name']
        source = asset['source']
        category = asset.get('category', '기타')
        
        for interval in INTERVALS:
            print(f"[{completed}/{total_tasks}] Processing {name} ({interval})...")
            
            # 데이터 가져오기
            df = get_data(ticker, source, interval)
            
            if df is not None and not df.empty:
                # 1. RSI v1
                res1 = run_strategy(df, "RSI")
                if res1:
                    results.append({"asset": name, "ticker": ticker, "category": category, "interval": interval, "strategy": "RSI v1", "timestamp": current_time, **res1})
                
                # 2. RSI v2 (NEW)
                res2 = run_strategy_rsi_v2(df)
                if res2:
                    results.append({"asset": name, "ticker": ticker, "category": category, "interval": interval, "strategy": "RSI v2 (Smart)", "timestamp": current_time, **res2})

                # 3. EMA Cross
                res3 = run_strategy(df, "EMA")
                if res3:
                    results.append({"asset": name, "ticker": ticker, "category": category, "interval": interval, "strategy": "EMA Cross", "timestamp": current_time, **res3})
            
            completed += 3

    # 결과 저장
    with open("analysis_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=4)
    
    print("Analysis Complete. Saved to analysis_results.json")

if __name__ == "__main__":
    main()