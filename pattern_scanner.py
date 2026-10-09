import os
import datetime
import requests
import pandas as pd
import yfinance as yf

LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

def send_line_push(message: str):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("LINE 密鑰未設定，略過推播。")
        return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}]
    }
    res = requests.post(url, headers=headers, json=payload, timeout=10)
    print("LINE 推播回應碼:", res.status_code)

def fetch_top_stocks() -> dict:
    """
    從證交所抓取：
    1. 當日成交金額 (成交值) 前 100 大
    2. 當日成交股數 (成交量) 前 100 大
    回傳: { '2330': '台積電', '2603': '長榮', ... }
    """
    stock_dict = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    # 1. 抓取成交金額前 100 大
    url_val = "https://www.twse.com.tw/rwd/zh/afterTrading/A112?response=json"
    try:
        res = requests.get(url_val, headers=headers, timeout=10)
        data = res.json()
        if "data" in data:
            for row in data["data"]:
                code = str(row[1]).strip()
                name = str(row[2]).strip()
                # 只保留 4 碼普通股，排除認購售權證與 00 開頭之 ETF
                if len(code) == 4 and code.isdigit() and not code.startswith("00"):
                    stock_dict[code] = name
    except Exception as e:
        print(f"抓取成交金額排行失敗: {e}")

    # 2. 抓取成交量 (股數) 前 100 大
    url_vol = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX20?response=json"
    try:
        res = requests.get(url_vol, headers=headers, timeout=10)
        data = res.json()
        if "data" in data:
            for row in data["data"]:
                code = str(row[1]).strip()
                name = str(row[2]).strip()
                if len(code) == 4 and code.isdigit() and not code.startswith("00"):
                    stock_dict[code] = name
    except Exception as e:
        print(f"抓取成交股數排行失敗: {e}")

    print(f"成功取得熱門/成交值/成交量去重後股票池，共 {len(stock_dict)} 檔。")
    return stock_dict

def check_spring(df: pd.DataFrame) -> bool:
    """橫向整理破底翻 (Spring) 判定"""
    if len(df) < 30:
        return False
    # 觀察倒數第 22 天到倒數第 3 天的盤整區 (20 天)
    consolidation = df.iloc[-23:-3]
    r_high = consolidation['High'].max()
    r_low = consolidation['Low'].min()
    if (r_high - r_low) / r_low > 0.15:
        return False
    swept = (df.iloc[-2]['Low'] < r_low) or (df.iloc[-3]['Low'] < r_low)
    reclaimed = df.iloc[-1]['Close'] > r_low
    return swept and reclaimed

def check_fvg(df: pd.DataFrame) -> bool:
    """看漲 FVG / OB 回踩判定"""
    if len(df) < 20:
        return False
    curr_bar = df.iloc[-1]
    for i in range(len(df) - 15, len(df) - 3):
        b1 = df.iloc[i]
        b3 = df.iloc[i + 2]
        if b1['High'] < b3['Low']:
            if curr_bar['Low'] <= b3['Low'] and curr_bar['Close'] >= b1['High']:
                return True
    return False

def main():
    stock_dict = fetch_top_stocks()
    if not stock_dict:
        print("未取得股票名單，程序終止。")
        return

    # 組裝批次下載清單 (格式: 2330.TW 2317.TW ...)
    tickers = [f"{code}.TW" for code in stock_dict.keys()]
    
    print("正在批次下載 K 線數據...")
    # 一次性下載所有股票，大幅提升速度並避免觸發 Yahoo API 限制
    data = yf.download(tickers, period="3mo", interval="1d", group_by="ticker", progress=False)

    spring_list = []
    fvg_list = []

    for code, name in stock_dict.items():
        ticker = f"{code}.TW"
        try:
            if ticker not in data or data[ticker].empty:
                continue
            
            df = data[ticker].dropna()
            if len(df) < 30:
                continue

            # 雙重保護：確認近 5 日日均量大於 1,000 張
            if df['Volume'].tail(5).mean() < 1_000_000:
                continue

            stock_label = f"{code} {name}"
            
            if check_spring(df):
                spring_list.append(stock_label)
            elif check_fvg(df):
                fvg_list.append(stock_label)
        except Exception as e:
            continue

    # 組裝推播文字
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    report = f"📊【明日早盤觀察名單】({today_str})\n\n"
    report += f"🔍 橫向整理破底翻:\n{', '.join(spring_list) if spring_list else '無符合標的'}\n\n"
    report += f"🎯 多頭 FVG/OB 回踩:\n{', '.join(fvg_list) if fvg_list else '無符合標的'}"

    print(report)
    send_line_push(report)

if __name__ == "__main__":
    main()
