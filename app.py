import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime
import requests
from io import StringIO

# --- 1. 頁面配置 ---
st.set_page_config(
    page_title="美股市場寬度 (Market Breadth) 量化監控儀表板",
    page_icon="📈",
    layout="wide"
)

# --- 2. 成分股獲取 (支援 Anti-403 與備援清單) ---
@st.cache_data(ttl=86400)
def get_constituents(index_name):
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
                raise ValueError("找不到 Nasdaq 100 數據表")

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
                raise ValueError("找不到道瓊成分股數據表")

        return tickers, benchmark
    except Exception as e:
        st.warning(f"獲取完整清單失敗: {e}，切換為十大核心龍頭股。")
        return ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "UNH"], "^GSPC"

# --- 3. 下載數據 ---
@st.cache_data(ttl=3600)
def download_data(tickers, benchmark_ticker, lookback_days=365):
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=lookback_days + 250)
    all_tickers = list(set(tickers + [benchmark_ticker]))
    
    df = yf.download(all_tickers, start=start_date, end=end_date, interval="1d", progress=False)
    close_df = df['Close'].copy() if 'Close' in df else df.copy()

    benchmark_close = close_df[benchmark_ticker]
    stocks_close = close_df.drop(columns=[benchmark_ticker], errors='ignore').dropna(how='all', axis=1)
    return stocks_close, benchmark_close

# --- 4. 計算市場寬度 ---
def calculate_market_breadth(stocks_close):
    sma_20 = stocks_close.rolling(window=20).mean()
    sma_50 = stocks_close.rolling(window=50).mean()
    sma_200 = stocks_close.rolling(window=200).mean()

    pct_above_20 = (stocks_close > sma_20).sum(axis=1) / stocks_close.notna().sum(axis=1) * 100
    pct_above_50 = (stocks_close > sma_50).sum(axis=1) / stocks_close.notna().sum(axis=1) * 100
    pct_above_200 = (stocks_close > sma_200).sum(axis=1) / stocks_close.notna().sum(axis=1) * 100

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

# --- 5. 智能診斷函數 ---
def diagnose_market(p20, p50, p200):
    status = []
    # 長期結構
    if p200 >= 70:
        macro = ("🟢 長期牛市格局良好", "超過 70% 標的站在年線之上，市場整體大趨勢偏多。")
    elif p200 <= 35:
        macro = ("🔴 長期處於系統性弱勢", "低於 35% 標的在年線上，防禦為上，注意長期下行壓力。")
    else:
        macro = ("🟡 長期中性多空拉鋸", "年線佔比位於中性區間，市場多空分歧未定。")
    
    # 中短期情緒
    if p50 >= 80:
        sentiment = ("⚠️ 中期動能極度過熱 (超買)", "高達 80% 以上個股站上季線，通常伴隨短期籌碼衰竭，留意回檔震盪。")
    elif p50 <= 20:
        sentiment = ("💎 中期極度悲觀 (超賣區)", "低於 20% 個股站上季線，恐慌盤大量湧現，常孕育反彈或波段買點。")
    elif p50 >= 55:
        sentiment = ("📈 中期健康多頭推升", "50-80% 區間為健康牛市推進行情，個股輪動良好。")
    else:
        sentiment = ("📉 中期空頭震盪整理", "季線佔比落於中線以下，個股跌多漲少。")

    return macro, sentiment

# --- UI 開始 ---
st.title("🏛️ 美股量化市場寬度 (Market Breadth) 儀表板")
st.caption("透過全市場成分股內部「微觀結構」，看穿市值加權巨頭掩蓋的真實盤勢。")

with st.sidebar:
    st.header("⚙️ 參數設定")
    selected_index = st.selectbox("監控基準指數", ["S&P 500", "Nasdaq 100", "Dow Jones Industrial Average"])
    lookback = st.slider("回測與圖表顯示天數", min_value=90, max_value=730, value=365, step=30)
    st.markdown("---")
    st.markdown("### 💡 快速提示")
    st.markdown("- **指數創新高 + 寬度下滑** = 頂背離 (出貨訊號)")
    st.markdown("- **指數創新低 + 寬度抬升** = 底背離 (築底訊號)")
    st.markdown("- **數值 > 80%** = 超買 / **數值 < 20%** = 超賣")

# 數據載入
tickers, benchmark_sym = get_constituents(selected_index)
with st.spinner(f"正在更新 {selected_index} 成分股數據與指標運算..."):
    stocks_close, benchmark_close = download_data(tickers, benchmark_sym, lookback_days=lookback)
    breadth_df = calculate_market_breadth(stocks_close)

display_df = breadth_df.iloc[-lookback:]
display_bench = benchmark_close.iloc[-lookback:]

latest = display_df.iloc[-1]
prev = display_df.iloc[-2]

# --- 頂部指標欄位 ---
c1, c2, c3, c4 = st.columns(4)
c1.metric("> 200 SMA (長期體質)", f"{latest['Pct_Above_200SMA']:.1f}%", f"{latest['Pct_Above_200SMA'] - prev['Pct_Above_200SMA']:.1f}%")
c2.metric("> 50 SMA (中期動能)", f"{latest['Pct_Above_50SMA']:.1f}%", f"{latest['Pct_Above_50SMA'] - prev['Pct_Above_50SMA']:.1f}%")
c3.metric("> 20 SMA (短期情緒)", f"{latest['Pct_Above_20SMA']:.1f}%", f"{latest['Pct_Above_20SMA'] - prev['Pct_Above_20SMA']:.1f}%")
c4.metric("最新漲/跌家數", f"{int(latest['Advancers'])} / {int(latest['Decliners'])}", f"淨額: {int(latest['Advancers'] - latest['Decliners'])}")

# --- 即時市場診斷卡 ---
macro_diag, sent_diag = diagnose_market(latest['Pct_Above_20SMA'], latest['Pct_Above_50SMA'], latest['Pct_Above_200SMA'])

st.markdown("### 🤖 即時盤面量化健康診斷")
d_col1, d_col2 = st.columns(2)
with d_col1:
    st.info(f"**宏觀架構：{macro_diag[0]}**\n\n{macro_diag[1]}")
with d_col2:
    if "超買" in sent_diag[0]:
        st.warning(f"**波段動能：{sent_diag[0]}**\n\n{sent_diag[1]}")
    elif "超賣" in sent_diag[0]:
        st.success(f"**波段動能：{sent_diag[0]}**\n\n{sent_diag[1]}")
    else:
        st.info(f"**波段動能：{sent_diag[0]}**\n\n{sent_diag[1]}")

# --- 主互動圖表 ---
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.08,
    row_heights=[0.55, 0.45],
    subplot_titles=(f"{selected_index} 指數走勢", "市場寬度：成分股站上均線比例 (%)")
)

# 基準指數曲線
fig.add_trace(
    go.Scatter(x=display_bench.index, y=display_bench.values, name=selected_index, line=dict(color="#1f77b4", width=2)),
    row=1, col=1
)

# 均線比例
fig.add_trace(
    go.Scatter(x=display_df.index, y=display_df['Pct_Above_50SMA'], name="% > 50 SMA (中期季線)", line=dict(color="#ff7f0e", width=1.5)),
    row=2, col=1
)
fig.add_trace(
    go.Scatter(x=display_df.index, y=display_df['Pct_Above_200SMA'], name="% > 200 SMA (長期年線)", line=dict(color="#2ca02c", width=1.5)),
    row=2, col=1
)

# 區間色彩標記
fig.add_hrect(y0=80, y1=100, fillcolor="rgba(255, 0, 0, 0.08)", line_width=0, row=2, col=1)
fig.add_hrect(y0=0, y1=20, fillcolor="rgba(0, 255, 0, 0.08)", line_width=0, row=2, col=1)

# 參考線
fig.add_hline(y=80, line_dash="dash", line_color="red", opacity=0.7, annotation_text="超買過熱 (80%)", row=2, col=1)
fig.add_hline(y=50, line_dash="dot", line_color="gray", opacity=0.4, annotation_text="多空分水嶺 (50%)", row=2, col=1)
fig.add_hline(y=20, line_dash="dash", line_color="green", opacity=0.7, annotation_text="超賣恐慌 (20%)", row=2, col=1)

fig.update_layout(
    height=600,
    margin=dict(l=20, r=20, t=40, b=20),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    template="plotly_white",
    hovermode="x unified"
)
fig.update_yaxes(title_text="指數收盤點位", row=1, col=1)
fig.update_yaxes(title_text="站在均線上個股佔比 (%)", range=[0, 100], row=2, col=1)
st.plotly_chart(fig, use_container_width=True)

# --- 騰落線圖表 ---
st.subheader("📊 累積騰落線 (Advance-Decline Line, ADL)")
fig_ad = go.Figure()
fig_ad.add_trace(go.Scatter(x=display_df.index, y=display_df['AD_Line'], name="AD Line", line=dict(color="#9467bd", width=2)))
fig_ad.update_layout(
    height=280,
    margin=dict(l=20, r=20, t=20, b=20),
    xaxis_title="日期",
    yaxis_title="累計淨上漲家數",
    template="plotly_white",
    hovermode="x"
)
st.plotly_chart(fig_ad, use_container_width=True)

# --- 深度教學與解說分頁 (Tab Panel) ---
st.markdown("---")
st.subheader("📖 數值解說與圖表實戰閱讀指南")

tab1, tab2, tab3 = st.tabs(["🎯 百分比數值意義對照", "📈 圖表怎麼看 (核心心法)", "⚡ 經典背離戰法圖解"])

with tab1:
    st.markdown("""
    市場寬度計算的是**「市場上到底有多少比例的股票符合多頭條件」**。這能消除單一大型權重股（如 Apple, Nvidia）對指數造成的扭曲。
    """)
    st.markdown("""
    | 區間範圍 | 市場狀態 | 量化意涵與交易策略解讀 |
    | :--- | :--- | :--- |
    | **80% ~ 100%** | **極度超買 (Overbought)** | **動能極致，警惕回檔。** 絕大多數個股都在上漲，市場情緒極其亢奮。歷史上此區間可持續一小段時間，但已不適合大舉追高，容易遭遇獲利回吐震盪。 |
    | **50% ~ 80%** | **健康多頭 (Healthy Bull)** | **最健康的趨勢推進區間。** 個股呈現良性輪動（Sector Rotation），即便權重股休息，中小型成分股亦能接棒，指數穩健走揚。 |
    | **40% ~ 50%** | **多空分歧 (Neutral / Chop)** | **盤整與結構退化臨界點。** 多數個股開始跌破支撐，此時常出現「指數撐在平盤，但投資人體感慘淡」的撕裂行情。 |
    | **20% ~ 40%** | **弱勢空頭 (Bearish)** | **空頭主導。** 跌破均線的個股數量遠大於上漲家數，反彈大多為弱勢反抽，建議以防禦減倉或逢高對沖為主。 |
    | **0% ~ 20%** | **極度超賣 (Oversold)** | **非理性恐慌出清。** 全市場極度冰封，通常出現在熊市末期或牛市黑天鵝急殺洗盤。在右側配合止跌信號時，往往是勝率極高的「黃金買點」。 |
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
    在量化金融領域，市場寬度最核心的殺手級應用在於**「背離偵測」**：
    
    1. **頂背離（Bearish Divergence）—— 提防假牛市閃崩**
       * **訊號特徵**：基準指數（S&P 500 / Nasdaq）在科技巨頭拉抬下**突破歷史新高**，但 `% > 50 SMA` 或 `% > 200 SMA` 的比例卻**明顯低於上一波高點**。
       * **背後邏輯**：大資金正在利用指數掩護其他非核心持股悄悄出貨。此時「體感下跌家數」已先變多，一旦權重股補跌，指數將面臨劇烈回檔。
    
    2. **底背離（Bullish Divergence）—— 掌握底部反轉點**
       * **訊號特徵**：指數在市場恐慌中**跌破前低或劇烈下挫**，但站上均線的個股比例卻**沒有破底、反而悄悄抬高**。
       * **背後邏輯**：多數成分股已經提前跌無可跌、主力資金已在底部暗中吃貨建倉，屬於市場即將見底反彈的先導領先訊號。
    """)
