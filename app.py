import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
import os
import glob
import psycopg2
from psycopg2 import pool
from psycopg2 import IntegrityError
import warnings
import extra_streamlit_components as stx  
import requests  
import re  
import secrets  
from werkzeug.security import generate_password_hash, check_password_hash 
import psycopg2.errors 
from contextlib import contextmanager
import time
import html

warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

st.set_page_config(page_title="大隊部準則管理系統", layout="wide")
# 👇 新增：系統維護模式開關
MAINTENANCE_MODE = False  # 設為 True 開啟維護，設為 False 關閉維護
ALLOWED_ADMINS = ['gu'] # 填寫在維護期間「仍然可以登入」的帳號 (例如管理員帳號)
# 🎨 1. 側邊欄視覺革命 & UI 核心樣式注入
st.markdown("""
    <style>
    /* 核心文字縮略設定 (保留完美神作) */
    .single-line-text { white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; display: block !important; max-width: 100% !important; }
    [data-testid="stExpander"] details summary p { white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; max-width: 100%; }
    [data-testid="stSidebar"] div.stMarkdown p { white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; }
    hr.custom-divider { margin: 0.5em 0 !important; border: none; border-top: 1px solid rgba(255, 255, 255, 0.2); }
    div[data-testid="stTooltipContent"] { max-width: 85vw !important; width: max-content !important; }
    [data-testid="stCheckbox"] p { white-space: nowrap !important; font-size: clamp(12px, 3.5vw, 15px) !important; }
    
    /* 🚀 側邊欄視覺革命 2.0：絕對靠左、暴力高光追蹤 */
    
    /* 1. 打擊側邊欄牆壁：消除 Streamlit 預設的巨大左右留白 */
    [data-testid="stSidebarUserContent"] { 
        padding-left: 0.5rem !important; 
        padding-right: 0.5rem !important; 
        padding-top: 1.5rem !important; 
    }
    
    /* 2. 斬除紅圈與壓縮垂直空間 */
    [data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child { display: none !important; }
    [data-testid="stSidebar"] div[role="radiogroup"] { gap: 2px !important; }
    [data-testid="stSidebar"] div[role="radiogroup"] > label { 
        padding: 8px 10px !important; 
        margin: 0 !important; 
        border-radius: 6px; 
        transition: background 0.2s; 
    }
    [data-testid="stSidebar"] div[role="radiogroup"] > label p { 
        margin: 0 !important; 
        line-height: 1.2 !important; 
    }
    [data-testid="stSidebar"] div[role="radiogroup"] > label:hover { background-color: rgba(255, 255, 255, 0.05); }
    
    /* 3. 🌟 修復高光紅色追蹤 (改用 input:checked 確保絕對相容最新版 Streamlit) */
    [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) { 
        background-color: rgba(255, 75, 75, 0.1) !important; 
        border-left: 4px solid #ff4b4b !important; 
    }
    [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) p { 
        color: #ff4b4b !important; 
        font-weight: 800 !important; 
        font-size: 1.05em !important; 
    }
    /* 4. 🔪 徹底消滅原生拖曳條，並強制瘦身側邊欄寬度 */
    [data-testid="stSidebarResizer"] { 
        display: none !important; 
    }
    [data-testid="stSidebar"] {
        min-width: 180px !important;
        max-width: 180px !important;
    }
    </style>
""", unsafe_allow_html=True)

if 'sys_toast' in st.session_state:
    st.toast(st.session_state['sys_toast'])
    del st.session_state['sys_toast']

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
csv_candidates = [f for f in glob.glob(os.path.join(BASE_DIR, '*.csv')) if '準則資料庫' in f]
if not csv_candidates:
    csv_candidates = glob.glob(os.path.join(BASE_DIR, '*.csv'))
CSV_FILE = csv_candidates[0] if csv_candidates else None

# ==========================================
# 🛡️ 4. 柔性防呆煞車系統 (資料庫連線) - 第一階段優化版
# ==========================================
@st.cache_resource
def init_connection_pool():
    """全域唯一連線池，限制最大連線數 10，保護 Supabase 額度"""
    try:
        return psycopg2.pool.ThreadedConnectionPool(1, 10, st.secrets["DATABASE_URL"], connect_timeout=10)
    except Exception as e:
        st.error(f"🚨 連線池初始化失敗：{e}")
        st.stop()

db_pool = init_connection_pool()

def get_db_connection():
    """獲取連線 (相容原有寫法，含自動重試機制)"""
    try:
        conn = db_pool.getconn()
    except psycopg2.pool.PoolError:
        st.toast("⏳ 系統滿載處理中，為您自動重整...")
        time.sleep(1)
        st.rerun()
        
    try:
        with conn.cursor() as c:
            c.execute("SELECT 1")
    except Exception:
        db_pool.putconn(conn, close=True)
        try:
            conn = db_pool.getconn()
        except psycopg2.pool.PoolError:
            st.toast("⏳ 系統滿載處理中，為您自動重整...")
            time.sleep(1)
            st.rerun()
    return conn

def release_connection(conn):
    """安全歸還連線"""
    try:
        if conn: db_pool.putconn(conn)
    except Exception as e:
        send_line_notify(f"🚨 【系統告警】連線池異常！原因：{e}") 
        try: conn.close()
        except Exception: pass

# ==========================================
# 🚀 新增：全域資料快取 (Cache Data)
# ==========================================
@st.cache_data(ttl=300)
def fetch_inventory_data():
    """全域快取：準則總表讀取 (5 分鐘自動刷新)"""
    conn = get_db_connection()
    try:
        return pd.read_sql_query("SELECT * FROM books ORDER BY book_name", conn)
    finally:
        release_connection(conn)

def clear_inventory_cache():
    """手動清除快取開關 (有異動時呼叫)"""
    fetch_inventory_data.clear()

# ==========================================
# 📡 升級：LINE Messaging API 報警
# ==========================================
def send_line_notify(message):
    """將原 Line Notify 升級為 Messaging API Push 模式 (發送至管理群組)"""
    try:
        token = st.secrets.get("LINE_CHANNEL_ACCESS_TOKEN")
        admin_id = st.secrets.get("LINE_GROUP_ID_ADMIN")
        if not token or not admin_id: return
        
        url = "https://api.line.me/v2/bot/message/push"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "to": admin_id,
            "messages": [{"type": "text", "text": f"⚠️ 系統告警：\n{message}"}]
        }
        requests.post(url, headers=headers, json=payload, timeout=5)
    except Exception: pass

# ==========================================
# 🛡️ 4. 柔性防呆煞車系統 (資料庫交易)
# ==========================================
@contextmanager
def db_transaction(success_msg=None, error_prefix="操作失敗"):
    if st.session_state.get('db_locked', False):
        st.toast("⏳ 系統處理中，請稍候...")
        time.sleep(1)
        st.rerun()
    st.session_state['db_locked'] = True
    
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            yield c
        conn.commit()
        if success_msg:
            st.session_state['sys_toast'] = success_msg
            clear_inventory_cache()  # 🌟 核心優化：只要交易成功，立刻清除記憶體舊資料！
    except IntegrityError:
        conn.rollback()
        st.error(f"❌ {error_prefix}：資料衝突或已存在於系統中！")
        st.session_state['db_locked'] = False
        st.stop()
    except Exception as e:
        conn.rollback()
        st.error(f"❌ {error_prefix}：{e}")
        send_line_notify(f"❌ {error_prefix}：{e}")  # 🌟 核心優化：出錯時自動用 Messaging API 推播！
        st.session_state['db_locked'] = False
        st.stop()
    finally:
        release_connection(conn)
        st.session_state['db_locked'] = False 

def apply_shadow_sort(df, has_unit=False):
    if df.empty or 'status' not in df.columns or 'book_name' not in df.columns: return df
    df = df.copy()
    w_map = {'少領異常': 1, '申請中': 2, '待審核': 2, '保留待領取': 3, '已審核': 3, '借閱中': 4, '歸還中': 5, '遺失待賠': 6}
    df['w'] = df['status'].map(lambda x: w_map.get(x, 99))
    group_cols = ['unit', 'book_name'] if has_unit and 'unit' in df.columns else ['book_name']
    df['min_w'] = df.groupby(group_cols)['w'].transform('min')
    sort_order = ['unit', 'min_w', 'book_name', 'w'] if has_unit and 'unit' in df.columns else ['min_w', 'book_name', 'w']
    return df.sort_values(by=sort_order).reset_index(drop=True)

def log_action(user_id, action, details):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        tz_tw = timezone(timedelta(hours=8))
        tw_now = datetime.now(tz_tw).strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (tw_now, str(user_id), str(action), str(details)))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        release_connection(conn)

def draw_status_card(book_name, qty, status, extra_info=""):
    style_map = {
        '申請中': ('🔵', '#4da6ff'), '待審核': ('🔵', '#4da6ff'),
        '保留待領取': ('🟡', '#ffb84d'), '已審核': ('🟡', '#ffb84d'),
        '借閱中': ('🟢', '#4CAF50'), '歸還中': ('🔴', '#ff6666'),
        '少領異常': ('🔴', '#ff6666'), '遺失待賠': ('⚫', '#808080'), '在庫': ('⚪', '#ffffff')
    }
    icon, color = style_map.get(status, ('🔹', 'gray'))
    display_status = "已審核" if status == '保留待領取' else status
    
    html = f"""
    <div style="border: 1px solid rgba(255,255,255,0.2); border-radius: 8px; padding: 10px; margin-bottom: 10px; background-color: rgba(0,0,0,0.1);">
        <div class="single-line-text" style="font-size: clamp(14px, 4vw, 18px); font-weight: bold; color: {color}; margin-bottom: 4px;">
            {icon} {book_name}
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 14px; color: {color}; padding-left: 24px;">
            <span>(共 <b>{qty}</b> 本) {extra_info}</span><span style="text-align: right;">狀態：{display_status}</span>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

@st.dialog("⚠️ 徹底刪除帳號")
def delete_account_dialog(uid, title):
    st.error(f"將徹底刪除【{title}】的帳號與所有資料！\n\n此動作無法復原，請確認該班隊的準則皆已歸還。")
    if st.button("🚨 確認刪除", use_container_width=True):
        with db_transaction(success_msg="🗑️ 帳號已永久刪除！") as c:
            c.execute("SELECT login_id FROM users WHERE id=%s", (uid,))
            user_res = c.fetchone()
            if user_res:
                login_id = user_res[0]
                c.execute("SELECT COUNT(*) FROM books WHERE owner_id=%s AND status != '在庫'", (login_id,))
                if c.fetchone()[0] > 0:
                    st.error("❌ 刪除失敗！該班隊名下還有尚未歸還的準則，系統拒絕刪除！")
                    st.session_state['db_locked'] = False
                    st.stop()
            
            c.execute("DELETE FROM users WHERE id=%s", (uid,))
        st.rerun()

@st.dialog("🛠️ 強制退回庫房 (上帝模式)")
def force_return_dialog(ghost_id):
    st.warning(f"確定要強制將帳號【{ghost_id}】名下的所有準則退回庫房嗎？\n\n此功能僅用於修復系統隱形資料。")
    if st.button("🚨 確定強制退庫", type="primary", use_container_width=True):
        with db_transaction() as c:
            # 💡 升級版防嚇人邏輯：
            # 如果輸入的是'在庫'，只去抓「狀態不是在庫」的異常殭屍書；
            # 如果輸入的是其他帳號，就正常全抓。
            if ghost_id.strip() == '在庫':
                c.execute("UPDATE books SET status='在庫', owner_id='在庫' WHERE owner_id='在庫' AND status != '在庫'")
            else:
                c.execute("UPDATE books SET status='在庫', owner_id='在庫' WHERE owner_id=%s", (ghost_id.strip(),))
                
            reclaimed = c.rowcount
            if reclaimed > 0:
                now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
                          (now_time, st.session_state.login_id, "上帝模式強制退庫", f"強制收回 {ghost_id} 的 {reclaimed} 本幽靈準則。"))
                st.session_state['sys_toast'] = f"✅ 已強制收回 {reclaimed} 本幽靈/異常準則！"
            else:
                st.warning("⚠️ 系統沒有找到需要修復的異常準則。")
                st.session_state['db_locked'] = False
                st.stop()
        st.rerun()

@st.dialog("🚨 重複借閱確認")
def duplicate_borrow_dialog(borrow_requests, warnings_list):
    st.warning("系統偵測到以下重複借閱風險：")
    for w in warnings_list:
        st.markdown(f"- {w}")
    st.info("已跟幹部確認這本準則我已借閱但數量不足。")
    if st.button("✅ 我確認尚需再借閱此本準則", type="primary", use_container_width=True):
        with db_transaction(success_msg="✅ 申請已強制送出！請等待幹部審核。") as c:
            now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
            for b_name, qty in borrow_requests.items():
                c.execute("INSERT INTO borrow_requests (login_id, unit, book_name, quantity, status) VALUES (%s, %s, %s, %s, %s)", 
                          (st.session_state.login_id, st.session_state.title, b_name, qty, '待審核'))
                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)",
                          (now_time, st.session_state.login_id, "申請借閱(強制)", f"申請 {b_name} {qty} 本"))
        if 'cart' in st.session_state: st.session_state.cart = {}
        st.rerun()
            
@st.dialog("🚨 幹部借閱審核確認")
def admin_borrow_approve_dialog(selected_unit, final_decisions, df_records):
    warnings = []
    for r in df_records:
        req_id = r['單號']
        approve_qty = final_decisions.get(req_id, 0)
        if approve_qty > 0 and r['已持有數'] > 0:
            warnings.append(f"【{r['書名']}】(將核准 {approve_qty} 本，但該班隊已持有 {r['已持有數']} 本)")
    
    if warnings:
        st.warning("⚠️ 偵測到重複發放風險！該班隊已持有下列準則：")
        for w in warnings:
            st.markdown(f"- {w}")
        st.info("確定這是遺失補發或額外申請，並送出核發嗎？")
    else:
        st.info(f"確定要送出【{selected_unit}】的審核結果嗎？")
        
    if st.button("✅ 確認送出審核", type="primary", use_container_width=True):
        with db_transaction(success_msg="✅ 審核完成！") as c:
            now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
            shortage_flag = False
            
            for r in df_records:
                req_id, req_login, req_book, req_qty, req_unit = r['單號'], r['帳號'], r['書名'], r['申請數量'], r['班隊']
                requested_approve_qty = final_decisions.get(req_id, 0)
                
                c.execute("SELECT id FROM books WHERE book_name=%s AND status='在庫' LIMIT %s", (req_book, requested_approve_qty))
                approved_ids = [b[0] for b in c.fetchall()]
                
                actual_approve_qty = len(approved_ids) # 真正能發出去的實際數量
                
                if approved_ids: 
                    c.execute(f"UPDATE books SET status='保留待領取', owner_id=%s WHERE id IN ({','.join(map(str, approved_ids))})", (req_login,))
                    
                if actual_approve_qty > 0:
                    c.execute("UPDATE borrow_requests SET status=%s WHERE id=%s", (f'已審核(實發{actual_approve_qty}本)', req_id))
                    c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "審核借閱", f"審核 {req_book} {actual_approve_qty} 本給 {req_unit}"))
                    
                    if requested_approve_qty > actual_approve_qty:
                        shortage_flag = True
                else:
                    c.execute("UPDATE borrow_requests SET status='已踢退(無庫存或退件)' WHERE id=%s", (req_id,))
                    c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "踢退借閱", f"全數踢退 {req_unit} 的 {req_book} 申請"))
            
            if shortage_flag:
                st.session_state['sys_toast'] = "⚠️ 審核完成！(部分準則因庫存不足，已自動下修實發數量)"
        st.rerun()

@st.dialog("📥 歸還點收確認")
def admin_return_approve_dialog(selected_unit, to_stock_ids, to_borrowed_ids, to_lost_ids):
    st.info("⚠️ 請確認這些準則 **已確實歸還至實體圖書館** 後再按確認送出！")
    
    if to_lost_ids:
        st.error(f"🚨 注意：該帳號已結訓凍結，您踢退的 {len(to_lost_ids)} 本準則將直接轉為 **『遺失待賠』**！")
        
    if st.button("✅ 確認判定並送出", type="primary", use_container_width=True):
        has_action = False
        with db_transaction(success_msg="✅ 點收審核完成！") as c:
            now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
            
            if to_stock_ids:
                # 👇 移除危險的 id_list_str 字串拼貼，改用 ANY(%s) 搭配 tuple 安全傳遞
                c.execute("SELECT u.title, b.book_name, COUNT(b.id) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.id = ANY(%s) GROUP BY u.title, b.book_name", (to_stock_ids,))
                for u_name, b_name, qty in c.fetchall():
                    c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "準則歸還", f"收訖 {u_name} 歸還 {b_name} {qty} 本"))
                c.execute("UPDATE books SET status='在庫', owner_id='在庫' WHERE id = ANY(%s)", (to_stock_ids,))
                has_action = True
                
            if to_borrowed_ids:
                id_list_str = ','.join(map(str, to_borrowed_ids))
                c.execute(f"SELECT u.title, b.book_name, COUNT(b.id) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.id IN ({id_list_str}) GROUP BY u.title, b.book_name")
                for u_name, b_name, qty in c.fetchall():
                    c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "歸還踢退", f"未收訖 {u_name} 的 {b_name} {qty} 本，退回借閱狀態"))
                c.execute(f"UPDATE books SET status='借閱中' WHERE id IN ({id_list_str})")
                has_action = True
                
            if to_lost_ids:
                id_list_str = ','.join(map(str, to_lost_ids))
                c.execute(f"SELECT u.title, b.book_name, COUNT(b.id) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.id IN ({id_list_str}) GROUP BY u.title, b.book_name")
                for u_name, b_name, qty in c.fetchall():
                    c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "歸還轉遺失", f"未收訖(凍結帳號) {u_name} 的 {b_name} {qty} 本，轉列遺失"))
                c.execute(f"UPDATE books SET status='遺失待賠' WHERE id IN ({id_list_str})")
                has_action = True
                
            if not has_action: 
                st.session_state['db_locked'] = False
                st.stop()
        st.rerun()

def init_db():
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, login_id TEXT UNIQUE, password TEXT, role TEXT, squadron TEXT, title TEXT, discharge_date DATE, status TEXT DEFAULT '啟用')''')
        c.execute('''CREATE TABLE IF NOT EXISTS books (id SERIAL PRIMARY KEY, book_name TEXT, serial_number TEXT UNIQUE, owner_id TEXT, status TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS borrow_requests (id SERIAL PRIMARY KEY, login_id TEXT, unit TEXT, book_name TEXT, quantity INTEGER, status TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS action_logs (id SERIAL PRIMARY KEY, timestamp TEXT, user_id TEXT, action TEXT, details TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS vehicles (id SERIAL PRIMARY KEY, account_id TEXT, plate_number TEXT)''')
        c.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS squadron TEXT")
        c.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS unit_title TEXT")
        c.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS parking_lot TEXT")
        c.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS parking_number TEXT")
        c.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS discharge_date DATE")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_token TEXT")
        c.execute('''CREATE TABLE IF NOT EXISTS system_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute("INSERT INTO system_settings (setting_key, setting_value) VALUES ('daily_report_date', '1970-01-01') ON CONFLICT DO NOTHING")
        
        c.execute("SELECT COUNT(*) FROM users")
        if c.fetchone()[0] == 0:
            default_users = [
                ('admin', generate_password_hash('1234'), 'L1', '大隊部', '系統管理員', None, '啟用'),
                ('l2_test', generate_password_hash('1234'), 'L2', '學生一中隊', '煙幕士兵班115-1期', '2026-12-31', '啟用')
            ]
            c.executemany("INSERT INTO users (login_id, password, role, squadron, title, discharge_date, status) VALUES (%s,%s,%s,%s,%s,%s,%s)", default_users)
        
        c.execute("SELECT COUNT(*) FROM books")
        if c.fetchone()[0] == 0:
            if CSV_FILE and os.path.exists(CSV_FILE):
                try:
                    try: df_books = pd.read_csv(CSV_FILE, encoding='big5')
                    except UnicodeDecodeError: df_books = pd.read_csv(CSV_FILE, encoding='utf-8')
                    insert_data = []
                    for index, row in df_books.iterrows():
                        if '書刊名稱' in row and pd.notna(row['書刊名稱']):
                            raw_title = str(row['書刊名稱']).strip()
                            pub_date = str(row['出版日期']).strip()[:-2] if '出版日期' in row and pd.notna(row['出版日期']) and str(row['出版日期']).strip().endswith('.0') else str(row.get('出版日期', '')).strip()
                            book_title = f"{raw_title} [{pub_date}]" if pub_date else raw_title
                            qty = int(row['數量']) if '數量' in row and pd.notna(row['數量']) else int(row.get('化訓準則館', 1))
                            for i in range(1, qty + 1): insert_data.append((book_title, f"{book_title}-{i:03d}", '在庫', '在庫'))
                    c.executemany("INSERT INTO books (book_name, serial_number, owner_id, status) VALUES (%s,%s,%s,%s)", insert_data)
                except Exception: pass
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        release_connection(conn)

@st.cache_resource
def run_system_init():
    init_db()
    return True

try:
    run_system_init()
except Exception as e:
    err_msg = f"🚨 【系統癱瘓】資料庫連線或初始化失敗！詳細錯誤：{e}"
    send_line_notify(err_msg) 
    st.error(err_msg)
    st.stop()

# ==========================================
# 🛡️ 第二階段：極速權限管理與側邊欄引擎
# ==========================================

@st.cache_data
def get_target_sq_list(target_sq):
    """利用記憶體快取權限清單，避免每次打字或切換畫面都重新運算"""
    target_sq = str(target_sq).strip()
    if target_sq == '大隊部': 
        return ['大隊部', '聯合中隊①', '聯合中隊②', '學員一中隊', '學員二中隊', '學生一中隊', '學生二中隊']
    elif target_sq == '聯合中隊①': 
        return ['聯合中隊①', '學員一中隊', '學生一中隊']
    elif target_sq == '聯合中隊②': 
        return ['聯合中隊②', '學員二中隊', '學生二中隊']
    return [target_sq]

def calculate_permissions(user_sq):
    return get_target_sq_list(user_sq)

cookie_manager = stx.CookieManager(key="main_cookie_auth")

# 登出邏輯 (使用精準連線)
if st.session_state.get('logout_triggered'):
    if 'login_id' in st.session_state:
        with get_db_connection() as conn:
            with conn.cursor() as c:
                c.execute("UPDATE users SET session_token = NULL WHERE login_id=%s", (st.session_state.login_id,))
            conn.commit()
            
    try: cookie_manager.delete('sys_user_token')
    except KeyError: pass
    st.session_state.clear()
    st.session_state['force_logout'] = True
    st.session_state['sys_toast'] = "👋 登出成功！安全連線已銷毀。"

all_cookies = cookie_manager.get_all()

# 自動登入邏輯 (使用精準連線)
if 'logged_in' not in st.session_state and not st.session_state.get('force_logout'):
    if all_cookies and 'sys_user_token' in all_cookies:
        stored_token = all_cookies['sys_user_token']
        with get_db_connection() as conn:
            try:
                user_data = pd.read_sql_query("SELECT * FROM users WHERE session_token=%s", conn, params=(str(stored_token),))
                if not user_data.empty and user_data.iloc[0]['status'] not in ['待審核', '停權', '結訓凍結']:
                    if MAINTENANCE_MODE and user_data.iloc[0]['login_id'] not in ALLOWED_ADMINS:
                        pass # 維護期間，若不在白名單內，不執行自動登入
                    else:
                        for col in user_data.columns: st.session_state[col] = user_data.iloc[0][col]
                        st.session_state['base_sq_list'] = calculate_permissions(user_data.iloc[0]['squadron'])
                        st.session_state['logged_in'] = True
                        st.rerun()
            except Exception: pass

# ==========================================
# 🔑 登入與註冊介面
# ==========================================
if 'logged_in' not in st.session_state:
    st.markdown("##  大隊部準則管理系統")
    tab1, tab2 = st.tabs([" 系統登入", " 班隊註冊"])
    
    with tab1:
        login_id = st.text_input("帳號 (Login ID)")
        password = st.text_input("密碼 (Password)", type="password")
        if st.button("登入", type="primary"):
            if MAINTENANCE_MODE and login_id not in ALLOWED_ADMINS:
                st.error("🛠️ 系統目前正在進行維護，暫停登入服務！")
            else:
                conn = get_db_connection()
                try:
                    user = pd.read_sql_query("SELECT * FROM users WHERE login_id=%s", conn, params=(login_id,))
                    if not user.empty:
                        db_pass = user.iloc[0]['password']
                        is_auth = False
                        if db_pass and (db_pass.startswith('scrypt:') or db_pass.startswith('pbkdf2:')):
                            try: is_auth = check_password_hash(db_pass, password)
                            except ValueError: is_auth = False
                                
                        if is_auth:
                            if user.iloc[0]['status'] == '待審核': st.warning("⚠️ 您的帳號尚未開通，請等待幹部審核。")
                            elif user.iloc[0]['status'] == '停權': st.error("🚨 您的帳號因違規停權！請聯絡幹部處理。")
                            elif user.iloc[0]['status'] == '結訓凍結': st.error("❄️ 您的班隊已結訓，帳號已凍結鎖定！")
                            else:
                                new_token = secrets.token_urlsafe(32)
                                c = conn.cursor()
                                c.execute("UPDATE users SET session_token=%s WHERE id=%s", (new_token, int(user.iloc[0]['id'])))
                                conn.commit()
                                for col in user.columns: st.session_state[col] = user.iloc[0][col]
                                st.session_state['base_sq_list'] = calculate_permissions(user.iloc[0]['squadron'])
                                st.session_state['logged_in'] = True
                                cookie_manager.set('sys_user_token', new_token, expires_at=datetime.now() + timedelta(days=30))
                                log_action(login_id, "登入", "使用者成功安全登入系統")
                                import time; time.sleep(0.5); st.rerun()
                        else: st.error("❌ 帳號或密碼錯誤")
                    else: st.error("❌ 帳號或密碼錯誤")
                except Exception as e:
                    conn.rollback()
                    st.error(f"❌ 登入發生錯誤：{e}")
                finally:
                    release_connection(conn)

    with tab2:
        st.subheader("班隊註冊", help="...")
        reg_squadron = st.selectbox("中隊", ["學員一中隊", "學員二中隊", "學生一中隊", "學生二中隊"])
        reg_title = st.text_input("班隊全銜 （消除士兵班115-2期)")
        reg_id = st.text_input("設定登入帳號")
        reg_pw = st.text_input("設定登入密碼", type="password")
        reg_date = st.date_input("結訓日期")
        
        if MAINTENANCE_MODE:
            st.warning("🛠️ 系統維護中，暫停開放新帳號註冊！")
            
        if st.button("送出註冊申請", disabled=MAINTENANCE_MODE):
            if reg_title and reg_id and reg_pw:
                import re
                if not re.match(r"^[A-Za-z0-9_]+$", reg_id):
                    st.error("❌ 帳號格式錯誤：為了系統安全，帳號只能包含大小寫英文、數字與底線 (_)。")
                    st.stop()
                with db_transaction(success_msg="✅ 註冊申請已送出！請等待幹部審核後即可登入。") as c:
                    c.execute("SELECT COUNT(*) FROM users WHERE login_id=%s", (reg_id,))
                    if c.fetchone()[0] > 0: 
                        st.error("❌ 此帳號已被使用！")
                        st.session_state['db_locked'] = False
                        st.stop()
                    hashed_pw = generate_password_hash(reg_pw)
                    c.execute("INSERT INTO users (login_id, password, role, squadron, title, discharge_date, status) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                              (reg_id, hashed_pw, 'L2', reg_squadron, reg_title, reg_date.strftime('%Y-%m-%d'), '待審核'))
                    log_action(reg_id, "註冊申請", f"{reg_squadron} {reg_title} 提出註冊申請")
                st.rerun()
            else: st.warning("請填寫所有欄位")
    st.stop()

# 攔截維護模式
if st.session_state.get('logged_in'):
    if MAINTENANCE_MODE and st.session_state.get('login_id') not in ALLOWED_ADMINS:
        st.session_state.clear()
        st.session_state['force_logout'] = True
        st.toast("🛠️ 系統已進入維護模式，您已被強制登出。")
        time.sleep(1.5)
        st.rerun()

# ==========================================
# 🎨 側邊欄渲染
# ==========================================
sq_list = st.session_state.get('base_sq_list', [str(st.session_state.get('squadron', '')).strip()])

with st.sidebar:
    st.markdown(f"### {'🧑‍✈️' if st.session_state.get('role') == 'L1' else '🎓'} {st.session_state.get('title', '')}")
    
    if st.session_state.get('role') == 'L1':
        if len(sq_list) > 1: 
            st.session_state['current_sq'] = st.selectbox("選擇中隊", sq_list, key="global_sq_selector", label_visibility="collapsed")
        else:
            st.session_state['current_sq'] = sq_list[0]
            st.markdown(f"**{st.session_state['current_sq']}**")
        menu_options = ["🏠 首頁", "👥 帳號管理", "📤 借閱審核", "📥 歸還審核", "💬 回報專區", "📊 準則現況", "🚗 車輛登載", "🔍 綜合查詢", "🗂️ 操作紀錄"]
        if str(st.session_state.get('squadron', '')).strip() == '大隊部': menu_options.insert(2, "⚙️ 系統管理")
    else:
        st.session_state['current_sq'] = st.session_state.get('squadron', '')
        st.markdown(f"**{st.session_state['current_sq']}**")
        menu_options = ["🏠 首頁", "📤 借閱準則", "🏷️ 序號登載", "📥 準則歸還", "💬 回報專區", "🔍 綜合查詢"]
        
    st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)
    menu = st.radio("隱藏標題", menu_options, label_visibility="collapsed")
    st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)
    
    if st.button("🚪 登出", use_container_width=True):
        st.session_state['logout_triggered'] = True
        st.rerun()

# 目標權限快取計算
target_sq = st.session_state.get('current_sq', str(st.session_state.get('squadron', '')).strip())
target_sq_list = get_target_sq_list(target_sq)

# 🛑 這裡不再執行全域的 conn = get_db_connection()
try:
        # ==========================================
        # 🏠 首頁模塊：精準連線重構版
        # ==========================================
        if menu in ["首頁", "🏠 首頁"]:
            st.header("🏠 首頁", help="""
:blue[**【🏠 首頁】**]
- :yellow[文書：檢視中隊待辦事項]  
:yellow[**【📝 待審核帳號】**]：申請帳號需審核數量
:yellow[**【📤 待借閱準則】**]：申請借閱需審核數量
:yellow[**【📤 待歸還準則】**]：申請歸還需審核數量
:yellow[**【🔴 借閱異常警示】**]：借閱準則未領取數量
- :yellow[訓員：檢視班隊持有準則現況]  
:blue[**【🔵申請中】**]：顯示準則狀態已申請借閱
:yellow[**【🟡已審核】**]：顯示準則狀態文書已審核
:green[**【🟢借閱中】**]：顯示準則狀態序號已登載
:red[**【🔴歸還中】**]：顯示準則狀況已申請歸還 """)
            
            # --- 幹部 L1 視角 ---
            if st.session_state.role == 'L1':
                target_sq = st.session_state.get('current_sq', '')
                st.markdown(f"**{st.session_state.title}** 長官好，以下為【{target_sq}】今日概況：")
                
                # 精準連線：只在計算 Metric 時開啟
                with get_db_connection() as conn:
                    with conn.cursor() as c:
                        c.execute("SELECT COUNT(*) FROM users WHERE status='待審核' AND squadron = ANY(%s)", (target_sq_list,))
                        pending_reg = c.fetchone()[0]
                        
                        c.execute("SELECT COUNT(*) FROM borrow_requests br JOIN users u ON br.login_id = u.login_id WHERE br.status='待審核' AND u.squadron = ANY(%s)", (target_sq_list,))
                        pending_bor = c.fetchone()[0]
                        
                        c.execute("SELECT COUNT(*) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='歸還中' AND u.squadron = ANY(%s)", (target_sq_list,))
                        pending_ret = c.fetchone()[0]
                        
                        c.execute("SELECT COUNT(*) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='少領異常' AND u.squadron = ANY(%s)", (target_sq_list,))
                        pending_abn = c.fetchone()[0]
                
                c_m1, c_m2, c_m3, c_m4 = st.columns(4)
                c_m1.metric("📝 待審核帳號", f"{pending_reg} 件")
                c_m2.metric("📥 待借閱準則", f"{pending_bor} 件")
                c_m3.metric("📤 待歸還準則", f"{pending_ret} 件")
                c_m4.metric("🔴 借閱異常警示", f"{pending_abn} 件")
                
            # --- 訓員 L2 視角 ---
            elif st.session_state.role == 'L2':
                st.markdown(f"**所屬單位：** {st.session_state.squadron} - {st.session_state.title}")
                if st.session_state.discharge_date:
                    d_date = datetime.strptime(str(st.session_state.discharge_date), '%Y-%m-%d').date()
                    today = datetime.now().date()
                    days_left = (d_date - today).days
                    if days_left < 0: st.error(f"🚨 已逾結訓日！請盡速歸還準則。")
                    elif days_left <= 3: st.warning(f"⚠️ 結訓倒數：{days_left} 天！")
                    else: st.info(f"📅 距離結訓日還有：{days_left} 天")

                st.markdown("#### 📦 借閱準則總覽")
                
                status_items = []
                # 精準連線：撈取個人準則清單
                with get_db_connection() as conn:
                    with conn.cursor() as c:
                        c.execute("SELECT book_name, SUM(quantity) FROM borrow_requests WHERE login_id=%s AND status='待審核' GROUP BY book_name", (st.session_state.login_id,))
                        for row in c.fetchall():
                            status_items.append({'book_name': row[0], 'qty': int(row[1]), 'status': '申請中'})
                            
                        c.execute("SELECT book_name, status, COUNT(id) FROM books WHERE owner_id=%s AND status IN ('保留待領取', '借閱中', '歸還中') GROUP BY book_name, status", (st.session_state.login_id,))
                        for row in c.fetchall():
                            status_items.append({'book_name': row[0], 'qty': int(row[2]), 'status': row[1]})

                if not status_items:
                    st.success("✨ 您目前沒有任何準則。")
                else:
                    df_items = apply_shadow_sort(pd.DataFrame(status_items))
                    for _, r in df_items.iterrows():
                        draw_status_card(r['book_name'], r['qty'], r['status'])
                            
            st.markdown("---")
            with st.expander("⚙️ 帳密設置", expanded=False):
                st.markdown("#### ⚙️ 個人設定")
                col_i, col_p = st.columns(2)
                with col_i: new_id = st.text_input("修改帳號", value=st.session_state.login_id, key="daily_id")
                with col_p: new_pwd = st.text_input("修改密碼", type="password", placeholder="若不修改請空白", key="daily_pw")
                
                if st.button("💾 儲存", key="save_daily_settings", type="primary"):
                    # 直接呼叫新的 db_transaction 引擎
                    with db_transaction(success_msg="✅ 設定已儲存！請重新登入...") as c:
                        uid = int(st.session_state.id)
                        final_id = new_id.strip() if new_id.strip() else st.session_state.login_id
                        
                        c.execute("SELECT COUNT(*) FROM users WHERE login_id=%s AND id!=%s", (final_id, uid))
                        if c.fetchone()[0] > 0: 
                            st.error("❌ 此帳號已被使用！")
                            st.stop()
                            
                        if new_pwd:
                            hashed_pwd = generate_password_hash(new_pwd)
                            pw_update = ", password=%s"
                            params = [final_id, hashed_pwd, st.session_state.title, uid]
                        else:
                            pw_update = ""
                            params = [final_id, st.session_state.title, uid]
                        
                        old_id = st.session_state.login_id
                        c.execute(f"UPDATE users SET login_id=%s{pw_update}, title=%s WHERE id=%s", tuple(params))
                        
                        if old_id != final_id:
                            # 批量更新關聯資料
                            c.execute("UPDATE books SET owner_id=%s WHERE owner_id=%s", (final_id, old_id))
                            c.execute("UPDATE borrow_requests SET login_id=%s WHERE login_id=%s", (final_id, old_id))
                            c.execute("UPDATE action_logs SET user_id=%s WHERE user_id=%s", (final_id, old_id))
                            c.execute("UPDATE vehicles SET account_id=%s WHERE account_id=%s", (final_id, old_id))
                            
                    import time; time.sleep(1); st.session_state.clear(); st.rerun()

        elif menu in ["車輛登載", "🚗 車輛登載"] and st.session_state.role == 'L1':
            st.header("🚗 車輛管制總表", help="由幹部統一集中管理所有車輛與停車格位置。")
            
            st.subheader("➕ 新增車輛")
            with st.form("add_vehicle_form", clear_on_submit=True):
                # 第一排：中隊、班隊、結訓日期 (已移除姓名)
                c1, c2, c3 = st.columns([3, 4, 3])
                with c1:
                    sq_options = ["學員一中隊", "學員二中隊", "學生一中隊", "學生二中隊"]
                    v_sq = st.selectbox("所屬中隊", sq_options)
                with c2:
                    v_unit = st.text_input("班隊", placeholder="例如：煙幕班115-1期")
                with c3:
                    v_date = st.date_input("結訓日期")

                # 第二排：車號、停車場、停車號碼
                c5, c6, c7 = st.columns(3)
                with c5:
                    v_plate = st.text_input("車號 (僅輸入數字)", placeholder="例如：1234")
                with c6:
                    lot_options = ["第一停車場", "第二停車場", "第三停車場", "二級廠"]
                    v_lot = st.selectbox("停車場位置", lot_options)
                with c7:
                    v_num = st.text_input("停車號碼", placeholder="例如：01")

                submit_v = st.form_submit_button("➕ 新增車輛", type="primary", use_container_width=True)
                if submit_v:
                    if not v_plate.strip():
                        st.warning("⚠️ 車號不可為空白！")
                    else:
                        # 🛡️ 資安修正：強制過濾，只保留數字字元
                        clean_plate = re.sub(r'[^0-9]', '', v_plate)
                        if not clean_plate:
                            st.warning("⚠️ 車號必須包含數字！")
                        else:
                            clean_unit = v_unit.strip()
                            clean_num = v_num.strip()
                            with db_transaction(success_msg=f"✅ 車輛 {clean_plate} 新增成功！") as c:
                                # 移除 owner_name 寫入
                                c.execute("INSERT INTO vehicles (account_id, plate_number, squadron, unit_title, parking_lot, parking_number, discharge_date) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                                          (st.session_state.login_id, clean_plate, v_sq, clean_unit, v_lot, clean_num, v_date))
                                # 👇 寫入操作紀錄
                                now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
                                          (now_time, st.session_state.login_id, "新增車輛", f"新增 {v_sq} {clean_unit} 車輛：{clean_plate}"))
                            st.session_state['refresh_vehicles'] = True 
                            st.rerun()

            st.markdown("---")
            st.subheader("📋 管制車輛清單")
            
            # 撈取全車輛表 (已移除 owner_name 抓取)
            if 'vehicle_data' not in st.session_state or st.session_state.get('refresh_vehicles', True):
                st.session_state['vehicle_data'] = pd.read_sql_query("""
                    SELECT id, squadron as 中隊, unit_title as 班隊, plate_number as 車號, parking_lot as 停車場, parking_number as 停車號碼, discharge_date as 結訓日期
                    FROM vehicles 
                    ORDER BY id DESC
                """, conn)
                st.session_state['refresh_vehicles'] = False 
            
            v_df = st.session_state['vehicle_data']

            @st.dialog("✏️ 編輯車輛資訊")
            def edit_vehicle_dialog(row):
                v_id = row['id']
                o_sq = row['中隊'] if pd.notna(row['中隊']) else "未登錄"
                o_unit = row['班隊'] if pd.notna(row['班隊']) else "未登錄"
                o_plate = row['車號']
                o_lot = row['停車場'] if pd.notna(row['停車場']) else "未登錄"
                o_num = row['停車號碼'] if pd.notna(row['停車號碼']) else "未登錄"
                
                if pd.notna(row['結訓日期']):
                    o_date = pd.to_datetime(row['結訓日期']).date()
                else:
                    o_date = datetime.now(timezone(timedelta(hours=8))).date()
                
                ec1, ec2 = st.columns(2)
                with ec1:
                    sq_opts = ["學員一中隊", "學員二中隊", "學生一中隊", "學生二中隊"]
                    new_sq = st.selectbox("所屬中隊", sq_opts, index=sq_opts.index(o_sq) if o_sq in sq_opts else 0, key=f"d_sq_{v_id}")
                with ec2:
                    new_unit = st.text_input("班隊", value=o_unit, key=f"d_unit_{v_id}")
                    
                ec4, ec5 = st.columns(2)
                with ec4:
                    new_plate = st.text_input("🚘 車號 (僅數字)", value=o_plate, key=f"d_plate_{v_id}")
                with ec5:
                    new_date = st.date_input("📅 結訓日期", value=o_date, key=f"d_date_{v_id}")

                ec6, ec7 = st.columns(2)
                with ec6:
                    lot_opts = ["第一停車場", "第二停車場", "第三停車場", "二級廠"] 
                    l_idx = lot_opts.index(o_lot) if o_lot in lot_opts else 0
                    new_lot = st.selectbox("停車場位置", lot_opts, index=l_idx, key=f"d_lot_{v_id}")
                with ec7:
                    new_num = st.text_input("停車號碼", value=o_num, key=f"d_num_{v_id}")
                    
                st.write("") 
                col_save, col_del = st.columns(2)
                with col_save:
                    if st.button("💾 儲存修改", key=f"d_save_{v_id}", type="primary", use_container_width=True):
                        clean_unit = str(new_unit).strip()
                        # 🛡️ 資安修正：強制過濾，只保留數字字元
                        clean_plate = re.sub(r'[^0-9]', '', str(new_plate))
                        clean_num = str(new_num).strip()
                        
                        if not clean_plate:
                            st.warning("⚠️ 車號必須包含數字！")
                        elif clean_plate != o_plate or new_sq != o_sq or clean_unit != o_unit or new_lot != o_lot or clean_num != o_num or new_date != o_date:
                            with db_transaction(success_msg="✅ 車輛資料更新成功！") as c:
                                c.execute("UPDATE vehicles SET plate_number=%s, squadron=%s, unit_title=%s, parking_lot=%s, parking_number=%s, discharge_date=%s WHERE id=%s", 
                                          (clean_plate, new_sq, clean_unit, new_lot, clean_num, new_date, v_id))
                                # 👇 寫入操作紀錄
                                now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
                                          (now_time, st.session_state.login_id, "編輯車輛", f"修改車輛資訊：{o_plate} ➔ {clean_plate}"))
                            st.session_state['refresh_vehicles'] = True 
                            st.rerun()
                        else:
                            st.warning("⚠️ 資料沒有更動。")
                with col_del:        
                    if st.button("🗑️ 刪除", key=f"d_del_{v_id}", use_container_width=True):
                        with db_transaction(success_msg="🗑️ 車輛已刪除！") as c:
                            c.execute("DELETE FROM vehicles WHERE id=%s", (v_id,))
                            # 👇 寫入操作紀錄
                            now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                            c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
                                      (now_time, st.session_state.login_id, "刪除車輛", f"刪除車號：{o_plate}"))
                        st.session_state['refresh_vehicles'] = True 
                        st.rerun()

            if v_df.empty: 
                st.info("💡 目前尚無登載任何車輛。")
            else:
                v_df['中隊'] = v_df['中隊'].fillna("未登錄").replace("", "未登錄")
                v_df['班隊'] = v_df['班隊'].fillna("未登錄").replace("", "未登錄")

                for sq_name, sq_df in v_df.groupby('中隊', dropna=False):
                    with st.expander(f"🏢 {sq_name} (共 {len(sq_df)} 輛)"):
                        for unit_name, unit_df in sq_df.groupby('班隊', dropna=False):
                            with st.expander(f"🔽 {unit_name} (共 {len(unit_df)} 輛)"):
                                for idx, row in unit_df.iterrows():
                                    with st.container(border=True):
                                        o_plate = row['車號']
                                        o_lot = row['停車場'] if pd.notna(row['停車場']) else "未登錄"
                                        o_num = row['停車號碼'] if pd.notna(row['停車號碼']) else "未登錄"
                                        o_date = row['結訓日期'] if pd.notna(row['結訓日期']) else "未登錄"

                                        col_info, col_btn = st.columns([8.5, 1.5])
                                        with col_info:
                                            # 卡片隱藏姓名，僅展示車號
                                            st.markdown(f"🚘 **車號: {o_plate}**")
                                            st.markdown(f"<span style='color: #a0a0a0; font-size: 14px;'>📍 {o_lot} (車位號: {o_num})<br>📅 結訓日: {o_date}</span>", unsafe_allow_html=True)
                                        with col_btn:
                                            st.write("") 
                                            if st.button("✏️ 編輯", key=f"btn_edit_{row['id']}", use_container_width=True):
                                                edit_vehicle_dialog(row)
            
        elif menu in ["序號登載", "🏷️ 序號登載"] and st.session_state.role == 'L2':
            st.header("🏷️ 序號登載與校正", help="""
:blue[**【🏷️ 序號登載與校正】**]  
:yellow[**【登載】**]：在`   `內登載序號，用`,`隔開  
:yellow[**【校正】**]：點擊`序號1,序號2`校正序號，用`,`隔開  
:yellow[**【☑️借閱異常】**]:借閱與領回數量不符時    
在`   `內登載領回準則序號後，勾選☑️借閱異常  
:yellow[**【💾 儲存】**]：登載好序號後，按下 :red[**💾 儲存**]""")
            bk_df = pd.read_sql_query("SELECT id, book_name, serial_number, status FROM books WHERE owner_id=%s AND status IN ('保留待領取', '借閱中')", conn, params=(st.session_state.login_id,))

            if bk_df.empty:
                st.success("✨ 您目前沒有需要登載或校正的準則！")
            else:
                with st.form("serial_entry_form"):
                    form_data = {}
                    bk_df = apply_shadow_sort(bk_df)
                    grouped = bk_df.groupby(['book_name', 'status'], sort=False)
                    
                    for (b_name, st_val), b_rows in grouped:
                        qty = len(b_rows)
                        if st_val == '保留待領取':
                            b_ids = b_rows['id'].tolist()
                            with st.container(border=True):                                                                
                                st.markdown(f"""
                                    <div class="single-line-text" style="font-size: clamp(14px, 4vw, 18px); font-weight: bold; color: #ffb84d; margin-bottom: 2px;">🟡 {b_name}</div>
                                    <div style="font-size: 14px; color: #ffb84d; margin-bottom: 8px;"><b>(共 {qty} 本)</b> 登載序號用 , 隔開</div>
                                """, unsafe_allow_html=True)
                                user_input = st.text_input(f"隱藏標題_{b_name}_p", label_visibility="collapsed", key=f"p_{b_name}")
                                abnormal = st.checkbox(f"☑️借閱異常：借閱與領回數量不符時勾選。", key=f"abn_{b_name}")
                                form_data[f"p_{b_name}"] = {'type': 'pending', 'ids': b_ids, 'input': user_input, 'abnormal': abnormal, 'b_name': b_name}

                        elif st_val == '借閱中':
                            current_s = [str(r['serial_number']).strip() for _, r in b_rows.iterrows() if pd.notna(r['serial_number'])]
                            with st.container(border=True):                                                                
                                st.markdown(f"""
                                    <div class="single-line-text" style="font-size: clamp(14px, 4vw, 18px); font-weight: bold; color: #4CAF50; margin-bottom: 2px;">🟢 {b_name}</div>
                                    <div style="font-size: 14px; color: #4CAF50; margin-bottom: 8px;"><b>(共 {qty} 本)</b> 序號用 , 隔開</div>
                                """, unsafe_allow_html=True)
                                user_input = st.text_input(f"隱藏標題_{b_name}_c", value=", ".join(current_s), label_visibility="collapsed", key=f"c_{b_name}")
                                form_data[f"c_{b_name}"] = {'type': 'correct', 'rows': b_rows.to_dict('records'), 'input': user_input, 'b_name': b_name}

                    st.markdown("---")
                    if st.form_submit_button("💾 儲存", type="primary", use_container_width=True):
                        success_cnt = 0
                        with db_transaction(success_msg="✅ 序號儲存成功！") as c:
                            for key, data in form_data.items():
                                # 💡 終極防呆：把空白、全形逗號、頓號、換行全部自動替換成標準逗號
                                cleaned_input = re.sub(r'[ \t\n，、]+', ',', data['input'])
                                raw_input = [s.strip() for s in cleaned_input.split(',') if s.strip()]
                                b_name = data['b_name']
                                if data['type'] == 'pending':
                                    p_ids = data['ids']
                                    if len(raw_input) > len(p_ids):
                                        st.error(f"❌ 【{b_name}】輸入序號數量 ({len(raw_input)}) 超過待領取額度 ({len(p_ids)})！")
                                        st.session_state['db_locked'] = False
                                        st.stop()
                                    for i in range(len(p_ids)):
                                        b_id = p_ids[i]
                                        if i < len(raw_input):
                                            new_s = raw_input[i]
                                            # 👇 強化防禦：多抓取 book_name 進行核對，防止器、車調包
                                            c.execute("SELECT id, status, owner_id, book_name FROM books WHERE serial_number=%s", (new_s,))
                                            check = c.fetchone()
                                            
                                            if not check:
                                                # 資料庫還沒有這個真實序號，直接覆寫虛擬序號
                                                c.execute("UPDATE books SET serial_number=%s, status='借閱中' WHERE id=%s", (new_s, b_id))
                                                success_cnt += 1
                                            else:
                                                # 取出多抓的 book_name
                                                target_id, target_status, target_owner, target_book_name = check
                                                
                                                # 👇 第一道防線：如果書名不符，直接亮紅燈擋下，不執行後續交換
                                                if target_book_name != b_name:
                                                    st.error(f"❌ 序號衝突！序號 `{new_s}` 目前登記在【{target_book_name}】名下，禁止跨種類登載至【{b_name}】。")
                                                    st.session_state['db_locked'] = False
                                                    st.stop()
                                                
                                                # 👇 以下保留您原本完美的交換邏輯 (只有書名一樣才會執行到這裡)
                                                if target_id == b_id:
                                                    # 剛好就是系統預發給自己的這本
                                                    c.execute("UPDATE books SET status='借閱中' WHERE id=%s", (b_id,))
                                                    success_cnt += 1
                                                    
                                                elif target_status == '在庫':
                                                    # 一般交換：跟庫房換
                                                    c.execute(f"UPDATE books SET status='借閱中', owner_id='{st.session_state.login_id}' WHERE id={target_id}")
                                                    c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id={b_id}")
                                                    success_cnt += 1
                                                    
                                                elif target_status == '保留待領取':
                                                    # 🚀 超級交換：這本書被系統預發給別人了！
                                                    # 把這本實體書搶過來給自己 (借閱中)
                                                    c.execute(f"UPDATE books SET status='借閱中', owner_id='{st.session_state.login_id}' WHERE id={target_id}")
                                                    # 把自己的「虛擬額度 (b_id)」賠給那個無辜的 target_owner
                                                    c.execute("UPDATE books SET owner_id=%s WHERE id=%s", (target_owner, b_id))
                                                    success_cnt += 1
                                                    
                                                else:
                                                    # 書真的已經被別人確實登載借走了
                                                    st.error(f"❌ 【{b_name}】序號 {new_s} 已被 {target_owner} 借出！")
                                                    st.session_state['db_locked'] = False
                                                    st.stop()
                                    else:
                                            # 👇 新增：如果訓員輸入的序號數量少於應領數量，且勾選了「借閱異常」
                                            if data.get('abnormal') == True:
                                                # 將剩下的額度狀態改為「少領異常」
                                                c.execute("UPDATE books SET status='少領異常' WHERE id=%s", (b_id,))
                                                success_cnt += 1
                                                # 寫入操作紀錄，讓幹部知道是誰回報的
                                                now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
                                                          (now_time, st.session_state.login_id, "回報借閱異常", f"回報 {b_name} 數量不足，轉入異常警示"))
                        if success_cnt > 0:
                            st.rerun()
                        else:
                            st.warning("⚠️ 尚未輸入或修改任何序號。")

        elif menu in ["借閱準則", "📤 借閱準則"] and st.session_state.role == 'L2':
            st.header("📤 借閱準則申請", help="""
:blue[**【📤 借閱準則申請】**]  
:yellow[**【🎯 設置借閱數量】**]:在`   `內輸入班隊人數  
:yellow[**【📚 選擇準則】**]：在`   `內輸入需借閱的準則  
:yellow[**【➕ 加入清單】**]：按➕加入清單將借閱準則加入  
:yellow[**【借閱數量】**]：在`   `內按➕或➖調整借閱數量  
:yellow[**【🚀提交申請】**]：按:red[🚀提交申請]提交申請""")
            c = conn.cursor()
            c.execute("SELECT book_name, COUNT(id) FROM books WHERE status='在庫' GROUP BY book_name")
            available_books = c.fetchall()
            
            if not available_books:
                st.warning("庫房無可借閱的準則。")
            else:
                st.subheader("🎯 設置借閱數量")
                default_req_qty = st.number_input("請輸入欲借閱的數量 (例如：貴班隊人數)", min_value=1, value=1)
                st.markdown("---")
                
                # 🛒 2. 導入「購物車」與「選單重置計數器」
                if 'cart' not in st.session_state:
                    st.session_state.cart = {}
                if 'clear_key' not in st.session_state:
                    st.session_state.clear_key = 0

                st.subheader("📚 選擇準則")
                book_options = [f"{b[0]} (庫存: {b[1]}本)" for b in available_books]
                
                # ⚡ 極速單選加入流 (極簡動態 Key 版)
                col_sel, col_add = st.columns([7, 3])
                
                # 🔑 注意這裡的 key 加上了 st.session_state.clear_key
                selected_book = col_sel.selectbox("選擇準則", book_options, index=None, placeholder="🔍 請輸入關鍵字搜尋準則...", label_visibility="collapsed", key=f"book_selector_{st.session_state.clear_key}")
                
                if col_add.button("➕ 加入清單", type="secondary", use_container_width=True):
                    if not selected_book:
                        st.warning("⚠️ 請先輸入或選擇要借閱的準則！")
                    else:
                        b_name, stock_info = selected_book.split(" (庫存: ")
                        max_qty = int(stock_info.replace("本)", ""))
                        
                        if b_name not in st.session_state.cart:
                            st.session_state.cart[b_name] = {'qty': min(default_req_qty, max_qty), 'max_qty': max_qty}
                            st.toast(f"✅ 已加入：{b_name}")
                        else:
                            st.toast(f"⚠️ {b_name} 已在清單中！")
                            
                        # 🎯 魔法在這裡：將 clear_key + 1，下次重整時就會是一個全新的空白選單！
                        st.session_state.clear_key += 1
                        st.rerun()

                # 完美雙行卡片排版渲染購物車
                if st.session_state.cart:
                    st.markdown("#### 🛒 借閱清單")
                    for b_name, data in list(st.session_state.cart.items()):
                        with st.container(border=True):
                            # 第一行：名稱 (自動縮略)
                            st.markdown(f"<div class='single-line-text' style='font-size: 16px; font-weight: bold; margin-bottom: 8px;' title='幫助說明：{b_name}'>📘 {b_name}</div>", unsafe_allow_html=True)
                            
                            # 第二行：借閱數量與移除按鈕
                            # 💡 修正點：只保留 3 個欄位，並重新分配排版比例 (3 : 4 : 3)
                            c1, c2, c3 = st.columns([3, 4, 3])
                            
                            with c1:
                                st.markdown("<div style='margin-top: 8px; font-size: 14px; color: #475569;'>:red[借閱數量：]</div>", unsafe_allow_html=True)
                            with c2:
                                new_qty = st.number_input("qty", value=data['qty'], min_value=1, max_value=data['max_qty'], key=f"cart_inp_{b_name}", label_visibility="collapsed")
                                if new_qty != data['qty']:
                                    st.session_state.cart[b_name]['qty'] = new_qty
                                    st.rerun()
                            with c3:
                                if st.button("🗑️ 移除", key=f"cart_rm_{b_name}", use_container_width=True):
                                    del st.session_state.cart[b_name]
                                    st.rerun()

                    
                    st.markdown("---")
                    # 一次性打包送出邏輯
                    if st.button("🚀 提交申請", type="primary", use_container_width=True):
                        warnings_list = []
                        borrow_requests = {}
                        
                        for b_name, data in st.session_state.cart.items():
                            borrow_requests[b_name] = data['qty']
                            c.execute("SELECT COUNT(*) FROM books WHERE owner_id=%s AND book_name=%s AND status!='在庫'", (st.session_state.login_id, b_name))
                            owned_count = int(c.fetchone()[0])
                            
                            c.execute("SELECT SUM(quantity) FROM borrow_requests WHERE login_id=%s AND book_name=%s AND status='待審核'", (st.session_state.login_id, b_name))
                            pending_req = c.fetchone()[0]
                            pending_count = int(pending_req) if pending_req else 0
                            
                            if (owned_count + pending_count) > 0:
                                warn_msg = f"【{b_name}】已持有: {owned_count} 本 / 審核中: {pending_count} 本"
                                warnings_list.append(warn_msg)
                        
                        if warnings_list:
                            duplicate_borrow_dialog(borrow_requests, warnings_list)
                        else:
                            with db_transaction(success_msg="✅ 申請已送出！請等待幹部審核。") as c_trans:
                                now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                for b_name, qty in borrow_requests.items():
                                    c_trans.execute("INSERT INTO borrow_requests (login_id, unit, book_name, quantity, status) VALUES (%s, %s, %s, %s, %s)", 
                                              (st.session_state.login_id, st.session_state.title, b_name, qty, '待審核'))
                                    c_trans.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)",
                                              (now_time, st.session_state.login_id, "申請借閱", f"申請 {b_name} {qty} 本"))
                            st.session_state.cart = {} # 清空購物車
                            st.rerun()

        elif menu in ["💬 回報專區", "回報專區"] and st.session_state.role == 'L2':
            st.header("💬 Line 借還書回報", help="自動產生個人借還書及庫存清點文字，方便快速回報。")
            tabs = st.tabs(["🚚 借還書回報", "📱 準則清點回報"])
            with tabs[0]:
                st.subheader("🚚 借還書回報", help="請點擊下方生成清單，並點擊黑框右上角的「📋」完成複製！")
                if st.button("🚀 生成借還書清單", type="primary"):
                    borrow_items = []
                    return_items = []
                    with conn.cursor() as c:
                        c.execute("SELECT book_name, SUM(quantity) FROM borrow_requests WHERE login_id=%s AND status='待審核' GROUP BY book_name", (st.session_state.login_id,))
                        for r in c.fetchall(): borrow_items.append({'book_name': r[0], 'qty': int(r[1]), 'status': '申請中'})

                        c.execute("SELECT book_name, COUNT(id) FROM books WHERE owner_id=%s AND status='保留待領取' GROUP BY book_name", (st.session_state.login_id,))
                        for r in c.fetchall(): borrow_items.append({'book_name': r[0], 'qty': int(r[1]), 'status': '已審核'})

                        c.execute("SELECT book_name, COUNT(id) FROM books WHERE owner_id=%s AND status='歸還中' GROUP BY book_name", (st.session_state.login_id,))
                        for r in c.fetchall(): return_items.append({'book_name': r[0], 'qty': int(r[1]), 'status': '歸還中'})

                    msg = f"班隊：{st.session_state.title}\n借還書清單：\n\n"
                    
                    borrow_msg = ""
                    if borrow_items:
                        borrow_msg += "【借閱書目】：\n"
                        df_b = apply_shadow_sort(pd.DataFrame(borrow_items))
                        for _, r in df_b.iterrows(): borrow_msg += f"{r['book_name']} * {r['qty']} ({r['status']})\n"
                    
                    return_msg = ""
                    if return_items:
                        return_msg += "【歸還書目】：\n"
                        df_r = apply_shadow_sort(pd.DataFrame(return_items))
                        for _, r in df_r.iterrows(): return_msg += f"{r['book_name']} * {r['qty']} (歸還中)\n"
                    
                    if borrow_msg: msg += borrow_msg + "\n"
                    if return_msg: msg += return_msg
                    if not borrow_msg and not return_msg: msg += "無借還書清單\n"
                        
                    st.code(msg.strip(), language="text")
                    
            with tabs[1]:
                st.subheader("📱 準則清點回報")
                if st.button("🚀 生成清點報表", type="primary"):
                    inv_items = []
                    with conn.cursor() as c:
                        c.execute("SELECT book_name, status, COUNT(id) FROM books WHERE owner_id=%s AND status IN ('借閱中', '歸還中') GROUP BY book_name, status", (st.session_state.login_id,))
                        for r in c.fetchall(): inv_items.append({'book_name': r[0], 'status': r[1], 'qty': int(r[2])})
                        
                    msg = f"班隊：{st.session_state.title}\n準則清點：\n\n"
                    if not inv_items: msg += "無\n"
                    else:
                        df_inv = apply_shadow_sort(pd.DataFrame(inv_items))
                        for _, r in df_inv.iterrows(): msg += f"{r['book_name']} * {r['qty']} ({r['status']})\n"
                    st.code(msg.strip(), language="text")

        elif menu in ["準則歸還", "📥 準則歸還"] and st.session_state.role == 'L2':
            st.header("📤 準則歸還", help="勾選準則標題旁的「☑️ 全數歸還此項」即可將該類準則全數歸還。\n\n【部分歸還】：展開個別序號清單，單獨勾選要歸還的序號。")
            books_df = pd.read_sql_query("SELECT id, book_name as 書名, serial_number as 序號 FROM books WHERE owner_id=%s AND status='借閱中'", conn, params=(st.session_state.login_id,))
            if not books_df.empty:
                if 'l2_partial_return_memory' not in st.session_state: st.session_state['l2_partial_return_memory'] = {}
                for b_name in books_df['書名'].unique():
                    editor_key = f"return_editor_{b_name}"
                    if editor_key in st.session_state:
                        edits = st.session_state[editor_key].get("edited_rows", {})
                        temp_df = books_df[books_df['書名'] == b_name].reset_index(drop=True)
                        for r_idx_str, edit_dict in edits.items():
                            if "勾選歸還" in edit_dict:
                                r_idx = int(r_idx_str)
                                if r_idx < len(temp_df): st.session_state['l2_partial_return_memory'][temp_df.at[r_idx, 'id']] = edit_dict["勾選歸還"]

                category_checks = {} 
                edited_return_dfs = {}
                for b_name in books_df['書名'].unique():
                    b_df = books_df[books_df['書名'] == b_name].reset_index(drop=True)
                    qty = len(b_df)
                    st.markdown(f"""<div class="single-line-text" style="font-size: 18px; font-weight: bold; color: #4CAF50; margin-bottom: 10px;">🟢 {b_name}</div>""", unsafe_allow_html=True)
                    col_chk, col_exp = st.columns([2.5, 7.5])
                    with col_chk: category_checks[b_name] = st.checkbox(f"☑️ 全數歸還 ({qty}本)", key=f"all_ret_{b_name}")
                    with col_exp:
                        with st.expander(f"🔽 展開個別序號"):
                            if category_checks[b_name]:
                                # 🛡️ 4. 批次操作的 UX 減壓：外面打勾，裡面直接鎖死給神級提示
                                st.success(f"✨ 已選擇全數歸還！送出後將一併歸還這 {qty} 本準則。")
                                edited_return_dfs[b_name] = None 
                            else:
                                # 🛡️ 4. 批次操作的 UX 減壓：預設全部打好勾 True！
                                initial_checks = [st.session_state['l2_partial_return_memory'].get(row['id'], False) for _, row in b_df.iterrows()]
                                b_df.insert(0, "勾選歸還", initial_checks)
                                edited_return_dfs[b_name] = st.data_editor(b_df, hide_index=True, disabled=["id", "書名", "序號"], width='stretch', column_config={"id": None, "書名": None}, key=f"return_editor_{b_name}")
                st.markdown("---") 
                if st.button("📤 送出目前的勾選項目", type="primary", use_container_width=True):
                    selected_ids = []
                    for b_name in books_df['書名'].unique():
                        if category_checks[b_name]:
                            selected_ids.extend(books_df[books_df['書名'] == b_name]["id"].tolist())
                        elif edited_return_dfs[b_name] is not None:
                            edited_df = edited_return_dfs[b_name]
                            selected_ids.extend(edited_df[edited_df["勾選歸還"] == True]["id"].tolist())
                    
                    if selected_ids:
                        selected_ids = list(set(selected_ids)) 
                        id_list_str = ','.join(map(str, selected_ids))
                        with db_transaction(success_msg=f"✅ 已送出 {len(selected_ids)} 本歸還申請！等待幹部審核。") as c:
                            c.execute(f"SELECT book_name, COUNT(id) FROM books WHERE id IN ({id_list_str}) GROUP BY book_name")
                            return_details = c.fetchall()
                            c.execute(f"UPDATE books SET status='歸還中' WHERE id IN ({id_list_str})")
                            now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                            for b_name, qty in return_details:
                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "申請歸還", f"申請 {st.session_state.title} 歸還 {b_name} {qty} 本"))
                        if 'l2_partial_return_memory' in st.session_state: del st.session_state['l2_partial_return_memory']
                        st.rerun()
                    else:
                        st.warning("⚠️ 您尚未勾選任何需要歸還的準則！")
            else:
                st.success("✨ 您名下目前沒有需要歸還的準則！")

        elif menu == "⚙️ 系統管理" and st.session_state.role == 'L1' and str(st.session_state.squadron).strip() == '大隊部':
            st.header("👑 系統管理", help="""
:blue[**【👑 系統管理】**]  
:yellow[**【➕ 新增人員】**]:生成配發帳號  
:yellow[**【⚙️ 管理帳號】**]：修改現有帳號資訊 """)
            # 👇 --- 新增這個對話框函數 --- 👇
            @st.dialog("⚙️ 編輯與管理帳號")
            def edit_user_dialog(user_row):
                uid = user_row['id']
                st.markdown(f"**正在編輯：** `{user_row['title']}` ({user_row['login_id']})")
                
                col_edit1, col_edit2 = st.columns(2)
                with col_edit1:
                    new_login = st.text_input("帳號", value=user_row['login_id'], key=f"d_id_{uid}")
                    new_pwd = st.text_input("密碼 (若不修改請留空)", type="password", placeholder="輸入新密碼", key=f"d_pw_{uid}")
                    role_opts = ["L1", "L2"]
                    new_role = st.selectbox("身分權限", role_opts, index=role_opts.index(user_row['role']) if user_row['role'] in role_opts else 0, key=f"d_ro_{uid}")
                with col_edit2:
                    new_sq = st.text_input("中隊", value=user_row['squadron'], key=f"d_sq_{uid}")
                    new_ti = st.text_input("職務/班隊", value=user_row['title'], key=f"d_ti_{uid}")
                    status_opts = ["啟用", "待審核", "結訓凍結", "停權"]
                    new_st = st.selectbox("狀態", status_opts, index=status_opts.index(user_row['status']) if user_row['status'] in status_opts else 0, key=f"d_st_{uid}")
                
                st.markdown("---")
                col_save, col_del = st.columns(2)
                with col_save:
                    if st.button("💾 儲存修改", key=f"d_s_{uid}", type="primary", use_container_width=True):
                        with db_transaction(success_msg="✅ 更新成功！") as c:
                            if new_pwd:
                                c.execute("""UPDATE users SET login_id=%s, password=%s, role=%s, squadron=%s, title=%s, status=%s WHERE id=%s""", (new_login, generate_password_hash(new_pwd), new_role, new_sq, new_ti, new_st, uid))
                            else:
                                c.execute("""UPDATE users SET login_id=%s, role=%s, squadron=%s, title=%s, status=%s WHERE id=%s""", (new_login, new_role, new_sq, new_ti, new_st, uid))
                            # 👇 寫入操作紀錄
                            now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                            c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
                                      (now_time, st.session_state.login_id, "編輯帳號", f"修改 {new_login} ({new_ti}) 權限與狀態"))
                        st.rerun()
                with col_del:
                    # 改用 Checkbox 進行防呆確認，避免呼叫第二層 Dialog
                    confirm_delete = st.checkbox("⚠️ 勾選以確認刪除", key=f"chk_del_{uid}")
                    
                    if st.button("🗑️ 徹底刪除", key=f"d_d_{uid}", use_container_width=True, disabled=not confirm_delete, type="primary" if confirm_delete else "secondary"):
                        with db_transaction(success_msg="🗑️ 帳號已永久刪除！") as c:
                            c.execute("SELECT login_id FROM users WHERE id=%s", (uid,))
                            user_res = c.fetchone()
                            if user_res:
                                login_id = user_res[0]
                                c.execute("SELECT COUNT(*) FROM books WHERE owner_id=%s AND status != '在庫'", (login_id,))
                                if c.fetchone()[0] > 0:
                                    st.error("❌ 刪除失敗！該班隊名下還有尚未歸還的準則，系統拒絕刪除！")
                                    st.session_state['db_locked'] = False
                                    st.stop()
                            
                            c.execute("DELETE FROM users WHERE id=%s", (uid,))
                        st.rerun()
            with st.expander("➕ 新增人員", expanded=False):
                st.markdown("#### 📝 配發帳號")
                col1, col2, col3 = st.columns(3)
                with col1:
                    add_role = st.selectbox("身分", ["L1 (幹部)", "L2 (訓員)"], key="add_role")
                    add_sq = st.selectbox("中隊", ["大隊部", "學員一中隊", "學員二中隊", "學生一中隊", "學生二中隊", "聯合中隊①", "聯合中隊②"], key="add_sq")
                with col2:
                    add_title = st.text_input("職務 / 班隊全銜", placeholder="例如：中隊長 或 煙幕班115-1期", key="add_title")
                    add_id = st.text_input("登入帳號", key="add_id")
                with col3:
                    add_pw = st.text_input("登入密碼", key="add_pw")
                    add_status = st.selectbox("初始狀態", ["啟用", "待審核", "結訓凍結"], key="add_status")
                    
                if st.button("🚀 立即建立帳號", type="primary"):
                    if add_title and add_id and add_pw:
                        r_val = "L1" if "L1" in add_role else "L2"
                        with db_transaction(success_msg=f"✅ 成功建立 {r_val} 帳號：{add_title}！") as c:
                            c.execute("SELECT COUNT(*) FROM users WHERE login_id=%s", (add_id,))
                            if c.fetchone()[0] > 0: 
                                st.error("❌ 此帳號已被使用！請更換帳號。")
                                st.session_state['db_locked'] = False
                                st.stop()
                            hashed_pw = generate_password_hash(add_pw)
                            c.execute("INSERT INTO users (login_id, password, role, squadron, title, status) VALUES (%s,%s,%s,%s,%s,%s)", (add_id, hashed_pw, r_val, add_sq, add_title, add_status))
                            # 👇 寫入操作紀錄
                            now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                            c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
                                      (now_time, st.session_state.login_id, "配發帳號", f"建立新帳號：{add_id} ({add_title})"))
                        st.rerun()
                    else: st.warning("⚠️ 請填寫完整資料 (職務/帳號/密碼不可為空)！")
            
            st.markdown("---")
            all_users = pd.read_sql_query("SELECT id, login_id, password, role, squadron, title, status FROM users ORDER BY id", conn)
            squadrons = [s for s in all_users['squadron'].unique() if pd.notna(s) and str(s).strip() != ""]
            for sq in squadrons:
                sq_df = all_users[all_users['squadron'] == sq].copy()
                with st.expander(f"🔽 {sq} (共 {len(sq_df)} 個帳號)"):
                    sq_df['display_group'] = sq_df.apply(lambda x: "訓員" if x['role'] == 'L2' else str(x['title']), axis=1)
                    groups = sq_df['display_group'].unique()
                    if len(groups) > 0:
                        tabs = st.tabs([f"🎖️ {g} ({len(sq_df[sq_df['display_group']==g])}個)" for g in groups])
                        for i, g in enumerate(groups):
                            with tabs[i]:
                                g_df = sq_df[sq_df['display_group'] == g]
                                for _, row in g_df.iterrows():
                                    uid = row['id']
                                    # 🏭 3. 擴建「UI 卡片工廠」 (大幅瘦身版：移除原本厚重的 expander)
                                    with st.container(border=True):
                                        safe_title = html.escape(str(row['title']))
                                        safe_login_id = html.escape(str(row['login_id']))
                                        st.markdown(f"""
                                        <div style="padding: 10px; background-color: rgba(255,255,255,0.05); border-radius: 8px; margin-bottom: 8px;">
                                            <div style="font-size: 16px; font-weight: bold; margin-bottom: 4px;">👤 {row['title']} <span style="font-size: 12px; color: #a0a0a0;">({row['role']})</span></div>
                                            <div style="font-size: 14px; color: #d0d0d0;">🆔 帳號: <code>{row['login_id']}</code> &nbsp; | &nbsp; 🔑 密碼: <code>********</code></div>
                                            <div style="font-size: 14px; margin-top: 4px;">{'🟢' if row['status']=='啟用' else '🔴'} 狀態: <strong>{row['status']}</strong></div>
                                        </div>
                                        """, unsafe_allow_html=True)
                                        
                                        # 🎯 魔法在這裡：將 8 個元件壓縮成 1 個按鈕，點擊才載入！
                                        if st.button("⚙️ 管理此帳號", key=f"mgr_{uid}", use_container_width=True):
                                            edit_user_dialog(row)
                                                        
            st.subheader("📥 準則同步",help="""
:blue[**【📥 準則同步】**]  
:yellow[**【🔄 更新CSV檔】**]:更新準則csv檔同步準則""")
            if st.button("🔄 更新CSV檔", type="primary", use_container_width=True):
                if CSV_FILE and os.path.exists(CSV_FILE):
                    try: df_books = pd.read_csv(CSV_FILE, encoding='big5')
                    except UnicodeDecodeError: df_books = pd.read_csv(CSV_FILE, encoding='utf-8')
                    insert_count, skip_count = 0, 0
                    
                    with db_transaction() as c:
                        for index, row in df_books.iterrows():
                            if '書刊名稱' in row and pd.notna(row['書刊名稱']):
                                raw_title = str(row['書刊名稱']).strip()
                                pub_date = ""
                                if '出版日期' in row and pd.notna(row['出版日期']):
                                    raw_date = str(row['出版日期']).strip()
                                    if raw_date.endswith('.0'): raw_date = raw_date[:-2]
                                    pub_date = raw_date
                                book_title = f"{raw_title} [{pub_date}]" if pub_date else raw_title
                                qty = int(row['數量']) if '數量' in row and pd.notna(row['數量']) else int(row.get('化訓準則館', 1))
                                for i in range(1, qty + 1):
                                    serial = f"{book_title}-{i:03d}"
                                    c.execute("SELECT id FROM books WHERE serial_number=%s", (serial,))
                                    if not c.fetchone():
                                        c.execute("INSERT INTO books (book_name, serial_number, owner_id, status) VALUES (%s, %s, %s, %s)", (book_title, serial, '在庫', '在庫'))
                                        insert_count += 1
                                    else: skip_count += 1
                    
                    st.success(f"✅ 同步完成！成功新增了 {insert_count} 本，略過了 {skip_count} 本。")
                    log_action("SYSTEM_L1", "CSV 擴充同步", f"新增了 {insert_count} 本準則")
                else: st.error("❌ 系統找不到 CSV 檔案！")
                    
            st.markdown("---")
            st.subheader("🛠️ 系統除錯", help="""
:blue[**【🛠️ 系統除錯】**]  
:yellow[**【🚨 將此帳號除錯】**]:將此帳號所有的準則歸還""")
            with st.expander("展開除錯工具"):
                st.subheader("1. 帳號除錯 (強制退庫)")
                ghost_id = st.text_input("輸入要退庫的帳號", key="ghost_id_input")
                if st.button("🚨 將此帳號強制退庫", type="primary"):
                    if ghost_id.strip():
                        force_return_dialog(ghost_id)
                    else: st.warning("請先輸入帳號！")
                
                st.markdown("---")
                st.subheader("2. 序號重置 (修正打錯字)")
                reset_sn = st.text_input("輸入要重置的「真實序號」", placeholder="例如：055510", key="reset_sn_input")
                if st.button("♻️ 重置為虛擬序號", type="primary"):
                    if reset_sn.strip():
                        with db_transaction() as c:
                            # 檢查序號是否存在
                            c.execute("SELECT id, book_name FROM books WHERE serial_number=%s", (reset_sn.strip(),))
                            res = c.fetchone()
                            if res:
                                bid, bname = res
                                # 👇 生成唯一的虛擬序號 (書名-RE-ID)，保證不會跟現有的 -001 衝突
                                new_virtual_sn = f"{bname}-RE-{bid}"
                                c.execute("UPDATE books SET serial_number=%s WHERE id=%s", (new_virtual_sn, bid))
                                
                                # 寫入操作紀錄
                                now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
                                          (now_time, st.session_state.login_id, "修復序號", f"將錯誤序號 {reset_sn} 重置為 {new_virtual_sn}"))
                                st.session_state['sys_toast'] = f"✅ 已成功將序號 {reset_sn} 洗白！"
                            else:
                                st.error("❌ 系統找不到這個序號，請確認是否輸入正確。")
                                st.session_state['db_locked'] = False
                                st.stop()
                        st.rerun()
                    else: st.warning("請先輸入序號！")

        elif st.session_state.role == 'L1' and menu in ["👥 帳號管理", "📤 借閱審核", "📥 歸還審核", "💬 回報專區"]:
            target_sq = st.session_state.get('current_sq', '')
            
        # ==========================================
        # 👥 帳號管理中心：精準連線與交易優化版
        # ==========================================
        elif menu == "👥 帳號管理":
            st.subheader("👥 帳號管理中心", help="""
:blue[**【📝 班隊開通】**]  
:yellow[**【✅審核開通】**]：開通此帳號的使用權  
:yellow[**【❌踢退開通】**]：踢退此帳號的使用權  
:blue[**【👤 帳號管理】**]  
:yellow[**【📅 結訓日期】**]：點擊更改結訓日期  
:yellow[**【💾 儲存】**]：按下 :red[**💾 儲存**]  
:yellow[**【🔑重置密碼為隨機】**]：按下按鈕後系統將生成隨機密碼供訓員登入。""")

            acc_tabs = st.tabs(["📝 班隊開通", "👤 帳號管理"])
            
            # --- Tab 1: 班隊開通 (審核待開通帳號) ---
            with acc_tabs[0]:
                st.subheader("📝 班隊開通")
                # 精準讀取：僅撈取待審核名單
                with get_db_connection() as conn:
                    reg_df = pd.read_sql_query(
                        "SELECT id, squadron as 中隊, title as 班隊, login_id as 帳號, discharge_date as 結訓日 FROM users WHERE status='待審核' AND squadron = ANY(%s)", 
                        conn, params=(target_sq_list,)
                    )
                
                if not reg_df.empty:
                    for _, row in reg_df.iterrows():
                        uid = row['id']
                        with st.container(border=True):
                            st.markdown(f"🎓 **班隊全銜：** `{row['班隊']}`  \n📍 **中隊：** `{row['中隊']}`  \n🆔 **申請帳號：** `{row['帳號']}`  \n📅 **結訓日期：** `{row['結訓日']}`")
                            col1, col2 = st.columns(2)
                            with col1:
                                if st.button("✅ 審核開通", key=f"app_reg_{uid}", type="primary", use_container_width=True):
                                    with db_transaction(success_msg="✅ 已審核開通！") as c:
                                        c.execute("UPDATE users SET status='啟用' WHERE id=%s", (uid,))
                                        # 寫入操作紀錄
                                        now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                        c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
                                                  (now_time, st.session_state.login_id, "開通帳號", f"核准開通：{row['班隊']} ({row['帳號']})"))
                                    st.rerun()
                            with col2:
                                if st.button("❌ 踢退開通", key=f"rej_reg_{uid}", use_container_width=True):
                                    # 呼叫已定義的 Dialog 進行刪除
                                    delete_account_dialog(uid, row['班隊'])
                else:
                    st.success("✨ 目前無待審核的註冊申請。")

            # --- Tab 2: 帳號管理 (管理現有訓員) ---
            with acc_tabs[1]:
                st.subheader("👤 帳號管理")
                # 精準讀取：撈取現有訓員名單
                with get_db_connection() as conn:
                    l2_users = pd.read_sql_query(
                        "SELECT id, squadron as 中隊, title as 班隊, login_id as 訓員帳號, status as 狀態, discharge_date as 結訓日 FROM users WHERE role='L2' AND status IN ('啟用', '結訓凍結') AND squadron = ANY(%s) ORDER BY title", 
                        conn, params=(target_sq_list,)
                    )
                
                if not l2_users.empty:
                    for unit_name in l2_users['班隊'].unique():
                        u_df = l2_users[l2_users['班隊'] == unit_name]
                        with st.expander(f"🔽 {unit_name} (共 {len(u_df)} 個帳號)"):
                            for _, row in u_df.iterrows():
                                uid = row['id']
                                with st.container(border=True):
                                    status_emoji = '🟢' if row['狀態'] == '啟用' else '❄️'
                                    st.markdown(f"🆔 **登入帳號：** `{row['訓員帳號']}`\n\n{status_emoji} **狀態：** `{row['狀態']}`")
                                    
                                    # 日期處理防呆
                                    def_date = pd.to_datetime(row['結訓日']).date() if pd.notna(row['結訓日']) else datetime.now(timezone(timedelta(hours=8))).date()
                                    new_date = st.date_input("📅 結訓日期 (點擊修改)", value=def_date, key=f"date_edit_{uid}")
                                    
                                    col_s, col_r = st.columns(2)
                                    with col_s:
                                        if st.button("💾 儲存", key=f"save_user_{uid}", type="primary", use_container_width=True):
                                            with db_transaction(success_msg="✅ 結訓日已更新！") as c:
                                                # 如果原為凍結狀態，修改日期後自動復權
                                                new_status = '啟用' if row['狀態'] == '結訓凍結' else row['狀態']
                                                c.execute("UPDATE users SET discharge_date=%s, status=%s WHERE id=%s", (new_date, new_status, uid))
                                                now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
                                                          (now_time, st.session_state.login_id, "修改結訓日", f"將 {row['班隊']} ({row['訓員帳號']}) 結訓日延至 {new_date}"))
                                            st.rerun()
                                    with col_r:
                                        if st.button("🔑 重置隨機密碼", key=f"reset_pw_{uid}", use_container_width=True):
                                            import string
                                            alphabet = string.ascii_letters + string.digits
                                            new_raw_pwd = ''.join(secrets.choice(alphabet) for i in range(8))
                                            
                                            with db_transaction(success_msg=f"✅ 重置成功！新密碼：{new_raw_pwd}") as c:
                                                c.execute("UPDATE users SET password=%s WHERE id=%s", (generate_password_hash(new_raw_pwd), uid))
                                                now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
                                                          (now_time, st.session_state.login_id, "重置密碼", f"強制重置 {row['班隊']} ({row['訓員帳號']}) 密碼"))
                                            st.rerun()
                else:
                    st.success("✨ 目前無可管理的訓員資料。")

        elif menu == "📤 借閱審核":
                st.subheader("📚 借閱準則審核", help="""
:blue[**【📚 借閱準則審核】**]  
:yellow[**【📌 選擇班隊】**]:在`   `內選擇要審核的班隊  
:yellow[**【🔽 展開】**]：展開此班隊借閱資訊  
:yellow[**【✅ 全審核】**]：審核此班隊全部借閱申請  
:yellow[**【❌ 全踢退】**]：踢退此班隊全部借閱申請  
:yellow[**【📋調整數量】**]：調整此本借閱準則數量  
:yellow[**【✅審核】**]：審核此本借閱準則申請  
:yellow[**【❌踢退】**]：踢退此本借閱準則申請  
:yellow[**【💾 送出班隊的審核結果】**]：  
按下:red[💾 送出班隊的審核結果]儲存""")
                req_df = pd.read_sql_query("SELECT br.id as 單號, br.login_id as 帳號, u.title as 班隊, br.book_name as 書名, br.quantity as 申請數量, u.status as 帳號狀態 FROM borrow_requests br JOIN users u ON br.login_id = u.login_id WHERE br.status='待審核' AND u.squadron = ANY(%s) ORDER BY u.title, br.book_name, br.id", conn, params=(target_sq_list,))
                
                if not req_df.empty:
                    unit_list = req_df['班隊'].unique()
                    selected_unit = st.selectbox("📌 選擇要審核的班隊", unit_list)
                    
                    unit_df = req_df[req_df['班隊'] == selected_unit]
                    u_status = unit_df.iloc[0]['帳號狀態']
                    
                    st.markdown(f"### 【{selected_unit}】待審核: {len(unit_df)} 筆")
                    
                    owned_counts = []
                    c = conn.cursor()
                    for _, row in unit_df.iterrows():
                        c.execute("SELECT COUNT(*) FROM books WHERE owner_id=%s AND book_name=%s AND status IN ('借閱中', '保留待領取', '少領異常')", (row['帳號'], row['書名']))
                        owned_counts.append(c.fetchone()[0])
                    unit_df['已持有數'] = owned_counts
                    
                    unit_action = st.radio("隱藏的標題", ["🔽 展開", "✅ 全審核", "❌ 全踢退"], horizontal=True, key=f"u_req_{selected_unit}", label_visibility="collapsed")
                    
                    final_decisions = {}
                    book_actions = {}
                    
                    if unit_action == "✅ 全審核":
                        for _, row in unit_df.iterrows(): final_decisions[row['單號']] = row['申請數量']
                    elif unit_action == "❌ 全踢退":
                        for _, row in unit_df.iterrows(): final_decisions[row['單號']] = 0
                    else:
                        st.divider()
                        for _, row in unit_df.iterrows():
                            req_id, b_name, req_qty, owned = row['單號'], row['書名'], row['申請數量'], row['已持有數']
                            draw_status_card(b_name, req_qty, '申請中', f"已持有: {owned} 本")
                            
                            book_actions[req_id] = st.radio(f"處理 {req_id}", ["📋 調整數量","✅審核","❌踢退"], horizontal=True, key=f"b_req_rad_{req_id}", label_visibility="collapsed")
                            
                            if book_actions[req_id] == "✅審核": final_decisions[req_id] = req_qty
                            elif book_actions[req_id] == "❌踢退": final_decisions[req_id] = 0
                            else:
                                final_decisions[req_id] = st.number_input(f"修改【{b_name}】核准數量", min_value=0, max_value=int(req_qty), value=int(req_qty), key=f"num_{req_id}")
                    
                    st.markdown("---")
                    if st.button(f"💾 送出【{selected_unit}】的審核結果", type="primary", use_container_width=True):
                        df_records = unit_df.to_dict('records')
                        admin_borrow_approve_dialog(selected_unit, final_decisions, df_records)
                        
                else:
                    st.info("目前無待審核的準則。")

                st.markdown("---")
                st.subheader("🔴 借閱異常警示", help="""
:blue[**【🔴 借閱異常警示】**]：訓員未領準則，將其退庫  
:yellow[**【☑️全結案】**]:勾選☑️全結案或選擇單本準則  
:yellow[**【🔄異常庫存退庫】**]：按🔄異常庫存退庫  """)
                abnormal_df = pd.read_sql_query("SELECT b.id, u.title as 班隊, b.book_name as 書名, b.serial_number as 序號 FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='少領異常' AND u.squadron = ANY(%s) ORDER BY u.title, b.book_name", conn, params=(target_sq_list,))
                if not abnormal_df.empty:
                    edited_abn_dfs, abn_checks = {}, {}
                    for unit_name in abnormal_df['班隊'].unique():
                        st.markdown(f'<div class="single-line-text" style="font-size:22px; font-weight:bold; margin: 15px 0 10px 0;">【{unit_name}】</div>', unsafe_allow_html=True)
                        unit_df = abnormal_df[abnormal_df['班隊'] == unit_name]
                        for b_name in unit_df['書名'].unique():
                            b_df = unit_df[unit_df['書名'] == b_name].reset_index(drop=True)
                            u_key = f"abn_{unit_name}_{b_name}"
                            col_chk, col_exp = st.columns([1.5, 8.5])
                            with col_chk:
                                st.write(""); abn_checks[u_key] = st.checkbox(f"☑️ 全結案 ({len(b_df)}本)", key=f"abn_all_{u_key}")
                            with col_exp:
                                with st.expander(f"📘 {b_name} (待釋放 {len(b_df)} 本)"):
                                    if not abn_checks[u_key]:
                                        # 🛡️ 4. 批次操作的 UX 減壓：內部展開也預設打勾方便結案
                                        b_df.insert(0, "✅ 結案", False)
                                        edited_abn_dfs[u_key] = st.data_editor(b_df, hide_index=True, disabled=["id", "班隊", "書名", "序號"], width='stretch', column_config={"✅ 結案": st.column_config.CheckboxColumn("✅ 結案(退庫)"), "id": None, "班隊": None, "書名": None}, key=f"abn_chk_{u_key}")
                    st.markdown("---")
                    if st.button("🔄 異常庫存退庫", type="primary"):
                        resolved_ids = []
                        resolved_books_summary = []
                        for unit_name in abnormal_df['班隊'].unique():
                            unit_df = abnormal_df[abnormal_df['班隊'] == unit_name]
                            for b_name in unit_df['書名'].unique():
                                u_key = f"abn_{unit_name}_{b_name}"
                                curr_ids = []
                                if abn_checks[u_key]: curr_ids.extend(unit_df[unit_df['書名'] == b_name]["id"].tolist())
                                elif edited_abn_dfs.get(u_key) is not None: curr_ids.extend(edited_abn_dfs[u_key][edited_abn_dfs[u_key]["✅ 結案"] == True]["id"].tolist())
                                
                                if curr_ids:
                                    resolved_ids.extend(curr_ids)
                                    resolved_books_summary.append(f"{unit_name}的{b_name}({len(curr_ids)}本)")
                                    
                        if resolved_ids:
                            with db_transaction(success_msg=f"✅ 成功結案！已釋放 {len(resolved_ids)} 本準則。") as c:
                                c.execute("UPDATE books SET status='在庫', owner_id='在庫' WHERE id = ANY(%s)", (resolved_ids,))
                                now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                summary_str = "、".join(resolved_books_summary)
                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "異常處理", f"將少領的 {len(resolved_ids)} 本額度釋放回庫房：{summary_str}"))
                            st.rerun()
                else:
                    st.success("目前無異常少領通報。")

        elif menu == "📥 歸還審核":
                st.subheader("📥 準則歸還與遺失", help="點收歸還的準則，或處理已結訓但未歸還的遺失帳務。")
                ret_tabs = st.tabs(["📥 準則歸還清單", "🚨 遺失準則"])
                
                with ret_tabs[0]:
                    return_df = pd.read_sql_query("SELECT b.id, u.title as 班隊, b.book_name as 書名, b.serial_number as 序號, b.owner_id, u.status as 帳號狀態 FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='歸還中' AND u.squadron = ANY(%s) ORDER BY u.title, b.book_name", conn, params=(target_sq_list,))
                    
                    if not return_df.empty:
                        ret_unit_list = return_df['班隊'].unique()
                        sel_ret_unit = st.selectbox("📌 選擇要點收的班隊", ret_unit_list)
                        
                        unit_df = return_df[return_df['班隊'] == sel_ret_unit]
                        u_status = unit_df.iloc[0]['帳號狀態']
                        
                        st.markdown(f"### 【{sel_ret_unit}】待歸還: {len(unit_df)} 本")
                        
                        unit_action = st.radio("隱藏標題", ["🔽 展開", "✅ 全點收", "❌ 全踢退"], horizontal=True, key=f"u_ret_rad_{sel_ret_unit}", label_visibility="collapsed")
                        
                        book_actions, item_actions = {}, {}
                        
                        if unit_action == "🔽 展開":
                            st.divider()
                            for b_name in unit_df['書名'].unique():
                                b_df = unit_df[unit_df['書名'] == b_name]
                                u_b_key = f"{sel_ret_unit}_{b_name}"
                                
                                with st.expander(f"📘 {b_name} (共 {len(b_df)} 本)"):
                                    book_actions[u_b_key] = st.radio(f"{b_name} 處理", ["🔽 展開", "✅ 全點收", "❌ 全踢退"], horizontal=True, key=f"b_rad_{u_b_key}")
                                    
                                    if book_actions[u_b_key] == "🔽 展開":
                                        st.markdown("---")
                                        for _, row in b_df.iterrows():
                                            c1, c2 = st.columns([5, 5])
                                            c1.markdown(f"🔖 序號: `{row['序號']}`")
                                            item_actions[row['id']] = c2.radio("操作", ["✅ 點收", "❌ 踢退"], horizontal=True, key=f"ret_item_{row['id']}", label_visibility="collapsed")
                                        st.write("")
                        
                        st.markdown("---")
                        if st.button(f"💾 送出【{sel_ret_unit}】點收結果", type="primary", use_container_width=True):
                            to_stock_ids, to_borrowed_ids, to_lost_ids = [], [], []
                            
                            if unit_action == "✅ 全點收":
                                to_stock_ids.extend(unit_df['id'].tolist())
                            elif unit_action == "❌ 全踢退":
                                if u_status == '結訓凍結': to_lost_ids.extend(unit_df['id'].tolist())
                                else: to_borrowed_ids.extend(unit_df['id'].tolist())
                            else:
                                for b_name in unit_df['書名'].unique():
                                    b_df = unit_df[unit_df['書名'] == b_name]
                                    u_b_key = f"{sel_ret_unit}_{b_name}"
                                    
                                    if book_actions[u_b_key] == "✅ 全點收":
                                        to_stock_ids.extend(b_df['id'].tolist())
                                    elif book_actions[u_b_key] == "❌ 全踢退":
                                        if u_status == '結訓凍結': to_lost_ids.extend(b_df['id'].tolist())
                                        else: to_borrowed_ids.extend(b_df['id'].tolist())
                                    else:
                                        for _, row in b_df.iterrows():
                                            i_act = item_actions[row['id']]
                                            if i_act == "✅ 點收": to_stock_ids.append(row['id'])
                                            else:
                                                if u_status == '結訓凍結': to_lost_ids.append(row['id'])
                                                else: to_borrowed_ids.append(row['id'])
                                                
                            admin_return_approve_dialog(sel_ret_unit, to_stock_ids, to_borrowed_ids, to_lost_ids)
                    else:
                        st.success("目前各班隊皆無待準則歸還之準則！")

                with ret_tabs[1]:
                    st.subheader("🚨 遺失準則", help="尋獲時，點擊右側按鈕即可結案！")
                    lost_df = pd.read_sql_query("SELECT b.id, u.title as 班隊, b.book_name as 書名, b.serial_number as 序號 FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='遺失待賠' AND u.squadron = ANY(%s) ORDER BY u.title, b.book_name", conn, params=(target_sq_list,))
                    
                    if not lost_df.empty:
                        for _, row in lost_df.iterrows():
                            l_id = row['id']
                            with st.container(border=True):
                                col1, col2 = st.columns([7, 3])
                                with col1:
                                    st.markdown(f"{row['班隊']}  \n📘 **書名：** `{row['書名']}`  \n🔖 **序號：** `{row['序號']}`")
                                with col2:
                                    st.write("")
                                    if st.button("✅ 尋獲", key=f"lost_res_{l_id}", type="primary", use_container_width=True):
                                        with db_transaction(success_msg="✅ 結案成功！已退回庫房。") as c:
                                            now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                            c.execute("UPDATE books SET status='在庫', owner_id='在庫' WHERE id=%s", (l_id,))
                                            c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "遺失結案", f"尋獲或完成賠償，退庫: {row['書名']} ({row['序號']})"))
                                        st.rerun()
                    else:
                        st.success("✨ 準則妥善率 100%！目前中隊無任何遺失之準則！")

            elif menu in ["💬 回報專區", "回報專區"]:
                st.subheader("💬 Line 報表自動生成器", help="自動彙整各班隊的借還書與清點現況，方便複製回報至 LINE 群組。")
                line_tabs = st.tabs(["🚚 準則借還訊息生成", "📦 準則清點"])
                
                with line_tabs[0]:
                    st.subheader("🚚 準則借還訊息生成", help="生成當下準則借還訊息，點擊生成訊息黑框右上角「📋」複製。")
                    st.markdown(f"📍 **目前產出中隊：** `{target_sq}`")
                    
                    dyn_mode = st.radio("🎯 回報範圍", ["中隊", "班隊"], horizontal=True, key="dyn_mode")
                    dyn_selected_units = []
                    if dyn_mode == "班隊":
                        c = conn.cursor()
                        c.execute("SELECT DISTINCT title FROM users WHERE squadron = ANY(%s) AND role='L2'", (target_sq_list,))
                        avail_units = [row[0] for row in c.fetchall()]
                        dyn_selected_units = st.multiselect("📌 請加入要回報的班隊 (可多選)：", avail_units, key="dyn_units")
                        
                    if st.button("🚀 生成準則借還訊息", type="primary"):
                        params = [target_sq_list]
                        unit_filter = ""
                        if dyn_mode == "班隊" and dyn_selected_units:
                            unit_filter = " AND u.title = ANY(%s)"
                            params.append(dyn_selected_units)
                        params_tuple = tuple(params)
                        
                        req_df = pd.read_sql_query(f"SELECT u.title as unit, br.book_name, SUM(br.quantity) as qty FROM borrow_requests br JOIN users u ON br.login_id = u.login_id WHERE u.squadron = ANY(%s) AND br.status='待審核'{unit_filter} GROUP BY u.title, br.book_name", conn, params=params_tuple)
                        res_df = pd.read_sql_query(f"SELECT u.title as unit, b.book_name, COUNT(b.id) as qty FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.squadron = ANY(%s) AND b.status='保留待領取'{unit_filter} GROUP BY u.title, b.book_name", conn, params=params_tuple)
                        ret_df = pd.read_sql_query(f"SELECT u.title as unit, b.book_name, COUNT(b.id) as qty FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.squadron = ANY(%s) AND b.status='歸還中'{unit_filter} GROUP BY u.title, b.book_name ORDER BY b.book_name", conn, params=params_tuple)
                        
                        now = datetime.now(timezone(timedelta(hours=8)))
                        tw_wd = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
                        msg = f"劉姐好，{target_sq}借還書清單\n時間：{now.month}/{now.day}（{tw_wd}）\n\n"
                        
                        all_units = set()
                        if not req_df.empty: all_units.update(req_df['unit'].tolist())
                        if not res_df.empty: all_units.update(res_df['unit'].tolist())
                        if not ret_df.empty: all_units.update(ret_df['unit'].tolist())
                        
                        if not all_units: msg += "無借還書清單。\n"
                        else:
                            for unit in sorted(list(all_units)):
                                unit_msg = ""
                                borrow_items = {}
                                
                                if not req_df.empty:
                                    for _, r in req_df[req_df['unit'] == unit].iterrows(): borrow_items[r['book_name']] = borrow_items.get(r['book_name'], 0) + int(r['qty'])
                                if not res_df.empty:
                                    for _, r in res_df[res_df['unit'] == unit].iterrows(): borrow_items[r['book_name']] = borrow_items.get(r['book_name'], 0) + int(r['qty'])
                                        
                                if borrow_items:
                                    unit_msg += "【借閱書目】：\n"
                                    for b_name in sorted(borrow_items.keys()): unit_msg += f"{b_name} * {borrow_items[b_name]}\n"
                                
                                return_items = []
                                if not ret_df.empty and not ret_df[ret_df['unit'] == unit].empty:
                                    for _, r in ret_df[ret_df['unit'] == unit].iterrows(): return_items.append(f"{r['book_name']} * {int(r['qty'])}\n")
                                
                                if return_items:
                                    if unit_msg: unit_msg += "\n"
                                    unit_msg += "【歸還書目】：\n"
                                    for i in return_items: unit_msg += i
                                    
                                if unit_msg:
                                    msg += f"【{unit}】\n{unit_msg}\n"
                        st.code(msg.strip(), language="text")

                with line_tabs[1]:
                    st.subheader("📦 準則清點", help="生成當下準則清點訊息，點擊生成訊息黑框右上角「📋」複製。")
                    st.markdown(f"📍 **目前產出中隊：** `{target_sq}`")
                        
                    inv_mode = st.radio("🎯 回報範圍", ["中隊", "中隊(序號)", "班隊"], horizontal=True, key="inv_mode2")
                    inv_selected_units = []
                    if inv_mode == "班隊":
                        c = conn.cursor()
                        c.execute("SELECT DISTINCT title FROM users WHERE squadron = ANY(%s) AND role='L2'", (target_sq_list,))
                        avail_units = [row[0] for row in c.fetchall()]
                        inv_selected_units = st.multiselect("📌 請加入要回報的班隊 (可多選)：", avail_units, key="inv_units2")
                        
                    if st.button("🚀 生成準則清點訊息", type="primary"):
                        params = [target_sq_list]
                        unit_filter = ""
                        if inv_mode == "班隊" and inv_selected_units:
                            unit_filter = " AND u.title = ANY(%s)"
                            params.append(inv_selected_units)
                            
                        # 💡 視覺修正：在 SQL 排除「保留待領取」及「未登載虛擬序號」
                        query = f"""
                        SELECT u.title as unit, 
                               b.book_name, 
                               b.status, 
                               COUNT(b.id) as qty,
                               STRING_AGG(
                                   CASE 
                                       WHEN b.status IN ('保留待領取', '少領異常') THEN NULL
                                       WHEN b.serial_number LIKE b.book_name || '-%%' THEN NULL 
                                       ELSE b.serial_number 
                                   END, 
                                   ', '
                               ) as serials
                        FROM books b 
                        JOIN users u ON b.owner_id = u.login_id 
                        WHERE u.squadron = ANY(%s) 
                          AND b.status IN ('借閱中', '歸還中', '遺失待賠', '少領異常') {unit_filter} 
                        GROUP BY u.title, b.book_name, b.status
                        """
                        inv_df = pd.read_sql_query(query, conn, params=tuple(params))
                        
                        now = datetime.now(timezone(timedelta(hours=8)))
                        tw_wd = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
                        inv_msg = f"{target_sq}準則清點總表\n時間：{now.month}/{now.day}（{tw_wd}）\n\n"
                        
                        if inv_df.empty: 
                            inv_msg += "目前無借閱任何準則。\n"
                        else:
                            inv_df = apply_shadow_sort(inv_df, has_unit=True)
                            for unit in inv_df['unit'].unique():
                                inv_msg += f"【{unit}】\n"
                                for _, r in inv_df[inv_df['unit'] == unit].iterrows():
                                    if inv_mode == "中隊(序號)":
                                        inv_msg += f"📘 {r['book_name']} * {int(r['qty'])} ({r['status']}) [序號: {r['serials']}]\n"
                                    else:
                                        inv_msg += f"📘 {r['book_name']} * {int(r['qty'])} ({r['status']})\n"
                                inv_msg += "\n"
                        
                        st.code(inv_msg.strip(), language="text")

        elif menu in ["綜合查詢", "🔍 綜合查詢"]:
            st.header("🔍 綜合查詢", help="「查書名」、「查序號」、「查車輛」都可輸入關鍵字搜尋。")
            search_type = st.radio("查詢模式", ["查書名", "查序號", "查車輛"], horizontal=True)

            keyword = st.text_input("請輸入關鍵字")
            if st.button("搜尋") and keyword:
                if "書名" in search_type:
                    query = "SELECT u.squadron as 中隊, u.title as 班隊, COUNT(b.id) as 數量 FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.book_name LIKE %s GROUP BY u.squadron, u.title"
                    res = pd.read_sql_query(query, conn, params=(f"%{keyword}%",))
                    st.dataframe(res, hide_index=True, use_container_width=True)
                elif "序號" in search_type:
                    # 💡 完美修復查詢顯示：遇到庫房的書，直接標示為「庫房」
                    query = """
                    SELECT 
                        CASE WHEN b.owner_id = '在庫' THEN '庫房' ELSE COALESCE(u.squadron, '⚠️ 未知/已刪除') END as 中隊, 
                        CASE WHEN b.owner_id = '在庫' THEN '庫房' ELSE COALESCE(u.title, b.owner_id) END as 班隊, 
                        b.book_name as 書名, 
                        b.status as 狀態 
                    FROM books b 
                    LEFT JOIN users u ON b.owner_id = u.login_id 
                    WHERE b.serial_number = %s
                    """
                    res = pd.read_sql_query(query, conn, params=(keyword,))
                    st.dataframe(res, hide_index=True, use_container_width=True)
                else:
                    clean_kw = re.sub(r'[^A-Za-z0-9\u4e00-\u9fa5]', '', keyword).upper()
                    # 直接從 vehicles 表獨立抓取資料，並拔除姓名顯示與搜尋
                    query = """
                    SELECT squadron as 中隊, unit_title as 班隊, plate_number as 車號, parking_lot as 停車場, parking_number as 停車號碼, discharge_date as 結訓日期 
                    FROM vehicles 
                    WHERE plate_number ILIKE %s OR unit_title ILIKE %s
                    """
                    res = pd.read_sql_query(query, conn, params=(f"%{clean_kw}%", f"%{clean_kw}%"))
                    if res.empty:
                        st.warning("查無符合條件的車輛，請確認關鍵字是否正確。")
                    else:
                        st.dataframe(res, hide_index=True, use_container_width=True)

        elif menu == "📊 準則現況":
            current_view_sq = st.session_state.get('current_sq', st.session_state.squadron)
            st.subheader(f"📊{current_view_sq}準則現況", help="點擊下方各班隊名稱，即可展開查看該班隊目前持有的所有準則與詳細序號。")
            
            if st.session_state.role == 'L1':
                query = "SELECT u.title as unit, b.book_name, b.status, b.serial_number FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.squadron = ANY(%s) AND b.status IN ('借閱中', '保留待領取', '少領異常', '歸還中') ORDER BY u.title, b.book_name"
                books_df = pd.read_sql_query(query, conn, params=(target_sq_list,))
            else:
                query = "SELECT u.title as unit, b.book_name, b.status, b.serial_number FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.login_id = %s AND b.status IN ('借閱中', '保留待領取', '少領異常', '歸還中') ORDER BY u.title, b.book_name"
                books_df = pd.read_sql_query(query, conn, params=(st.session_state.login_id,))
                
            if books_df.empty:
                st.success("✨ 目前無任何班隊持有準則 (皆已歸還或無借閱)。")
            else:
                for unit_name, unit_group in books_df.groupby('unit', sort=False):
                    with st.expander(f"🏢 {unit_name}"):
                        sorted_group = apply_shadow_sort(unit_group)
                        grouped = sorted_group.groupby(['book_name', 'status'], sort=False)
                        for (b_name, st_val), b_rows in grouped:
                            qty = len(b_rows)
                            draw_status_card(b_name, qty, st_val)
                            
                            # 💡 視覺修正：只顯示「已完成登載狀態」的真實序號
                            display_serials = []
                            for _, s_row in b_rows.iterrows():
                                if pd.notna(s_row['serial_number']):
                                    sn = str(s_row['serial_number']).strip()
                                    # 必須是 借閱中、歸還中、遺失待賠，且不是虛擬序號(不含書名)，才顯示！
                                    if st_val in ['借閱中', '歸還中', '遺失待賠'] and b_name not in sn:
                                        display_serials.append(sn)
                                        
                            if display_serials:
                                serials_text = ", ".join(display_serials)
                                nested_html = f"""
                                <details style="margin-left: 20px; margin-bottom: 15px;">
                                    <summary style="cursor: pointer; color: #A0A0A0; font-size: 0.9em; outline: none;">🔖 點擊展開詳細序號清單</summary>
                                    <div style="margin-top: 8px; padding: 10px; border-left: 3px solid #4CAF50; background-color: rgba(255,255,255,0.05); color: #E0E0E0; font-family: monospace; word-wrap: break-word; border-radius: 0 5px 5px 0;">
                                        {serials_text}
                                    </div>
                                </details>
                                """
                                st.markdown(nested_html, unsafe_allow_html=True)
                            else:
                                st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)

        elif menu in ["操作紀錄", "🗂️ 操作紀錄"]:
            st.header("🗂️ 系統操作紀錄", help="追蹤借還、審核、設定異動與異常處理等歷史紀錄。支援關鍵字搜尋 (如輸入：姓名、班隊名稱、或特定動作)。")
            search_keyword = st.text_input("🔍 搜尋紀錄 (可輸入班隊、動作、準則名稱等)", placeholder="例如：借閱、歸還、異常...")
            
            log_query = """
                SELECT a.timestamp as 時間, 
                       COALESCE(
                           CASE 
                               WHEN u.role = 'L2' THEN u.title
                               WHEN u.role = 'L1' THEN u.squadron || '-' || u.title
                               ELSE a.user_id 
                           END, a.user_id
                       ) as 操作者, 
                       a.action as 動作, 
                       a.details as 詳細內容 
                FROM action_logs a
                LEFT JOIN users u ON a.user_id = u.login_id
            """
            params = []
            if search_keyword:
                log_query += " WHERE a.details LIKE %s OR a.action LIKE %s OR u.title LIKE %s"
                params.extend([f"%{search_keyword}%", f"%{search_keyword}%", f"%{search_keyword}%"])
                
            log_query += " ORDER BY a.id DESC LIMIT 300"
            logs_df = pd.read_sql_query(log_query, conn, params=tuple(params) if params else None)
            
            if logs_df.empty:
                st.info("📭 目前無操作紀錄。")
            else:
                def add_emoji(action):
                    act = str(action)
                    if '借閱' in act: return f"📤 {act}"
                    if '歸還' in act: return f"📥 {act}"
                    if '審核' in act: return f"✅ {act}"
                    if '踢退' in act or '異常' in act: return f"🚨 {act}"
                    if '設定' in act or '修改' in act: return f"⚙️ {act}"
                    if '登出' in act or '登入' in act: return f"👤 {act}"
                    return f"🔹 {act}"
                    
                logs_df['動作'] = logs_df['動作'].apply(add_emoji)
                st.dataframe(
                    logs_df, 
                    hide_index=True, 
                    use_container_width=True,
                    column_config={
                        "時間": st.column_config.TextColumn("🕒 發生時間", width="medium"),
                        "操作者": st.column_config.TextColumn("🧑‍✈️ 單位 / 操作者", width="medium"),
                        "動作": st.column_config.TextColumn("🎯 系統動作", width="small"),
                        "詳細內容": st.column_config.TextColumn("📝 日誌詳情", width="large")
                    }
                )

except Exception as e:
    # 🌟 讓 Streamlit 的控制訊號 (煞車/重整) 正常通過，不觸發崩潰警報
    if type(e).__name__ in ['StopException', 'RerunException']:
        raise e
        
    err_full = f"🚨 【系統發生未知崩潰】\n異常位置：全域攔截器\n錯誤內容：{e}"
    send_line_notify(err_full)
    st.error(f"系統發生預期外錯誤，已同步通報管理員。錯誤代碼：{e}")
