import requests
from io import StringIO

# --- 成分股抓取 (支援 User-Agent 偽裝與 GitHub 備援機制) ---
@st.cache_data(ttl=86400)
def get_constituents(index_name):
    """獲取主要指數的成分股列表 (具備防 403 阻擋機制)"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    try:
        if index_name == "S&P 500":
            benchmark = "^GSPC"
            try:
                # 方式一：帶 User-Agent 抓取 Wikipedia
                url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
                resp = requests.get(url, headers=headers, timeout=10)
                resp.raise_for_status()
                table = pd.read_html(StringIO(resp.text))[0]
                tickers = table['Symbol'].str.replace('.', '-', regex=False).tolist()
            except Exception:
                # 方式二（備援）：直接讀取 GitHub DataHub 開源 S&P 500 清單
                fallback_url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
                df_fallback = pd.read_csv(fallback_url)
                tickers = df_fallback['Symbol'].str.replace('.', '-', regex=False).tolist()

        elif index_name == "Nasdaq 100":
            benchmark = "^NDX"
            url = "https://en.wikipedia.org/wiki/Nasdaq-100"
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            
            # 動態比對包含 Ticker 或 Symbol 的表格，避免 index 跑掉
            tables = pd.read_html(StringIO(resp.text))
            tickers = []
            for t in tables:
                col = next((c for c in t.columns if c in ['Ticker', 'Symbol']), None)
                if col and len(t) >= 90:  # 確認是成分股大表
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
                if col and len(t) == 30:  # 道瓊固定為 30 檔
                    tickers = t[col].str.replace('.', '-', regex=False).tolist()
                    break
            if not tickers:
                raise ValueError("找不到道瓊成分股表格")

        return tickers, benchmark

    except Exception as e:
        st.warning(f"獲取完整成分股時出現警告: {e}，切換為預設權重龍頭股。")
        # 降級預備清單 (Mega-caps)
        return ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "UNH"], "^GSPC"
