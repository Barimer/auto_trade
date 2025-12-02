import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime, timedelta
import batch_analyzer

# --- 페이지 설정 ---
st.set_page_config(layout="wide", page_title="Trading Dashboard", page_icon="📊")

# --- CSS 스타일링 ---
st.markdown("""
<style>
    .stDataFrame {
        font-size: 14px;
    }
</style>
""", unsafe_allow_html=True)

# --- 데이터 로드 ---

# [새로 넣을 부분]
# ttl=600은 10분 동안 분석 결과를 저장(캐시)한다는 뜻입니다.
@st.cache_data(ttl=600, show_spinner="실시간 데이터 분석 중입니다... 잠시만 기다려주세요.")
def load_data():
    # 파일 읽기 대신, batch_analyzer의 분석 함수를 직접 실행합니다.
    raw_data = batch_analyzer.get_analysis_results()
    return pd.DataFrame(raw_data)

def main():
    st.caption(f"마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if st.button("🔄 데이터 새로고침"):
        st.cache_data.clear()
        st.rerun()

    df = load_data()

    if df.empty:
        st.warning("데이터가 없습니다. `batch_analyzer.py`를 먼저 실행해주세요.")
        st.stop()

    # --- 사이드바 필터 ---
    st.sidebar.header("🔍 필터")
    
    # 기간 선택 필터 (새로 추가)
    period_filter = st.sidebar.radio(
        "📅 조회 기간 단위",
        ["전체", "1일", "1달", "6달", "1년"],
        index=0
    )
    
    # 특정 기간 선택 로직
    use_specific_period = False
    specific_start_date = None
    specific_end_date = None
    
    if period_filter != "전체":
        use_specific_period = st.sidebar.checkbox("특정 기간 선택")
        
        if use_specific_period:
            # 전체 데이터에서 날짜 범위 추출
            all_dates = []
            for _, row in df.iterrows():
                if isinstance(row.get('trade_history'), list):
                    for t in row['trade_history']:
                        try:
                            dt = pd.to_datetime(t['time'])
                            if dt.tzinfo is not None:
                                dt = dt.tz_localize(None)
                            all_dates.append(dt)
                        except:
                            pass
            
            if not all_dates:
                st.sidebar.warning("날짜 데이터가 없습니다.")
                min_date = datetime.now()
                max_date = datetime.now()
            else:
                min_date = min(all_dates)
                max_date = max(all_dates)
            
            # 위젯 표시
            if period_filter == "1일":
                target_date = st.sidebar.date_input("날짜 선택", max_date)
                specific_start_date = datetime.combine(target_date, datetime.min.time())
                specific_end_date = datetime.combine(target_date, datetime.max.time())
                
            elif period_filter == "1달":
                # 월 리스트 생성
                months = []
                cur = min_date.replace(day=1)
                while cur <= max_date:
                    months.append(cur.strftime("%Y-%m"))
                    # 다음 달로 이동
                    if cur.month == 12:
                        cur = cur.replace(year=cur.year+1, month=1)
                    else:
                        cur = cur.replace(month=cur.month+1)
                
                months = sorted(list(set(months)), reverse=True) # 최신순
                if not months: months = [datetime.now().strftime("%Y-%m")]
                
                selected_month = st.sidebar.selectbox("월 선택", months)
                y, m = map(int, selected_month.split('-'))
                specific_start_date = datetime(y, m, 1)
                # 월의 마지막 날 계산
                if m == 12:
                    specific_end_date = datetime(y+1, 1, 1) - timedelta(seconds=1)
                else:
                    specific_end_date = datetime(y, m+1, 1) - timedelta(seconds=1)
                    
            elif period_filter == "6달":
                # 반기 리스트 생성
                halves = []
                cur_y = min_date.year
                end_y = max_date.year
                for y in range(cur_y, end_y + 1):
                    halves.append(f"{y} 상반기")
                    halves.append(f"{y} 하반기")
                
                halves = sorted(halves, reverse=True)
                selected_half = st.sidebar.selectbox("반기 선택", halves)
                
                y = int(selected_half.split()[0])
                if "상반기" in selected_half:
                    specific_start_date = datetime(y, 1, 1)
                    specific_end_date = datetime(y, 6, 30, 23, 59, 59)
                else:
                    specific_start_date = datetime(y, 7, 1)
                    specific_end_date = datetime(y, 12, 31, 23, 59, 59)
                    
            elif period_filter == "1년":
                # 연도 리스트 생성
                years = range(min_date.year, max_date.year + 1)
                years = sorted(list(years), reverse=True)
                selected_year = st.sidebar.selectbox("연도 선택", years)
                
                specific_start_date = datetime(selected_year, 1, 1)
                specific_end_date = datetime(selected_year, 12, 31, 23, 59, 59)
    
    # 전략 필터
    strategies = ["All"] + list(df['strategy'].unique())
    selected_strategy = st.sidebar.selectbox("전략 선택", strategies)
    
    # 카테고리 필터
    if 'category' in df.columns:
        categories = ["All"] + list(df['category'].unique())
        selected_category = st.sidebar.selectbox("자산 그룹 선택", categories)
    else:
        selected_category = "All"

    # 자산 필터
    if selected_category != "All":
        filtered_assets_list = df[df['category'] == selected_category]['asset'].unique()
        assets = ["All"] + list(filtered_assets_list)
    else:
        assets = ["All"] + list(df['asset'].unique())
        
    selected_asset = st.sidebar.selectbox("자산 선택", assets)
    
    # 봉 길이 필터
    intervals = ["All"] + list(df['interval'].unique())
    selected_interval = st.sidebar.selectbox("봉 길이 선택", intervals)

    # 기간 필터링 적용
    with st.spinner('데이터 분석 중...'):
        filtered_df = df.copy()
        
        # 기간 필터 적용 (trade_history 기반 재계산)
        if period_filter != "전체":
            # 기간별로 데이터 범위 지정
            now = datetime.now()
            cutoff_date = None # 기존 로직용 (최근 N일)
            
            if not use_specific_period:
                # 기존 로직: 최근 N일
                if period_filter == "1일":
                    cutoff_date = now - timedelta(days=1)
                elif period_filter == "1달":
                    cutoff_date = now - timedelta(days=30)
                elif period_filter == "6달":
                    cutoff_date = now - timedelta(days=180)
                elif period_filter == "1년":
                    cutoff_date = now - timedelta(days=365)
            
            # 재계산 함수
            def recalculate(row):
                if 'trade_history' not in row or not isinstance(row['trade_history'], list):
                    return row
                
                trades = row['trade_history']
                filtered_trades = []
                
                for t in trades:
                    try:
                        trade_time = pd.to_datetime(t['time'])
                        if trade_time.tzinfo is not None:
                            trade_time = trade_time.tz_localize(None)
                        
                        # 필터링 조건 확인
                        include = False
                        if use_specific_period and specific_start_date and specific_end_date:
                            # 특정 기간 범위
                            if specific_start_date <= trade_time <= specific_end_date:
                                include = True
                        elif cutoff_date:
                            # 최근 N일
                            if cutoff_date.tzinfo is None and trade_time.tzinfo is not None:
                                # trade_time은 위에서 이미 tz_localize(None) 처리됨
                                pass 
                            if trade_time >= cutoff_date:
                                include = True
                                
                        if include:
                            filtered_trades.append(t)
                    except:
                        continue
                
                # 메트릭 재계산
                initial_balance = 1000000
                balance = initial_balance
                
                for t in filtered_trades:
                    balance *= (1 + t['pnl'])
                    
                total_return = (balance - initial_balance) / initial_balance * 100
                win_trades = [t for t in filtered_trades if t['pnl'] > 0]
                win_rate = (len(win_trades) / len(filtered_trades) * 100) if filtered_trades else 0
                
                row['return'] = total_return
                row['win_rate'] = win_rate
                row['trades'] = len(filtered_trades)
                return row

            # Apply recalculation
            if 'trade_history' in filtered_df.columns:
                filtered_df = filtered_df.apply(recalculate, axis=1)

        
        # 나머지 필터 적용
        if selected_category != "All" and 'category' in filtered_df.columns:
            filtered_df = filtered_df[filtered_df['category'] == selected_category]
            
        if selected_strategy != "All":
            filtered_df = filtered_df[filtered_df['strategy'] == selected_strategy]
        if selected_asset != "All":
            filtered_df = filtered_df[filtered_df['asset'] == selected_asset]
        if selected_interval != "All":
            filtered_df = filtered_df[filtered_df['interval'] == selected_interval]

        # --- 필터링 결과 요약 통계 ---
        st.subheader("📊 선택한 조건의 백테스팅 결과")
        
        if filtered_df.empty:
            st.warning("선택한 조건에 맞는 데이터가 없습니다.")
        else:
            # 집계 통계 계산
            total_trades = filtered_df['trades'].sum()
            
            # 승률 계산 (가중 평균)
            if total_trades > 0:
                weighted_win_rate = (filtered_df['win_rate'] * filtered_df['trades']).sum() / total_trades
            else:
                weighted_win_rate = 0
            
            # 평균 수익률 계산
            avg_return = filtered_df['return'].mean()
            
            # 거래 수수료 설정 (매수 0.05% + 매도 0.05% = 왕복 0.1%)
            fee_per_trade_pct = 0.001  # 0.1% = 0.001
            
            # 초기 금액
            initial_amount = 1000000
            
            # 수수료를 고려한 복리 계산
            # 각 거래마다: 수익 = (1 + return_rate) * (1 - fee_rate) - 1
            # 전체 거래 후 최종 금액 = initial * Π[(1 + return_i) * (1 - fee)]
            balance_no_fee = initial_amount
            balance_with_fee = initial_amount
            
            for _, row in filtered_df.iterrows():
                return_rate = row['return'] / 100  # % to decimal
                trades_count = row['trades']
                
                # 해당 전략의 각 거래별 평균 수익률 적용
                avg_return_per_trade = return_rate / trades_count if trades_count > 0 else 0
                
                for _ in range(int(trades_count)):
                    # 수수료 없이
                    balance_no_fee *= (1 + avg_return_per_trade)
                    
                    # 수수료 포함 (매수 시 0.05%, 매도 시 0.05% = 총 0.1%)
                    # 거래 후 실제 수익 = (1 + return) * (1 - 0.001) - 1
                    balance_with_fee *= (1 + avg_return_per_trade) * (1 - fee_per_trade_pct)
            
            # 최종 금액
            final_amount_before_fee = balance_no_fee
            final_amount_after_fee = balance_with_fee
            
            # 총 수수료 금액 = 수수료 전 금액 - 수수료 후 금액
            total_fee_amount = final_amount_before_fee - final_amount_after_fee
            
            # 수익률 계산
            return_before_fee = ((final_amount_before_fee - initial_amount) / initial_amount) * 100
            return_after_fee = ((final_amount_after_fee - initial_amount) / initial_amount) * 100
            
            # 메트릭 카드로 표시 (2줄로 배치)
            # 첫 번째 줄: 기본 통계
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric(
                    label="총 거래 횟수",
                    value=f"{int(total_trades)} 회"
                )
            
            with col2:
                st.metric(
                    label="평균 승률",
                    value=f"{weighted_win_rate:.1f}%"
                )
            
            with col3:
                st.metric(
                    label="수익률 (수수료 전)",
                    value=f"{return_before_fee:.2f}%",
                    delta=f"{return_before_fee:.2f}%"
                )
            
            with col4:
                st.metric(
                    label="최종 금액 (수수료 전)",
                    value=f"{int(final_amount_before_fee):,} 원",
                    delta=f"{int(final_amount_before_fee - initial_amount):,} 원"
                )
            
            # 두 번째 줄: 수수료 적용 결과
            st.markdown("#### 💰 수수료 적용 후 실제 수익")
            col5, col6, col7, col8 = st.columns(4)
            
            with col5:
                st.metric(
                    label="총 수수료 비용",
                    value=f"{int(total_fee_amount):,} 원",
                    delta=f"-{(total_fee_amount/initial_amount*100):.2f}%",
                    delta_color="inverse"
                )
            
            with col6:
                st.metric(
                    label="수수료율 (왕복)",
                    value="0.1%",
                    help="매수 0.05% + 매도 0.05%"
                )
            
            with col7:
                st.metric(
                    label="실제 수익률 (수수료 후)",
                    value=f"{return_after_fee:.2f}%",
                    delta=f"{return_after_fee:.2f}%"
                )
            
            with col8:
                st.metric(
                    label="실제 최종 금액 (수수료 후)",
                    value=f"{int(final_amount_after_fee):,} 원",
                    delta=f"{int(final_amount_after_fee - initial_amount):,} 원"
                )
            
            st.markdown("---")
            
            # 선택 조건 표시
            st.markdown("---")
        
        # 선택 조건 표시
        period_str = period_filter
        if use_specific_period:
            if period_filter == "1일": period_str = f"{specific_start_date.strftime('%Y-%m-%d')}"
            elif period_filter == "1달": period_str = f"{specific_start_date.strftime('%Y-%m')}"
            elif period_filter == "6달": period_str = f"{specific_start_date.strftime('%Y-%m')} ~ {specific_end_date.strftime('%Y-%m')}"
            elif period_filter == "1년": period_str = f"{specific_start_date.year}"
            
        st.caption(f"📌 **필터 조건**: 기간={period_str}, 전략={selected_strategy}, 자산={selected_asset}, 봉길이={selected_interval}")
        st.caption(f"📈 **데이터 수**: {len(filtered_df)}개 결과 기반")
            
        # --- 거래 목록 테이블 ---
        st.subheader("📋 거래 목록")
        
        # 표시할 컬럼 선택
        cols_to_show = ['asset', 'category', 'strategy', 'interval', 'return', 'win_rate', 'trades', 'current_signal', 'last_price']
        # category 컬럼이 없으면 제외
        display_cols = [c for c in cols_to_show if c in filtered_df.columns]
        
        display_df = filtered_df[display_cols].sort_values(by='return', ascending=False).reset_index(drop=True)
        
        # 스타일링 함수
        def color_return(val):
            if val >= 0:
                return 'color: #4CAF50; font-weight: bold;'  # Green for profit
            else:
                return 'color: #FF5252; font-weight: bold;'  # Red for loss
        
        def color_signal(val):
            if 'Buy' in str(val):
                return 'color: #4CAF50; font-weight: bold;'  # Green
            elif 'Sell' in str(val):
                return 'color: #FF5252; font-weight: bold;'  # Red
            else:
                return 'color: white;'
        
        # 테이블 표시
        st.dataframe(
            display_df.style
            .applymap(color_return, subset=['return'])
            .applymap(color_signal, subset=['current_signal'])
            .format({
                'return': "{:.2f}%",
                'win_rate': "{:.1f}%",
                'last_price': "{:,.2f}"
            }),
            use_container_width=True,
            height=400
        )

if __name__ == "__main__":
    main()

