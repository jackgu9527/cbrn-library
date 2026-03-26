import os
import psycopg2
import pandas as pd
from datetime import datetime, timezone, timedelta
import requests
import json
import warnings # 👈 新增這個
# 👈 新增這行，消滅熊貓套件的黃色警告
warnings.filterwarnings('ignore', category=UserWarning, module='pandas')
# 取得環境變數 (GitHub Secrets 會提供)
DATABASE_URL = os.environ.get('DATABASE_URL')
LINE_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_TARGET_ID = os.environ.get('LINE_TARGET_ID')

# 🚀 升級版：加上除錯雷達的發送函數
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
    
    print(f"📡 準備發射飛彈至 ID: {LINE_TARGET_ID[:5]}... (前5碼)")
    
    try:
        response = requests.post(
            "https://api.line.me/v2/bot/message/push", 
            headers=headers, 
            data=json.dumps(data)
        )
        # 🚨 這行是關鍵：印出 LINE 伺服器的回應狀態
        print(f"🎯 LINE 伺服器回應狀態碼: {response.status_code}")
        if response.status_code != 200:
            print(f"❌ 發送失敗！錯誤訊息: {response.text}")
        else:
            print("✅ 戰情報表已成功發送 (LINE 已確認接收)！")
    except Exception as e:
        print(f"💥 發送過程發生未預期爆炸: {e}")

def main():
    print(f"⏳ 開始執行定時戰情掃描... (台灣時間: {datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M:%S')})")
    
    if not DATABASE_URL:
        print("❌ 錯誤：缺少 DATABASE_URL Secrets。")
        return

    # 連線資料庫
    try:
        conn = psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"❌ 資料庫連線失敗: {e}")
        return
    
    # 這裡設定長官要監控的中隊清單
    target_squadrons = ['學員一中隊', '學員二中隊', '學生一中隊', '學生二中隊', '聯合中隊①', '聯合中隊②', '大隊部']
    
    now = datetime.now(timezone(timedelta(hours=8)))
    msg = f"準則管理系統通報\n時間：{now.strftime('%m/%d %H:%M')}\n\n"
    
    total_actions_needed = 0 # 全局計數器，用來判斷要不要發送
    
    for sq in target_squadrons:
        # 1. 查：新增註冊開通
        query_reg = f"SELECT COUNT(*) FROM users WHERE status='待審核' AND squadron='{sq}'"
        c_reg = pd.read_sql_query(query_reg, conn).iloc[0,0]
        
        # 2. 查：待審核借閱
        query_bor = f"SELECT COUNT(*) FROM borrow_requests br JOIN users u ON br.login_id=u.login_id WHERE br.status='待審核' AND u.squadron='{sq}'"
        c_bor = pd.read_sql_query(query_bor, conn).iloc[0,0]
        
        # 3. 查：待點收歸還
        query_ret = f"SELECT COUNT(*) FROM books b JOIN users u ON b.owner_id=u.login_id WHERE b.status='歸還中' AND u.squadron='{sq}'"
        c_ret = pd.read_sql_query(query_ret, conn).iloc[0,0]
        
        # 4. 查：已審核未登載 (保留待領取)
        query_res = f"SELECT COUNT(*) FROM books b JOIN users u ON b.owner_id=u.login_id WHERE b.status='保留待領取' AND u.squadron='{sq}'"
        c_res = pd.read_sql_query(query_res, conn).iloc[0,0]
        
        # 5. 查：少領異常
        query_abn = f"SELECT COUNT(*) FROM books b JOIN users u ON b.owner_id=u.login_id WHERE b.status='少領異常' AND u.squadron='{sq}'"
        c_abn = pd.read_sql_query(query_abn, conn).iloc[0,0]
        
        sq_total = c_reg + c_bor + c_ret + c_res + c_abn
        total_actions_needed += sq_total
        
        if sq_total > 0:
            msg += f"{sq}\n"
            msg += f"新增註冊開通：{f'{c_reg}件' if c_reg > 0 else '無'}\n"
            msg += f"待審核借閱：{f'{c_bor}件' if c_bor > 0 else '無'}\n"
            msg += f"待點收歸還：{f'{c_ret}件' if c_ret > 0 else '無'}\n"
            msg += f"已審核未登載：{f'{c_res}件' if c_res > 0 else '無'}\n"
            msg += f"少領異常：{f'{c_abn}件' if c_abn > 0 else '無'}\n\n"

    conn.close()

    # 🚀 終極火力保險：如果所有中隊加起來都是 0 件，直接結束，絕對不發訊息！
    if total_actions_needed == 0:
        print("💡 偵察結果：目前指定的各中隊皆無待辦事項，程式自動靜默。")
        return
        
    # 如果有資料，發射！
    send_line_message(msg.strip())

if __name__ == "__main__":
    main()
