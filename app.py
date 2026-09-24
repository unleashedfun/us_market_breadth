import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime

# --- 頁面配置 ---
st.set_page_config(
    page_title="美股市場寬度 (Market Breadth) 監控儀表板",
    page_icon="📈",
    layout="wide"
)

# --- 成分股抓取 (含快取機制避免頻繁請求被封鎖) ---
@st.cache_data(ttl=86400)
def get_constituents(index_name):
    """獲取主要指數的成分股列表"""
    try:
        if index_name == "S&P 500":
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            table = pd.read_html(url)[0]
            tickers = table['Symbol'].str.replace('.', '-', regex=False).tolist()
            benchmark = "^GSPC"
        elif index_name == "Nasdaq 100":
            url = "https://en.wikipedia.org/wiki/Nasdaq-100"
            table = pd.read_html(url)[4]  # Wikipedia 結構可能隨時間微調
            if 'Ticker' in table.columns:
                tickers = table['Ticker'].str.replace('.', '-', regex=False).tolist()
            else:
                tickers = table['Symbol'].str.replace('.', '-', regex=False).tolist()
            benchmark = "^NDX"
        elif index_name == "Dow Jones Industrial Average":
            url = "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average"
            table = pd.read_html(url)[1]
            tickers = table['Symbol'].str.replace('.', '-', regex=False).tolist()
            benchmark = "^DJI"
        return tickers, benchmark
    except Exception as e:
        st.error(f"成分股抓取失敗: {e}")
        # 降級備用名單
        return ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"], "^GSPC"

# --- 下載歷史行情 ---
@st.cache_data(ttl=3600)
def download_data(tickers, benchmark_ticker, lookback_days=365):
    """批次下載個股及基準指數的收盤價數據"""
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=lookback_days + 250) # 額外預留 250 天以計算 200 SMA

    # 批次下載成分股收盤價
    all_tickers = list(set(tickers + [benchmark_ticker]))
    df = yf.download(all_tickers, start=start_date, end=end_date, interval="1d", progress=False)
    
    # 提取收盤價
    if 'Close' in df:
        close_df = df['Close'].copy()
    else:
        close_df = df.copy()

    benchmark_close = close_df[benchmark_ticker]
    stocks_close = close_df.drop(columns=[benchmark_ticker], errors='ignore').dropna(how='all', axis=1)
    
    return stocks_close, benchmark_close

# --- 量化計算：市場寬度指標 ---
def calculate_market_breadth(stocks_close):
    """計算均線穿透率與騰落指標"""
    # 移動平均線
    sma_20 = stocks_close.rolling(window=20).mean()
    sma_50 = stocks_close.rolling(window=50).mean()
    sma_200 = stocks_close.rolling(window=200).mean()

    # 高於各均線的個股比例 (%)
    pct_above_20 = (stocks_close > sma_20).sum(axis=1) / stocks_close.notna().sum(axis=1) * 100
    pct_above_50 = (stocks_close > sma_50).sum(axis=1) / stocks_close.notna().sum(axis=1) * 100
    pct_above_200 = (stocks_close > sma_200).sum(axis=1) / stocks_close.notna().sum(axis=1) * 100

    # 騰落 (Advance-Decline)
    daily_returns = stocks_close.pct_change()
    advancers = (daily_returns > 0).sum(axis=1)
    decliners = (daily_returns < 0).sum(axis=1)
    net_advances = advancers - decliners
    ad_line = net_advances.cumsum()

    breadth_df = pd.DataFrame({
        'Pct_Above_20SMA': pct_above_20,
        'Pct_Above_50SMA': pct_above_50,
        'Pct_Above_200SMA': pct_above_200,
        'Advancers': advancers,
        'Decliners': decliners,
        'AD_Line': ad_line
    })
    
    return breadth_df

# --- UI 介面與控制台 ---
st.title("🏛️ 美股量化市場寬度 (Market Breadth) 儀表板")
st.markdown("市場寬度用於衡量指數背後的**真實參與廣度**，能有效識別權重股掩蓋的市場衰竭與牛熊背離。")

with st.sidebar:
    st.header("參數設定")
    selected_index = st.selectbox(
        "選擇基準指數",
        ["S&P 500", "Nasdaq 100", "Dow Jones Industrial Average"]
    )
    lookback = st.slider("回測區間 (天)", min_value=90, max_value=730, value=365, step=30)
    st.info("註：數據由 Yahoo Finance 延遲提供。首次載入或切換指數可能需 10-20 秒。")

# 獲取成分股與計算
tickers, benchmark_sym = get_constituents(selected_index)
with st.spinner(f"正在下載 {selected_index} 旗下 {len(tickers)} 檔成分股數據..."):
    stocks_close, benchmark_close = download_data(tickers, benchmark_sym, lookback_days=lookback)
    breadth_df = calculate_market_breadth(stocks_close)

# 切割顯示時間區間
display_df = breadth_df.iloc[-lookback:]
display_bench = benchmark_close.iloc[-lookback:]

# --- 頂部儀表盤指標 (KPIs) ---
latest = display_df.iloc[-1]
prev = display_df.iloc[-2]

col1, col2, col3, col4 = st.columns(4)
col1.metric("> 200 SMA (長期強弱)", f"{latest['Pct_Above_200SMA']:.1f}%", f"{latest['Pct_Above_200SMA'] - prev['Pct_Above_200SMA']:.1f}%")
col2.metric("> 50 SMA (中期動能)", f"{latest['Pct_Above_50SMA']:.1f}%", f"{latest['Pct_Above_50SMA'] - prev['Pct_Above_50SMA']:.1f}%")
col3.metric("> 20 SMA (短期情緒)", f"{latest['Pct_Above_20SMA']:.1f}%", f"{latest['Pct_Above_20SMA'] - prev['Pct_Above_20SMA']:.1f}%")
col4.metric("最新上漲 / 下跌家數", f"{int(latest['Advancers'])} / {int(latest['Decliners'])}", f"淨額: {int(latest['Advancers'] - latest['Decliners'])}")

# --- 主圖表：指數收盤價 vs 市場寬度 ---
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.08,
    row_heights=[0.55, 0.45],
    subplot_titles=(f"{selected_index} 指數走勢", "成分股高於移動平均線佔比 (%)")
)

# 指數走勢
fig.add_trace(
    go.Scatter(x=display_bench.index, y=display_bench.values, name=selected_index, line=dict(color="#1f77b4", width=2)),
    row=1, col=1
)

# 寬度指標 (50 SMA & 200 SMA)
fig.add_trace(
    go.Scatter(x=display_df.index, y=display_df['Pct_Above_50SMA'], name="% > 50日線 (中期)", line=dict(color="#ff7f0e", width=1.5)),
    row=2, col=1
)
fig.add_trace(
    go.Scatter(x=display_df.index, y=display_df['Pct_Above_200SMA'], name="% > 200日線 (長期)", line=dict(color="#2ca02c", width=1.5)),
    row=2, col=1
)

# 加入超買/超賣警戒線
fig.add_hline(y=80, line_dash="dash", line_color="red", opacity=0.6, annotation_text="超買區間 (80%)", row=2, col=1)
fig.add_hline(y=20, line_dash="dash", line_color="green", opacity=0.6, annotation_text="超賣區間 (20%)", row=2, col=1)
fig.add_hline(y=50, line_dash="dot", line_color="gray", opacity=0.4, row=2, col=1)

fig.update_layout(
    height=650,
    margin=dict(l=20, r=20, t=40, b=20),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    template="plotly_white"
)
fig.update_yaxes(title_text="指數點位", row=1, col=1)
fig.update_yaxes(title_text="佔比 (%)", range=[0, 100], row=2, col=1)

st.plotly_chart(fig, use_container_width=True)

# --- 次圖表：騰落線 (Advance-Decline Line) ---
st.subheader("📊 累積騰落線 (Advance-Decline Line)")
fig_ad = go.Figure()
fig_ad.add_trace(go.Scatter(x=display_df.index, y=display_df['AD_Line'], name="AD Line", line=dict(color="#9467bd", width=2)))
fig_ad.update_layout(
    height=300,
    margin=dict(l=20, r=20, t=20, b=20),
    xaxis_title="日期",
    yaxis_title="累計淨上漲家數",
    template="plotly_white"
)
st.plotly_chart(fig_ad, use_container_width=True)
