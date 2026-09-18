import os
import requests
import pandas as pd
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage
)

# -------------------------------------------------------------
# 1. 取得當前 0050 最新 50 檔成分股 (可替換為元大官網爬蟲或固定 set)
# -------------------------------------------------------------
CURRENT_0050 = {
    "2330", "2317", "2454", "2308", "2382", "2412", "2881", "2882", "2303", "2891",
    "3711", "3008", "2886", "1216", "2884", "3231", "2892", "2885", "5880", "2880",
    "2887", "2603", "3034", "2357", "4938", "2379", "6669", "2890", "1301", "1303",
    "2002", "2883", "5871", "3045", "4904", "2912", "2345", "1101", "2207", "3661",
    "2395", "1590", "2327", "2609", "2615", "6505", "1402", "9910", "1326", "2801"
}

# -------------------------------------------------------------
# 2. 爬取 TWSE 證交所全市場每日收盤市值
# -------------------------------------------------------------
def fetch_twse_market_cap():
    """
    從證交所 OpenAPI 或每日行情抓取股票代號與最新市值
    此處抓取證交所公開之盤後股票市值彙總資料
    """
    url = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    res = requests.get(url, headers=headers, timeout=10)
    data = res.json()
    
    # 欄位通常包含: Code (代號), Name (名稱), PE (本益比), PB (股價淨值比), DividendYield (殖利率)
    # 市值可搭配收盤行情 https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL
    stock_url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    stock_res = requests.get(stock_url, headers=headers, timeout=10)
    stock_data = stock_res.json()
    
    # 建立收盤價 DataFrame
    df_stocks = pd.DataFrame(stock_data)
    df_stocks = df_stocks.rename(columns={"Code": "ticker", "Name": "name", "ClosingPrice": "close"})
    df_stocks["close"] = pd.to_numeric(df_stocks["close"].str.replace(",", ""), errors="coerce")
    
    # 抓取上市資本額表計算發行股數 (或直接抓取 TWSE 每日市值排行)
    # 為確保範例穩定運行，此處調用證交所「每日收盤總市值表」API
    cap_url = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX20"
    cap_res = requests.get(cap_url, headers=headers, timeout=10)
    
    records = []
    if cap_res.status_code == 200 and len(cap_res.json()) > 0:
        for item in cap_res.json():
            records.append({
                "ticker": item.get("Code"),
                "name": item.get("Name"),
                "market_cap": float(item.get("MarketCapitalization", "0").replace(",", ""))
            })
        return pd.DataFrame(records)
    else:
        # 備用降級：由股價排序示意
        return pd.DataFrame()


# -------------------------------------------------------------
# 3. 0050 緩衝區預測演算法
# -------------------------------------------------------------
def analyze_0050_changes(df_market):
    # 依市值由大到小排序
    df_sorted = df_market.sort_values(by="market_cap", ascending=False).reset_index(drop=True)
    df_sorted["rank"] = df_sorted.index + 1
    df_sorted["is_current"] = df_sorted["ticker"].isin(CURRENT_0050)

    # 規則 1：非成分股進入前 40 名 -> 絕對納入
    must_add = df_sorted[(~df_sorted["is_current"]) & (df_sorted["rank"] <= 40)]
    
    # 規則 2：現有成分股跌出 60 名之外 -> 絕對剔除
    must_delete = df_sorted[(df_sorted["is_current"]) & (df_sorted["rank"] >= 61)]
    
    # 規則 3：前 41~45 名之非成分股（密切觀察遞補區）
    watchlist = df_sorted[(~df_sorted["is_current"]) & (df_sorted["rank"] > 40) & (df_sorted["rank"] <= 45)]

    return must_add, must_delete, watchlist


# -------------------------------------------------------------
# 4. 發送 LINE 訊息
# -------------------------------------------------------------
def send_line_alert(channel_token, user_id, message_text):
    config = Configuration(access_token=channel_token)
    with ApiClient(config) as api_client:
        messaging_api = MessagingApi(api_client)
        request = PushMessageRequest(
            to=user_id,
            messages=[TextMessage(text=message_text)]
        )
        messaging_api.push_message(request)


# -------------------------------------------------------------
# 主執行程序
# -------------------------------------------------------------
if __name__ == "__main__":
    LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "T7g3sU4iMZylq3dvoWLcy8RYYNBa0jZPzjfuNuap3D5EzaGWeO6yGYLrkTOFmYdFOErmc97KJtzEnNPQhrrsVCmqs5jrcUudUiCVU0o/0UhluWEZI8Qtg+qMCYYPQkcv0FioANTsMikaPcH1RjE08gdB04t89/1O/w1cDnyilFU=")
    LINE_USER_ID = os.getenv("LINE_USER_ID", "U81b4b2054b21b221175fb92845dba60b")

    print("正在獲取證交所全市場資料...")
    df_market = fetch_twse_market_cap()

    if df_market.empty:
        print("無法取得即時市值資料，請檢查 API 回應狀態。")
        exit()

    must_add, must_delete, watchlist = analyze_0050_changes(df_market)

    # 組裝推播文字
    msg_lines = ["【0050 換股預測雷達】", ""]
    
    msg_lines.append(" 強制納入候選 (非成分股進入前40):")
    if not must_add.empty:
        for _, row in must_add.iterrows():
            msg_lines.append(f"  • {row['ticker']} {row['name']} (第 {row['rank']} 名)")
    else:
        msg_lines.append("  (暫無新進前 40 名標的)")

    msg_lines.append("\n⚠️ 強制剔除風險 (成分股跌出第61名):")
    if not must_delete.empty:
        for _, row in must_delete.iterrows():
            msg_lines.append(f"  • {row['ticker']} {row['name']} (第 {row['rank']} 名)")
    else:
        msg_lines.append("  (成分股皆在前 60 名內)")

    msg_lines.append("\n 邊界觀察名單 (第41~45名):")
    if not watchlist.empty:
        for _, row in watchlist.iterrows():
            msg_lines.append(f"  • {row['ticker']} {row['name']} (第 {row['rank']} 名)")
    else:
        msg_lines.append("  (無符合標的)")

    final_msg = "\n".join(msg_lines)
    print(final_msg)

    # 發送到 LINE
    if LINE_ACCESS_TOKEN != "你的_LINE_CHANNEL_ACCESS_TOKEN":
        send_line_alert(LINE_ACCESS_TOKEN, LINE_USER_ID, final_msg)
        print("LINE 訊息推播成功！")
    else:
        print("未設定 Token，僅於本地終端機輸出。")
