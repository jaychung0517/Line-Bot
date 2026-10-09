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
    print("LINE 推播回應:", res.status_code)

def check_spring(df: pd.DataFrame) -> bool:
    if len(df) < 30:
        return False
    consolidation = df.iloc[-23:-3]
    r_high = consolidation['High'].max()
    r_low = consolidation['Low'].min()
    if (r_high - r_low) / r_low > 0.15:
        return False
    swept = (df.iloc[-2]['Low'] < r_low) or (df.iloc[-3]['Low'] < r_low)
    reclaimed = df.iloc[-1]['Close'] > r_low
    return swept and reclaimed

def check_fvg(df: pd.DataFrame) -> bool:
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
    # 自選股或成分股代碼清單
    watchlist = [
        "2330", "2317", "2454", "2382", "3231", 
        "2603", "2609", "1519", "1513", "3035", 
        "3443", "6446", "3661", "2376", "2356"
    ]
    
    spring_list = []
    fvg_list = []

    print("開始執行盤後篩選...")
    for sym in watchlist:
        try:
            df = yf.download(f"{sym}.TW", period="3mo", interval="1d", progress=False)
            if df.empty or len(df) < 30:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if df['Volume'].tail(5).mean() < 1_000_000:
                continue
            
            if check_spring(df):
                spring_list.append(sym)
            elif check_fvg(df):
                fvg_list.append(sym)
        except Exception as e:
            print(f"掃描 {sym} 錯誤: {e}")

    report = f"📊【明日早盤觀察名單】({datetime.date.today()})\n\n"
    report += f"🔍 橫向整理破底翻:\n{', '.join(spring_list) if spring_list else '無符合標的'}\n\n"
    report += f"🎯 多頭 FVG/OB 回踩:\n{', '.join(fvg_list) if fvg_list else '無符合標的'}\n\n"
    report += "⚡ 提醒: 明日 09:15 僅對上述標的確認成交量與 2% 漲幅。"

    print(report)
    send_line_push(report)

if __name__ == "__main__":
    main()
