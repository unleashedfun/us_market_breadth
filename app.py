import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime
import requests
from io import StringIO

# --- 1. 頁面配置 (必須在最前面執行) ---
st.set_page_config(
    page_title="美股市場寬度 (Market Breadth) 監控儀表板",
    page_icon="📈",
    layout="wide"
)

# --- 2. 成分股抓取 (防 403 + 備援機制) ---
@st.cache_data(ttl=86400)
def get_constituents(index_name):
    """獲取指數成分股列表"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    try:
        if index_name == "S&P 500":
            benchmark = "^GSPC"
            try:
                url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
                resp = requests.get(url, headers=headers, timeout=10)
                resp.raise_for_status()
                table = pd.read_html(StringIO(resp.text))[0]
                tickers = table['Symbol'].str.replace('.', '-', regex=False).tolist()
            except Exception:
                fallback_url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
                df_fallback = pd.read_csv(fallback_url)
                tickers = df_fallback['Symbol'].str.replace('.', '-', regex=False).tolist()

        elif index_name == "Nasdaq 100":
            benchmark = "^NDX"
            url = "https://en.wikipedia.org/wiki/Nasdaq-100"
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            tables = pd.read_html(StringIO(resp.text))
            tickers = []
            for t in tables:
                col = next((c for c in t.columns if c in ['Ticker', 'Symbol']), None)
                if col and len(t) >= 90:
                    tickers = t[col].str.replace('.', '-', regex=False).tolist()
                    break
            if not tickers:
                raise ValueError("找不到 Nasdaq 100 成分股表格")

        elif index_name == "Dow Jones Industrial Average":
            benchmark = "^DJI"
            url = "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average"
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            tables = pd.read_html(StringIO(resp.text))
            tickers = []
            for t in tables:
                col = next((c for c in t.columns if c in ['Symbol', 'Ticker']), None)
                if col and len(t) == 30:
                    tickers = t[col].str.replace('.', '-', regex=False).tolist()
                    break
            if not tickers:
                raise ValueError("找不到道瓊成分股表格")

        return tickers, benchmark

    except Exception as e:
        st.warning(f"獲取完整成分股時出現問題 ({e})，使用前 10 大權重股作為替代範本。")
        return ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "UNH"], "^GSPC"

# --- 3. 歷史行情下載 ---
@st.cache_data(ttl=3600)
def download_data(tickers, benchmark_ticker, lookback_days=365):
    """批次下載收盤價數據"""
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=lookback_days + 250)

    all_tickers = list(set(tickers + [benchmark_ticker]))
    df = yf.download(all_tickers, start=start_date, end=end_date, interval="1d", progress=False)

    if 'Close' in df:
        close_df = df['Close'].copy()
    else:
        close_df = df.copy()

    benchmark_close = close_df[benchmark_ticker]
    stocks_close = close_df.drop(columns=[benchmark_ticker], errors='ignore').dropna(how='all', axis=1)

    return stocks_close, benchmark_close

# --- 4. 市場寬度計算 ---
def calculate_market_breadth(stocks_close):
    """計算高於均線比例與騰落指標"""
    sma_20 = stocks_close.rolling(window=20).mean()
    sma_50 = stocks_close.rolling(window=50).mean()
    sma_200 = stocks_close.rolling(window=200).mean()

    pct_above_20 = (stocks_close > sma_20).sum(axis=1) / stocks_close.notna().sum(axis=1) * 100
    pct_above_50 = (stocks_close > sma_50).sum(axis=1) / stocks_close.notna().sum(axis=1) * 100
    pct_above_200 = (stocks_close > sma_200).sum(axis=1) / stocks_close.notna().sum(axis=1) * 100

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

# --- 5. UI 介面佈局 ---
st.title("🏛️ 美股量化市場寬度 (Market Breadth) 儀表板")
st.markdown("衡量指數內部的**真實參與度**，避免因少數權重股拉抬而誤判整體盤勢。")

with st.sidebar:
    st.header("參數控制")
    selected_index = st.selectbox(
        "選擇基準指數",
        ["S&P 500", "Nasdaq 100", "Dow Jones Industrial Average"]
    )
    lookback = st.slider("回測區間 (天)", min_value=90, max_value=730, value=365, step=30)
    st.caption("註：每日初次載入需進行多股並行下載與快取，請稍候 10~20 秒。")

tickers, benchmark_sym = get_constituents(selected_index)
with st.spinner(f"正在加載 {selected_index} 成分股行情..."):
    stocks_close, benchmark_close = download_data(tickers, benchmark_sym, lookback_days=lookback)
    breadth_df = calculate_market_breadth(stocks_close)

display_df = breadth_df.iloc[-lookback:]
display_bench = benchmark_close.iloc[-lookback:]

latest = display_df.iloc[-1]
prev = display_df.iloc[-2]

# 關鍵數值看板
c1, c2, c3, c4 = st.columns(4)
c1.metric("> 200 SMA (長期趨勢)", f"{latest['Pct_Above_200SMA']:.1f}%", f"{latest['Pct_Above_200SMA'] - prev['Pct_Above_200SMA']:.1f}%")
c2.metric("> 50 SMA (中期動能)", f"{latest['Pct_Above_50SMA']:.1f}%", f"{latest['Pct_Above_50SMA'] - prev['Pct_Above_50SMA']:.1f}%")
c3.metric("> 20 SMA (短期情緒)", f"{latest['Pct_Above_20SMA']:.1f}%", f"{latest['Pct_Above_20SMA'] - prev['Pct_Above_20SMA']:.1f}%")
c4.metric("最新上漲 / 下跌", f"{int(latest['Advancers'])} / {int(latest['Decliners'])}", f"淨差額: {int(latest['Advancers'] - latest['Decliners'])}")

# 指數與均線穿透圖
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.08,
    row_heights=[0.55, 0.45],
    subplot_titles=(f"{selected_index} 指數走勢", "成分股高於移動平均線佔比 (%)")
)

fig.add_trace(
    go.Scatter(x=display_bench.index, y=display_bench.values, name=selected_index, line=dict(color="#1f77b4", width=2)),
    row=1, col=1
)

fig.add_trace(
    go.Scatter(x=display_df.index, y=display_df['Pct_Above_50SMA'], name="% > 50日線 (中期)", line=dict(color="#ff7f0e", width=1.5)),
    row=2, col=1
)
fig.add_trace(
    go.Scatter(x=display_df.index, y=display_df['Pct_Above_200SMA'], name="% > 200日線 (長期)", line=dict(color="#2ca02c", width=1.5)),
    row=2, col=1
)

fig.add_hline(y=80, line_dash="dash", line_color="red", opacity=0.6, annotation_text="超買 (80%)", row=2, col=1)
fig.add_hline(y=20, line_dash="dash", line_color="green", opacity=0.6, annotation_text="超賣 (20%)", row=2, col=1)
fig.add_hline(y=50, line_dash="dot", line_color="gray", opacity=0.4, row=2, col=1)

fig.update_layout(
    height=600,
    margin=dict(l=20, r=20, t=40, b=20),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    template="plotly_white"
)
fig.update_yaxes(title_text="指數點位", row=1, col=1)
fig.update_yaxes(title_text="佔比 (%)", range=[0, 100], row=2, col=1)
st.plotly_chart(fig, use_container_width=True)

# 騰落線圖
st.subheader("📊 累積騰落線 (Advance-Decline Line)")
fig_ad = go.Figure()
fig_ad.add_trace(go.Scatter(x=display_df.index, y=display_df['AD_Line'], name="AD Line", line=dict(color="#9467bd", width=2)))
fig_ad.update_layout(
    height=300,
    margin=dict(l=20, r=20, t=20, b=20),
    xaxis_title="日期",
    yaxis_title="累計淨值",
    template="plotly_white"
)
st.plotly_chart(fig_ad, use_container_width=True)
