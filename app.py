import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime
import requests
from io import StringIO
import re

# --- 1. 頁面配置 (首項執行) ---
st.set_page_config(
    page_title="美股市場寬度與恐懼貪婪指數監控儀表板",
    page_icon="📈",
    layout="wide"
)

# --- 2. 完備備援清單 (保證成分股樣本齊全) ---
DOW30_FALLBACK = [
    "AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS",
    "GS", "HD", "HON", "IBM", "JNJ", "JPM", "KO", "MCD", "MMM", "MRK",
    "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "VZ", "WMT"
]

NASDAQ100_FALLBACK = [
    "AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "ALGN", "AMAT", "AMD",
    "AMGN", "AMZN", "ANSS", "APP", "ARM", "ASML", "AVGO", "AZN", "BIIB", "BKNG",
    "BKR", "CDNS", "CEG", "CHTR", "CMCSA", "COST", "CPRT", "CRWD", "CSCO", "CSGP",
    "CSX", "CTAS", "CTSH", "DASH", "DDOG", "DLTR", "DXCM", "EA", "EXC", "FANG",
    "FAST", "FTNT", "GEHC", "GFS", "GILD", "GOOG", "GOOGL", "HON", "IDXX", "ILMN",
    "INTC", "INTU", "ISRG", "KDP", "KHC", "KLAC", "LIN", "LRCX", "LULU", "MAR",
    "MCHP", "MDLZ", "MELI", "META", "MNST", "MRNA", "MRVL", "MSFT", "MU", "NFLX",
    "NVDA", "NXPI", "ODFL", "ON", "ORLY", "PANW", "PAYX", "PCAR", "PDD", "PEP",
    "PLTR", "PYPL", "QCOM", "REGN", "ROP", "ROST", "SBUX", "SNPS", "STX", "TEAM",
    "TMUS", "TSLA", "TTWO", "TXN", "VRSK", "VRTX", "WBD", "WDC", "WDAY", "XEL", "ZS"
]

# --- 3. 表格解析引擎 ---
def extract_tickers_from_tables(tables, min_count=25, max_count=600):
    for df in tables:
        if len(df) < min_count or len(df) > max_count:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            flat_cols = [' '.join(str(lvl) for lvl in col).strip() for col in df.columns]
        else:
            flat_cols = [str(c).strip() for c in df.columns]

        target_idx = None
        for idx, col_name in enumerate(flat_cols):
            c_clean = col_name.lower().replace(" ", "").replace("_", "")
            if "ticker" in c_clean or "symbol" in c_clean:
                target_idx = idx
                break

        if target_idx is not None:
            raw_series = df.iloc[:, target_idx].dropna().astype(str).str.strip()
            valid_tickers = [
                sym.replace('.', '-') for sym in raw_series
                if re.match(r'^[A-Za-z\.\-]{1,6}$', sym)
            ]
            valid_tickers = list(dict.fromkeys(valid_tickers))
            if len(valid_tickers) >= min_count:
                return valid_tickers
    return []

# --- 4. 抓取成分股名單 ---
@st.cache_data(ttl=86400)
def get_constituents(index_name):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    if index_name == "Nasdaq 100":
        benchmark = "^NDX"
        try:
            resp = requests.get("https://en.wikipedia.org/wiki/Nasdaq-100", headers=headers, timeout=10)
            if resp.status_code == 200:
                tickers = extract_tickers_from_tables(pd.read_html(StringIO(resp.text)), min_count=80, max_count=120)
                if tickers: return tickers, benchmark
        except Exception: pass
        return NASDAQ100_FALLBACK, benchmark

    elif index_name == "Dow Jones Industrial Average":
        benchmark = "^DJI"
        try:
            resp = requests.get("https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average", headers=headers, timeout=10)
            if resp.status_code == 200:
                tickers = extract_tickers_from_tables(pd.read_html(StringIO(resp.text)), min_count=28, max_count=35)
                if tickers: return tickers, benchmark
        except Exception: pass
        return DOW30_FALLBACK, benchmark

    elif index_name == "S&P 500":
        benchmark = "^GSPC"
        try:
            resp = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers=headers, timeout=10)
            if resp.status_code == 200:
                tickers = extract_tickers_from_tables(pd.read_html(StringIO(resp.text)), min_count=450, max_count=550)
                if tickers: return tickers, benchmark
        except Exception: pass
        try:
            df_m = pd.read_csv("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv")
            return df_m['Symbol'].str.replace('.', '-', regex=False).tolist(), benchmark
        except Exception: pass
        return NASDAQ100_FALLBACK[:50], benchmark

    return NASDAQ100_FALLBACK, "^NDX"

# --- 5. 抓取 CNN Fear & Greed Index ---
@st.cache_data(ttl=1800)
def get_fear_and_greed():
    """調用 CNN 官方數據接口獲取恐懼與貪婪指數及歷史數據"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://www.cnn.com/markets/fear-and-greed",
        "Origin": "https://www.cnn.com",
        "Accept": "application/json, text/plain, */*"
    }
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            fg_main = data.get("fear_and_greed", {})
            hist_raw = data.get("fear_and_greed_historical", {}).get("data", [])
            
            hist_df = pd.DataFrame()
            if hist_raw:
                hist_df = pd.DataFrame(hist_raw)
                hist_df['date'] = pd.to_datetime(hist_df['x'], unit='ms')
                hist_df = hist_df.rename(columns={'y': 'score'}).set_index('date').sort_index()

            return {
                "score": round(float(fg_main.get("score", 50)), 1),
                "rating": str(fg_main.get("rating", "neutral")).lower(),
                "prev_close": round(float(fg_main.get("previous_close", 50)), 1),
                "prev_1w": round(float(fg_main.get("previous_1_week", 50)), 1),
                "prev_1m": round(float(fg_main.get("previous_1_month", 50)), 1),
                "prev_1y": round(float(fg_main.get("previous_1_year", 50)), 1),
                "historical": hist_df
            }
    except Exception:
        pass
    return None

# --- 6. 繪製 Fear & Greed 儀表盤 ---
def plot_fear_greed_gauge(score, rating_text, prev_close):
    rating_trans = {
        "extreme fear": ("極度恐慌", "#d73027"),
        "fear": ("恐慌", "#fc8d59"),
        "neutral": ("中性", "#e0af1f"),
        "greed": ("貪婪", "#91cf60"),
        "extreme greed": ("極度貪婪", "#1a9850")
    }
    zh_text, color = rating_trans.get(rating_text, ("中性", "#e0af1f"))

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=score,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': f"當前情緒：<b>{zh_text}</b>", 'font': {'size': 19, 'color': color}},
        delta={'reference': prev_close, 'increasing': {'color': "#1a9850"}, 'decreasing': {'color': "#d73027"}},
        number={'font': {'size': 44, 'family': 'Arial, sans-serif'}},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "gray", 'tickvals': [0, 25, 45, 55, 75, 100]},
            'bar': {'color': "#2c3e50", 'thickness': 0.26},
            'bgcolor': "white",
            'borderwidth': 1,
            'bordercolor': "#e2e8f0",
            'steps': [
                {'range': [0, 25], 'color': '#ff4d4f'},    # 極度恐懼
                {'range': [25, 45], 'color': '#ffa940'},   # 恐懼
                {'range': [45, 55], 'color': '#fadb14'},   # 中性
                {'range': [55, 75], 'color': '#95de64'},   # 貪婪
                {'range': [75, 100], 'color': '#52c41a'}   # 極度貪婪
            ],
            'threshold': {
                'line': {'color': "#111111", 'width': 4},
                'thickness': 0.75,
                'value': score
            }
        }
    ))
    fig.update_layout(
        height=270,
        margin=dict(l=25, r=25, t=35, b=10),
        template="plotly_white"
    )
    return fig

# --- 7. 下載行情數據 ---
@st.cache_data(ttl=3600)
def download_data(tickers, benchmark_ticker, lookback_days=365):
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=lookback_days + 250)
    all_tickers = list(set(tickers + [benchmark_ticker]))
    
    df = yf.download(all_tickers, start=start_date, end=end_date, interval="1d", progress=False)
    close_df = df['Close'].copy() if 'Close' in df else df.copy()

    if benchmark_ticker in close_df.columns:
        benchmark_close = close_df[benchmark_ticker]
        stocks_close = close_df.drop(columns=[benchmark_ticker], errors='ignore').dropna(how='all', axis=1)
    else:
        benchmark_close = close_df.iloc[:, 0]
        stocks_close = close_df.iloc[:, 1:].dropna(how='all', axis=1)

    return stocks_close, benchmark_close

# --- 8. 計算市場寬度指標 ---
def calculate_market_breadth(stocks_close):
    sma_20 = stocks_close.rolling(window=20).mean()
    sma_50 = stocks_close.rolling(window=50).mean()
    sma_200 = stocks_close.rolling(window=200).mean()

    valid_counts = stocks_close.notna().sum(axis=1).replace(0, np.nan)
    pct_above_20 = (stocks_close > sma_20).sum(axis=1) / valid_counts * 100
    pct_above_50 = (stocks_close > sma_50).sum(axis=1) / valid_counts * 100
    pct_above_200 = (stocks_close > sma_200).sum(axis=1) / valid_counts * 100

    daily_returns = stocks_close.pct_change()
    advancers = (daily_returns > 0).sum(axis=1)
    decliners = (daily_returns < 0).sum(axis=1)
    ad_line = (advancers - decliners).cumsum()

    return pd.DataFrame({
        'Pct_Above_20SMA': pct_above_20,
        'Pct_Above_50SMA': pct_above_50,
        'Pct_Above_200SMA': pct_above_200,
        'Advancers': advancers,
        'Decliners': decliners,
        'AD_Line': ad_line
    })

# --- 9. 智能量化診斷 ---
def diagnose_market(p20, p50, p200):
    if p200 >= 70:
        macro = ("🟢 長期牛市架構穩固", "逾 70% 個股位於年線上方，大週期多頭趨勢鮮明。")
    elif p200 <= 35:
        macro = ("🔴 長期系統性偏弱", "僅不到 35% 個股站上年線，宏觀熊市或下行壓力沉重。")
    else:
        macro = ("🟡 長期處於分水嶺拉鋸", "年線佔比位於中性平衡區，市場多空未分勝負。")
    
    if p50 >= 80:
        sentiment = ("⚠️ 中期動能極度過熱 (超買)", "站上季線個股超過 80%，易受獲利回吐打壓，防範短線震盪。")
    elif p50 <= 20:
        sentiment = ("💎 中期極度恐慌 (超賣黃金區)", "站上季線個股不足 20%，市場殺跌接近極值，多孕育高勝率反彈買點。")
    elif p50 >= 55:
        sentiment = ("📈 中期健康多頭推進", "季線佔比穩居 55-80% 健康區，成分股輪動良好。")
    else:
        sentiment = ("📉 中期空頭震盪整理", "季線佔比落於 50% 榮枯線下方，個股多數受壓。")

    return macro, sentiment

# --- 10. UI 控制台與資料運算 ---
st.title("🏛️ 美股市場寬度與恐懼貪婪指數監控儀表板")
st.caption("結合微觀內部結構（Market Breadth）與全市場宏觀情緒（Fear & Greed），全方位穿透市場本質。")

with st.sidebar:
    st.header("⚙️ 參數設定")
    selected_index = st.selectbox(
        "基準指數 (預設為納指)",
        ["Nasdaq 100", "S&P 500", "Dow Jones Industrial Average"],
        index=0
    )
    lookback = st.slider("回測與圖表顯示天數", min_value=90, max_value=730, value=365, step=30)
    st.markdown("---")
    st.markdown("### 💡 核心量化法則")
    st.markdown("- **指數創高 + 寬度下滑** ➔ 頂背離 (出貨警戒)")
    st.markdown("- **指數破底 + 寬度抬升** ➔ 底背離 (築底轉強)")
    st.markdown("- **極度恐懼 (<25) + 寬度超賣 (<20%)** ➔ 雙重共振黃金底")

# 同步讀取市場數據與情緒數據
fg_data = get_fear_and_greed()
tickers, benchmark_sym = get_constituents(selected_index)

with st.spinner(f"正在更新 {selected_index} ({len(tickers)} 檔個股) 數據與情緒指標..."):
    stocks_close, benchmark_close = download_data(tickers, benchmark_sym, lookback_days=lookback)
    breadth_df = calculate_market_breadth(stocks_close)

display_df = breadth_df.iloc[-lookback:]
display_bench = benchmark_close.iloc[-lookback:]
latest = display_df.iloc[-1]
prev = display_df.iloc[-2]

# --- 11. 頂部儀表盤：情緒 Gauge + 寬度關鍵指標 ---
st.markdown("### 🧭 市場情緒與微觀體質總覽")
row1_col1, row1_col2 = st.columns([1.1, 1.9])

with row1_col1:
    st.markdown("##### CNN 恐懼與貪婪指數 (Fear & Greed)")
    if fg_data:
        st.plotly_chart(plot_fear_greed_gauge(fg_data["score"], fg_data["rating"], fg_data["prev_close"]), use_container_width=True)
        # 歷史對照表
        h_c1, h_c2, h_c3, h_c4 = st.columns(4)
        h_c1.caption(f"昨收: **{fg_data['prev_close']}**")
        h_c2.caption(f"1週前: **{fg_data['prev_1w']}**")
        h_c3.caption(f"1月前: **{fg_data['prev_1m']}**")
        h_c4.caption(f"1年前: **{fg_data['prev_1y']}**")
    else:
        st.warning("暫時無法取得 CNN 官方 Fear & Greed 即時數據，請稍後刷新。")

with row1_col2:
    st.markdown(f"##### {selected_index} 市場寬度核心狀態")
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("> 200 SMA (年線)", f"{latest['Pct_Above_200SMA']:.1f}%", f"{latest['Pct_Above_200SMA'] - prev['Pct_Above_200SMA']:.1f}%")
    kpi2.metric("> 50 SMA (季線)", f"{latest['Pct_Above_50SMA']:.1f}%", f"{latest['Pct_Above_50SMA'] - prev['Pct_Above_50SMA']:.1f}%")
    kpi3.metric("> 20 SMA (月線)", f"{latest['Pct_Above_20SMA']:.1f}%", f"{latest['Pct_Above_20SMA'] - prev['Pct_Above_20SMA']:.1f}%")
    kpi4.metric("最新漲/跌", f"{int(latest['Advancers'])} / {int(latest['Decliners'])}", f"淨: {int(latest['Advancers'] - latest['Decliners'])}")

    macro_diag, sent_diag = diagnose_market(latest['Pct_Above_20SMA'], latest['Pct_Above_50SMA'], latest['Pct_Above_200SMA'])
    st.info(f"**長期趨勢結構：{macro_diag[0]}** — {macro_diag[1]}")
    if "超買" in sent_diag[0]:
        st.warning(f"**波段動能訊號：{sent_diag[0]}** — {sent_diag[1]}")
    elif "超賣" in sent_diag[0]:
        st.success(f"**波段動能訊號：{sent_diag[0]}** — {sent_diag[1]}")
    else:
        st.info(f"**波段動能訊號：{sent_diag[0]}** — {sent_diag[1]}")

st.markdown("---")

# --- 12. 主圖表：指數走勢 vs 市場寬度 ---
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.08,
    row_heights=[0.55, 0.45],
    subplot_titles=(f"{selected_index} 價格走勢", "市場寬度：站上均線個股比例 (%)")
)

fig.add_trace(
    go.Scatter(x=display_bench.index, y=display_bench.values, name=selected_index, line=dict(color="#1f77b4", width=2)),
    row=1, col=1
)

fig.add_trace(
    go.Scatter(x=display_df.index, y=display_df['Pct_Above_50SMA'], name="% > 50 SMA (中期季線)", line=dict(color="#ff7f0e", width=1.5)),
    row=2, col=1
)
fig.add_trace(
    go.Scatter(x=display_df.index, y=display_df['Pct_Above_200SMA'], name="% > 200 SMA (長期年線)", line=dict(color="#2ca02c", width=1.5)),
    row=2, col=1
)

fig.add_hrect(y0=80, y1=100, fillcolor="rgba(255, 0, 0, 0.08)", line_width=0, row=2, col=1)
fig.add_hrect(y0=0, y1=20, fillcolor="rgba(0, 255, 0, 0.08)", line_width=0, row=2, col=1)

fig.add_hline(y=80, line_dash="dash", line_color="red", opacity=0.7, annotation_text="超買過熱 (80%)", row=2, col=1)
fig.add_hline(y=50, line_dash="dot", line_color="gray", opacity=0.4, annotation_text="多空分水嶺 (50%)", row=2, col=1)
fig.add_hline(y=20, line_dash="dash", line_color="green", opacity=0.7, annotation_text="超賣恐慌 (20%)", row=2, col=1)

fig.update_layout(
    height=580,
    margin=dict(l=20, r=20, t=35, b=20),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    template="plotly_white",
    hovermode="x unified"
)
fig.update_yaxes(title_text="點位", row=1, col=1)
fig.update_yaxes(title_text="佔比 (%)", range=[0, 100], row=2, col=1)
st.plotly_chart(fig, use_container_width=True)

# --- 13. 次圖表：騰落線 (A/D Line) & Fear and Greed 歷史 ---
chart_c1, chart_c2 = st.columns(2)

with chart_c1:
    st.subheader("📊 累積騰落線 (A/D Line)")
    fig_ad = go.Figure()
    fig_ad.add_trace(go.Scatter(x=display_df.index, y=display_df['AD_Line'], name="AD Line", line=dict(color="#9467bd", width=2)))
    fig_ad.update_layout(
        height=270,
        margin=dict(l=20, r=20, t=20, b=20),
        xaxis_title="日期",
        yaxis_title="累計淨家數",
        template="plotly_white",
        hovermode="x"
    )
    st.plotly_chart(fig_ad, use_container_width=True)

with chart_c2:
    st.subheader("📈 CNN 恐懼與貪婪歷史走勢")
    if fg_data and not fg_data["historical"].empty:
        df_hist = fg_data["historical"].tail(lookback)
        fig_fgh = go.Figure()
        fig_fgh.add_trace(go.Scatter(x=df_hist.index, y=df_hist['score'], name="F&G Score", line=dict(color="#d62728", width=1.8)))
        fig_fgh.add_hline(y=75, line_dash="dash", line_color="red", opacity=0.6, annotation_text="極度貪婪 (75)")
        fig_fgh.add_hline(y=25, line_dash="dash", line_color="green", opacity=0.6, annotation_text="極度恐懼 (25)")
        fig_fgh.update_layout(
            height=270,
            margin=dict(l=20, r=20, t=20, b=20),
            xaxis_title="日期",
            yaxis_title="指數分數 (0-100)",
            yaxis_range=[0, 100],
            template="plotly_white",
            hovermode="x"
        )
        st.plotly_chart(fig_fgh, use_container_width=True)
    else:
        st.info("無可用之歷史恐懼貪婪時間序列數據。")

# --- 14. 實戰教學說明 Tabs ---
st.markdown("---")
st.subheader("📖 深度量化解說與雙指標實戰閱讀指南")

tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 市場寬度百分比意義", 
    "📈 圖表閱讀心法 (均線/ADL)", 
    "⚡ 頂底背離戰法圖解",
    "🧭 恐懼貪婪與市場寬度共振戰法"
])

with tab1:
    st.markdown("""
    市場寬度計算的是**「市場上到底有多少比例的股票符合多頭條件」**。這能消除少數大型權重巨頭對指數造成的遮蔽扭曲。
    """)
    st.markdown("""
    | 區間範圍 | 市場狀態 | 量化意涵與交易策略解讀 |
    | :--- | :--- | :--- |
    | **80% ~ 100%** | **極度超買 (Overbought)** | **動能極致，警惕回檔。** 絕大多數個股都在上漲，情緒極其亢奮。歷史上不適合大舉追高，容易遭遇獲利回吐震盪。 |
    | **50% ~ 80%** | **健康多頭 (Healthy Bull)** | **最健康的趨勢推進區間。** 個股呈現良性板塊輪動，即使權重股盤整，中小型股亦能接棒推升指數。 |
    | **40% ~ 50%** | **多空分歧 (Neutral / Chop)** | **盤整與結構退化臨界點。** 多數個股開始跌破支撐，常出現「指數撐在平盤，但投資人持股體感慘淡」的撕裂行情。 |
    | **20% ~ 40%** | **弱勢空頭 (Bearish)** | **空頭主導。** 跌破均線的個股數量遠大於上漲家數，反彈多為弱勢反抽，建議以防禦減倉或逢高對沖為主。 |
    | **0% ~ 20%** | **極度超賣 (Oversold)** | **非理性恐慌出清。** 全市場極度冰封，常出現在熊市末期或牛市黑天鵝急殺洗盤。在右側配合止跌信號時，往往是勝率極高的「黃金買點」。 |
    """)

with tab2:
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### 1. 均線層級代表的實戰週期")
        st.markdown("""
        * **% > 200 SMA (年線 - 宏觀體質)**：
          * 判斷現在是處於**結構性大牛市**還是**大熊市**。
          * 若維持在 60% 以上，代表多頭基本盤堅固；若長年低於 40%，代表指數處於空頭週期。
        * **% > 50 SMA (季線 - 波段動能)**：
          * **交易員最常用的波段擺盪指標**。
          * 80% / 20% 兩條警示線對 50 SMA 最為靈敏，能精準捕捉 1~3 個月級別的波段轉折。
        * **% > 20 SMA (月線 - 短線情緒)**：
          * 反映 1~3 週極短線的市場心跳，適合超短線進出場節奏調整。
        """)
    with col_b:
        st.markdown("#### 2. 累積騰落線 (A/D Line) 怎麼看？")
        st.markdown("""
        * **趨勢確認**：
          * 當「指數往右上走，A/D Line 也往右上走」：代表上漲由**廣泛個股推動**，趨勢真實可靠。
        * **趨勢衰竭預警**：
          * 當「指數創波段新高，但 A/D Line 卻走平甚至向下掉」：代表上漲只剩少數幾檔股票在撐，市場廣度已經先行潰散（廣度耗竭），隨時可能補跌。
        """)

with tab3:
    st.markdown("#### ⚠️ 最重要的量化異象：背離（Divergence）")
    st.markdown("""
    1. **頂背離（Bearish Divergence）—— 提防假牛市閃崩**
       * **訊號特徵**：基準指數（Nasdaq 100 / S&P 500）在少數巨頭拉抬下**突破歷史新高**，但 `% > 50 SMA` 或 `% > 200 SMA` 的比例卻**明顯低於上一波高點**。
       * **背後邏輯**：大資金正在利用指數掩護其他非核心持股悄悄出貨。此時「體感下跌家數」已先變多，一旦權重股補跌，指數將面臨劇烈回檔。
    
    2. **底背離（Bullish Divergence）—— 掌握底部反轉點**
       * **訊號特徵**：指數在市場恐慌中**跌破前低或劇烈下挫**，但站上均線的個股比例卻**沒有破底、反而悄悄抬高**。
       * **背後邏輯**：多數成分股已經提前跌無可跌、主力資金已在底部暗中吃貨建倉，屬於市場即將見底反彈的先導領先訊號。
    """)

with tab4:
    st.markdown("#### 🧭 恐懼貪婪指數 (Fear & Greed) 與市場寬度的共振戰法")
    st.markdown("""
    CNN 恐懼與貪婪指數是由 **7 大獨立市場指標**加權計算得出：
    1. **股價動能 (Market Momentum)**：S&P 500 與其 125 日移動平均線的距離。
    2. **股價強度 (Stock Price Strength)**：紐約證交所創 52 週新高與新低的股票數量差。
    3. **股價廣度 (Stock Price Breadth)**：上漲個股成交量 vs 下跌個股成交量（McClellan Volume Summation Index）。
    4. **期權比率 (Put and Call Options)**：看跌期權 (Put) 與看漲期權 (Call) 成交量比。
    5. **市場波動率 (Market Volatility)**：VIX 指數及其 50 日均線表現。
    6. **避險資產需求 (Safe Haven Demand)**：過去 20 天股票與公債收益率之差距。
    7. **垃圾債券需求 (Junk Bond Demand)**：高收益垃圾債與投資級公司債之利差。

    ---

    ##### 💡 實戰共振決策矩陣

    * **🔥 頂部高危共振（強烈賣出/減倉訊號）**：
      * `Fear & Greed > 75 (極度貪婪)` **+** `市場寬度出現顯著「頂背離」`。
      * **解讀**：市場大眾散戶情緒極端盲目樂觀，但指數底層過半數股票已經跌破 50 SMA。少數龍頭股拉抬掩護主力出貨，極高機率引發閃崩或深度回調。

    * **💎 底部共振黃金坑（極高勝率波段進場訊號）**：
      * `Fear & Greed < 20 (極度恐慌)` **+** `市場寬度 % > 50 SMA < 20% (極度超賣)`。
      * **解讀**：流動性危機或恐慌性拋售進入尾聲，散戶與機構被迫不計成本停損砍倉，市場呈現「無差別殺跌」。此時右側只要配合寬度率先止跌抬升，通常是勝率最高、盈虧比極佳的波段起漲點。

    * **⚠️ 假摔假突破鑑別**：
      * 指數暴跌但 Fear & Greed 仍在 50 附近，且市場寬度年線未破 ➔ **健康牛次回調，非趨勢反轉**。
      * 指數持續上衝但 Fear & Greed 始終卡在中性 ➔ **市場參與度不足，多頭缺乏廣泛信號**。
    """)
