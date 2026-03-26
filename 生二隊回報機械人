import os
import psycopg2
import pandas as pd
from datetime import datetime, timezone, timedelta
import requests
import warnings
import json  # 👈 LINE 官方 API 必須用到 json

# 忽略 pandas 警告
warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

# 從環境變數抓取金鑰 (改為官方帳號規格)
DATABASE_URL = os.environ.get('DATABASE_URL')
LINE_TOKEN = os.environ.get('LINE_TOKEN')
LINE_TARGET_ID = os.environ.get('LINE_TARGET_ID')

# 🚀 升級回 LINE 官方帳號發送函數
def send_line_message(message):
    if not LINE_TOKEN or not LINE_TARGET_ID:
        print("❌ 錯誤：缺少 LINE Token 或 Target ID。")
        return
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "to": LINE_TARGET_ID,
        "messages": [{"type": "text", "text": message}]
    }
    try:
        response = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, data=json.dumps(data))
        if response.status_code == 200:
            print("✅ 報表已成功發送！")
        else:
            print(f"❌ 發送失敗！錯誤碼: {response.status_code}, 訊息: {response.text}")
    except Exception as e:
        print(f"💥 發送過程發生未預期爆炸: {e}")

# 📊 產出【借還書清單】(每週三) - (與原本相同，省略細節以防太長，請保留你原本的程式碼)
def generate_borrow_return_report(conn):
    # ...(保留你原本的程式碼)...
    now = datetime.now(timezone(timedelta(hours=8)))
    tw_wd = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
    msg = f"劉姐好，學生二中隊借還書清單\n時間：{now.month}/{now.day}（{tw_wd}）\n\n"
    # ... 中間省略 ...
    return msg.strip()

# 📦 產出【準則清點】(每週四) - (與原本相同)
def generate_inventory_report(conn):
    # ...(保留你原本的程式碼)...
    now = datetime.now(timezone(timedelta(hours=8)))
    tw_wd = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
    msg = f"學生二中隊準則清點總表\n時間：{now.month}/{now.day}（{tw_wd}）\n\n"
    # ... 中間省略 ...
    return msg.strip()

def main():
    if not DATABASE_URL:
        print("❌ 錯誤：缺少 DATABASE_URL。")
        return
        
    now = datetime.now(timezone(timedelta(hours=8)))
    weekday = now.weekday()
    
    # 抓取 GitHub 傳進來的環境變數
    override = os.environ.get('MANUAL_OVERRIDE', 'auto')
    custom_text = os.environ.get('CUSTOM_TEXT', '') # 🌟 抓取自訂文字
    
    try:
        # 如果是發送自訂訊息，根本不需要連線資料庫，直接發射！
        if override == 'custom':
            if custom_text.strip():
                print(f"⏳ 準備發送【自訂訊息】: {custom_text}")
                send_line_message(custom_text)
            else:
                print("⚠️ 錯誤：您選擇了發送自訂訊息，但沒有輸入任何文字！")
            return # 發完就結束程式
            
        # 報表類需要連資料庫
        conn = psycopg2.connect(DATABASE_URL)
        
        if override == 'wednesday' or (override == 'auto' and weekday == 2):
            print("⏳ 準備發送【借還書清單】...")
            msg = generate_borrow_return_report(conn)
            send_line_message(msg)
            
        elif override == 'thursday' or (override == 'auto' and weekday == 3):
            print("⏳ 準備發送【準則清點總表】...")
            msg = generate_inventory_report(conn)
            send_line_message(msg)
            
        else:
            print("💡 自動排程模式：今日非週三或週四，無需發送報表。")
            
    except Exception as e:
        print(f"❌ 資料庫連線或執行錯誤：{e}")
    finally:
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    main()
