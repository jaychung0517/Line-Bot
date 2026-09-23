import os
import re
import json
import requests
import pandas as pd
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage
)

HISTORY_FILE = "previous_ranks.json"

# -------------------------------------------------------------
# 1. 讀取與儲存歷史名次 (JSON)
# -------------------------------------------------------------
def load_previous_ranks() -> dict:
    """讀取前一次執行的個股名次紀錄 { '股票代號': rank }"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"讀取歷史紀錄異常: {e}")
    return {}

def save_current_ranks(current_ranks: dict):
    """將當天全市場個股名次存入 JSON 檔案"""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(current_ranks, f, ensure_ascii=False, indent=2)
        print("今日名次已成功存檔。")
    except Exception as e:
        print(f"存檔異常: {e}")


# -------------------------------------------------------------
# 2. 元大官網動態爬蟲：取得最新 0050 成分股
# -------------------------------------------------------------
def get_yuanta_0050_components() -> set:
    url = "https://www.yuantafunds.com/api/fund/holding"
    params = {"fundCode": "1066"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.yuantafunds.com/fund/holding/1066",
        "Accept": "application/json, text/plain, */*"
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            holding_list = data.get("data", []) if isinstance(data, dict) else data
            if isinstance(holding_list, dict):
                holding_list = holding_list.get("list", []) or holding_list.get("holdings", [])

            components = set()
            for item in holding_list:
                code = item.get("stockCode") or item.get("symbol") or item.get("code") or ""
                code = str(code).strip()
                if re.match(r"^\d{4}$", code):
                    components.add(code)

            if len(components) >= 45:
                print(f"成功自元大投信官網同步最新 0050 成分股，共 {len(components)} 檔。")
                return components
    except Exception as e:
        print(f"元大投信 API 連線異常: {e}，啟用靜態備援名單。")

    return {
        "2330", "2317", "2454", "2308", "2382", "2412", "2881", "2882", "2303", "2891",
        "3711", "3008", "2886", "1216", "2884", "3231", "2892", "2885", "5880", "2880",
        "2887", "2603", "3034", "2357", "4938", "2379", "6669", "2890", "1301", "1303",
        "2002", "2883", "5871", "3045", "4904", "2912", "2345", "1101", "2207", "3661",
        "2395", "1590", "2327", "2609", "2615", "6505", "1402", "9910", "1326", "2801"
    }


# -------------------------------------------------------------
# 3. 爬取 TWSE 證交所全市場每日收盤市值
# -------------------------------------------------------------
def fetch_twse_market_cap():
    cap_url = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX20"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        cap_res = requests.get(cap_url, headers=headers, timeout=15)
        records = []
        if cap_res.status_code == 200:
            for item in cap_res.json():
                records.append({
                    "ticker": item.get("Code", "").strip(),
                    "name": item.get("Name", "").strip(),
                    "market_cap": float(item.get("MarketCapitalization", "0").replace(",", ""))
                })
            return pd.DataFrame(records)
    except Exception as e:
        print(f"證交所 API 連線異常: {e}")
    return pd.DataFrame()


# -------------------------------------------------------------
# 4. 股票過濾器與 0050 換股預測核心
# -------------------------------------------------------------
def is_common_stock(ticker: str) -> bool:
    """排除 00 開頭 ETF、01 開頭受益證券及特別股，僅保留 4 碼純數字普通股"""
    ticker = str(ticker).strip()
    if ticker.startswith("00") or ticker.startswith("01"):
        return False
    return bool(re.match(r"^\d{4}$", ticker))


def analyze_0050_changes(df_market: pd.DataFrame, current_components: set):
    df_sorted = df_market.sort_values(by="market_cap", ascending=False).reset_index(drop=True)
    df_sorted["rank"] = df_sorted.index + 1
    df_sorted["is_current"] = df_sorted["ticker"].isin(current_components)

    # 過濾出純普通股
    df_sorted["is_stock"] = df_sorted["ticker"].apply(is_common_stock)
    df_stocks = df_sorted[df_sorted["is_stock"]].copy()

    # 潛在納入候選：非現有成分股且依市值排序，取前 5 名
    potential_additions = df_stocks[~df_stocks["is_current"]].head(5)

    # 同步回傳全市場當前排名字典 {ticker: rank}，供存檔比對
    all_ranks_dict = dict(zip(df_stocks["ticker"], df_stocks["rank"]))

    return potential_additions, all_ranks_dict


# -------------------------------------------------------------
# 5. 發送 LINE 推播訊息
# -------------------------------------------------------------
def send_line_alert(channel_token: str, user_id: str, message_text: str):
    config = Configuration(access_token=channel_token)
    with ApiClient(config) as api_client:
        messaging_api = MessagingApi(api_client)
        request = PushMessageRequest(
            to=user_id,
            messages=[TextMessage(text=message_text)]
        )
        messaging_api.push_message(request)


# -------------------------------------------------------------
# 主執行流程
# -------------------------------------------------------------
if __name__ == "__main__":
    LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "你的_LINE_CHANNEL_ACCESS_TOKEN")
    LINE_USER_ID = os.getenv("LINE_USER_ID", "你的_USER_ID")

    print("1. 取得歷史名次紀錄...")
    prev_ranks = load_previous_ranks()

    print("2. 取得最新 0050 成分股清單...")
    current_0050 = get_yuanta_0050_components()

    print("3. 抓取證交所全市場最新市值資料...")
    df_market = fetch_twse_market_cap()

    if df_market.empty:
        print("無法取得即時市值資料，中斷執行。")
        exit(1)

    print("4. 執行 0050 換股模型分析...")
    potential_additions, all_ranks = analyze_0050_changes(df_market, current_0050)

    # 組裝推播文字
    msg_lines = ["【0050 換股預測-3、6、9、12 月】", ""]
    msg_lines.append("潛在納入候選 Top 5:")

    if not potential_additions.empty:
        for idx, (_, row) in enumerate(potential_additions.iterrows(), 1):
            ticker = row["ticker"]
            name = row["name"]
            current_rank = row["rank"]

            # 比對昨日名次
            if ticker in prev_ranks:
                prev_rank = prev_ranks[ticker]
                if current_rank < prev_rank:      # 名次數字變小 = 排名上升
                    rank_str = f"第{current_rank}名↑"
                elif current_rank > prev_rank:    # 名次數字變大 = 排名下降
                    rank_str = f"第{current_rank}名↓"
                else:
                    rank_str = f"第{current_rank}名="
            else:
                rank_str = f"第{current_rank}名"

            msg_lines.append(f"  {idx}. {ticker} {name} ({rank_str})")
    else:
        msg_lines.append("  (暫無候選標的)")

    final_msg = "\n".join(msg_lines)
    print("\n" + final_msg + "\n")

    # 發送 Line 通知
    if LINE_ACCESS_TOKEN != "你的_LINE_CHANNEL_ACCESS_TOKEN":
        send_line_alert(LINE_ACCESS_TOKEN, LINE_USER_ID, final_msg)
        print("LINE 訊息推播成功！")
    else:
        print("本地測試未提供 Token，已略過 LINE 發送。")

    # 存入今日名次供下次比對
    save_current_ranks(all_ranks)
