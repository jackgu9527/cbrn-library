import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
import os
import glob
import psycopg2
from psycopg2 import pool
from psycopg2 import IntegrityError
import warnings

# 關閉 Pandas 對於未嚴格使用 SQLAlchemy 的警告
warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

# ==========================================
# 1. 系統初始化與資料庫設定 (渦輪加速連線池)
# ==========================================
st.set_page_config(page_title="大隊部準則管理系統", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 【精準雷達】專門鎖定檔名包含「準則資料庫」的 csv 檔案
csv_candidates = [f for f in glob.glob(os.path.join(BASE_DIR, '*.csv')) if '準則資料庫' in f]
if not csv_candidates:
    csv_candidates = glob.glob(os.path.join(BASE_DIR, '*.csv'))
CSV_FILE = csv_candidates[0] if csv_candidates else None

# ⚡ 雲端連線引擎 (渦輪加速版 Plan B+)
@st.cache_resource(ttl=3600)  # 快取連線池，每小時重置以確保通道乾淨
def get_pool():
    return pool.ThreadedConnectionPool(1, 20, st.secrets["DATABASE_URL"], connect_timeout=5)

def get_db_connection():
    db_pool = get_pool()
    conn = db_pool.getconn()
    # 🛡️ 防呆機制：偵測連線是否存活
    try:
        with conn.cursor() as c:
            c.execute("SELECT 1")
    except Exception:
        # 如果閒置斷線，丟棄舊連線，瞬間重新申請
        db_pool.putconn(conn, close=True)
        conn = db_pool.getconn()
    return conn

def release_connection(conn):
    # 用完不關門，而是把連線放回池子裡保留
    try:
        get_pool().putconn(conn)
    except Exception:
        pass

def log_action(user_id, action, details):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        # 🚀 強制綁定台灣時區 (UTC+8)
        tz_tw = timezone(timedelta(hours=8))
        tw_now = datetime.now(tz_tw).strftime("%Y-%m-%d %H:%M:%S")
        
        c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)",
                  (tw_now, str(user_id), str(action), str(details)))
        conn.commit()
    finally:
        release_connection(conn)

def init_db():
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        login_id TEXT UNIQUE, password TEXT, role TEXT, unit TEXT,
                        squadron TEXT, title TEXT, name TEXT, discharge_date DATE, 
                        setup_count INTEGER DEFAULT 1, status TEXT DEFAULT '啟用',
                        pending_name TEXT, pending_login_id TEXT
                    )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS books (
                        id SERIAL PRIMARY KEY,
                        book_name TEXT, serial_number TEXT UNIQUE, owner_id TEXT, status TEXT
                    )''')
                    
        c.execute('''CREATE TABLE IF NOT EXISTS borrow_requests (
                        id SERIAL PRIMARY KEY,
                        login_id TEXT, unit TEXT, book_name TEXT, quantity INTEGER, status TEXT
                    )''')
                    
        c.execute('''CREATE TABLE IF NOT EXISTS action_logs (
                        id SERIAL PRIMARY KEY,
                        timestamp TEXT, user_id TEXT, action TEXT, details TEXT
                    )''')
        
        c.execute("SELECT COUNT(*) FROM users")
        if c.fetchone()[0] == 0:
            default_users = [
                ('1', '1', 'L1', '大隊部', '大隊部', '系統管理員', '管理員', None, 0, '啟用'),
                ('2', '2', 'L2', '大隊部', '大隊部', '大隊長', '', None, 0, '啟用'),
                ('3', '3', 'L2', '大隊部', '大隊部', '大隊輔導長', '', None, 0, '啟用'),
                ('4', '4', 'L3', '學員一中隊', '學員一中隊', '隊長', '', None, 0, '啟用'),
                ('5', '5', 'L3', '學員一中隊', '學員一中隊', '輔導長', '', None, 0, '啟用'),
                ('6', '6', 'L3', '學員二中隊', '學員二中隊', '隊長', '', None, 0, '啟用'),
                ('7', '7', 'L3', '學員二中隊', '學員二中隊', '輔導長', '', None, 0, '啟用'),
                ('8', '8', 'L3', '學生一中隊', '學生一中隊', '隊長', '', None, 0, '啟用'),
                ('9', '9', 'L3', '學生一中隊', '學生一中隊', '輔導長', '', None, 0, '啟用'),
                ('10', '10', 'L3', '學生二中隊', '學生二中隊', '隊長', '', None, 0, '啟用'),
                ('11', '11', 'L3', '學生二中隊', '學生二中隊', '輔導長', '', None, 0, '啟用'),
                ('12', '12', 'L4', '學生一中隊', '學生一中隊', '區隊長', '①', None, 1, '啟用'),
                ('13', '13', 'L4', '學生一中隊', '學生一中隊', '區隊長', '②', None, 1, '啟用'),
                ('14', '14', 'L4', '學生二中隊', '學生二中隊', '區隊長', '①', None, 1, '啟用'),
                ('15', '15', 'L4', '學生二中隊', '學生二中隊', '區隊長', '②', None, 1, '啟用'),
                ('16', '16', 'L4', '學生二中隊', '學生二中隊', '分隊長', '①', None, 1, '啟用'),
                ('17', '17', 'L4', '學生二中隊', '學生二中隊', '分隊長', '②', None, 1, '啟用'),
                ('18', '18', 'L4', '學生二中隊', '學生二中隊', '分隊長', '③', None, 1, '啟用'),
                ('19', '19', 'L4', '學生二中隊', '學生二中隊', '分隊長', '④', None, 1, '啟用'),
                ('20', '20', 'L4', '學生二中隊', '學生二中隊', '分隊長', '⑤', None, 1, '啟用'),
                ('21', '21', 'L4', '學生二中隊', '學生二中隊', '分隊長', '⑥', None, 1, '啟用'),
                ('22', '22', 'L4', '學生二中隊', '學生二中隊', '分隊長', '⑦', None, 1, '啟用'),
                ('23', '23', 'L4', '學生二中隊', '學生二中隊', '分隊長', '⑧', None, 1, '啟用'),
                ('24', '24', 'L4', '學生二中隊', '學生二中隊', '分隊長', '⑨', None, 1, '啟用'),
                ('25', '25', 'L4', '聯合中隊', '學員一中隊,學生一中隊', '文書兵', '①', None, 1, '啟用'),
                ('26', '26', 'L4', '聯合中隊', '學員二中隊,學生二中隊', '文書兵', '②', None, 1, '啟用')
            ]
            c.executemany("INSERT INTO users (login_id, password, role, unit, squadron, title, name, discharge_date, setup_count, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", default_users)
            
        c.execute("SELECT COUNT(*) FROM books")
        if c.fetchone()[0] == 0:
            if CSV_FILE and os.path.exists(CSV_FILE):
                try:
                    try:
                        df_books = pd.read_csv(CSV_FILE, encoding='big5')
                    except UnicodeDecodeError:
                        df_books = pd.read_csv(CSV_FILE, encoding='utf-8')
                        
                    insert_data = []
                    for index, row in df_books.iterrows():
                        if '書刊名稱' in row and pd.notna(row['書刊名稱']):
                            raw_title = str(row['書刊名稱']).strip()
                            
                            pub_date = ""
                            if '出版日期' in row and pd.notna(row['出版日期']):
                                raw_date = str(row['出版日期']).strip()
                                if raw_date.endswith('.0'): raw_date = raw_date[:-2]
                                pub_date = raw_date
                                
                            book_title = f"{raw_title} [{pub_date}]" if pub_date else raw_title
                            
                            qty = 1
                            if '數量' in row and pd.notna(row['數量']):
                                qty = int(row['數量'])
                            elif '化訓準則館' in row and pd.notna(row['化訓準則館']):
                                qty = int(row['化訓準則館'])
                                
                            for i in range(1, qty + 1):
                                serial = f"{book_title}-{i:03d}"
                                insert_data.append((book_title, serial, '在庫', '在庫'))
                    
                    c.executemany("INSERT INTO books (book_name, serial_number, owner_id, status) VALUES (%s,%s,%s,%s)", insert_data)
                except Exception as e:
                    pass
                
        conn.commit()
    finally:
        release_connection(conn)

# ⚡ 初次連線檢查
try:
    init_db()
except Exception as e:
    st.error(f"資料庫連線失敗！請檢查 Secrets 或網路狀態。詳細錯誤：{e}")
    st.stop()

# ==========================================
# ⚡ 幽靈背景引擎：結訓日 24:00 全自動清查 (台灣時區校正版)
# ==========================================
def run_ghost_cleanup():
    if 'ghost_engine_ran' in st.session_state:
        return
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        # 🚀 強制對齊台灣時間 (UTC+8)，精準執行 24:00 斬首行動
        tz_tw = timezone(timedelta(hours=8))
        today_str = datetime.now(tz_tw).strftime('%Y-%m-%d')
        
        c.execute(f"SELECT id, login_id, unit FROM users WHERE role='L5' AND discharge_date < '{today_str}' AND status='啟用'")
        overdue_users = c.fetchall()
        
        if overdue_users:
            now_time = datetime.now(tz_tw).strftime("%Y-%m-%d %H:%M:%S")
            
            for u_row in overdue_users:
                u_id = int(u_row[0])
                u_login = str(u_row[1])
                u_unit = str(u_row[2])
                
                c.execute(f"SELECT COUNT(*) FROM books WHERE owner_id='{u_login}' AND status!='在庫'")
                unreturned = int(c.fetchone()[0])
                
                if unreturned == 0:
                    c.execute(f"DELETE FROM users WHERE id={u_id}")
                    c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, "SYSTEM", "帳號註銷", f"班隊 {u_unit} ({u_login}) 已結訓且無欠裝，自動註銷。"))
                else:
                    c.execute("SELECT login_id FROM users WHERE login_id LIKE 'cbrn%'")
                    existing_cbrn = [row[0] for row in c.fetchall()]
                    cbrn_idx = 1
                    while f"cbrn{cbrn_idx}" in existing_cbrn:
                        cbrn_idx += 1
                    new_login = f"cbrn{cbrn_idx}"
                    
                    c.execute(f"UPDATE users SET login_id='{new_login}', password='LOCKED', status='停權' WHERE id={u_id}")
                    c.execute(f"UPDATE books SET owner_id='{new_login}' WHERE owner_id='{u_login}'")
                    c.execute(f"UPDATE borrow_requests SET login_id='{new_login}' WHERE login_id='{u_login}'")
                    c.execute(f"UPDATE action_logs SET user_id='{new_login}' WHERE user_id='{u_login}'")
                    c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, "SYSTEM", "強制扣留", f"班隊 {u_unit} ({u_login}) 結訓欠裝 {unreturned} 本，強制鎖定為 {new_login}。"))
                    
        seven_days_ago = (datetime.now(tz_tw) - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        c.execute(f"DELETE FROM action_logs WHERE timestamp < '{seven_days_ago}' AND user_id NOT IN (SELECT login_id FROM users) AND user_id != 'SYSTEM'")
        conn.commit()
    except Exception:
        pass
    finally:
        release_connection(conn)
        st.session_state['ghost_engine_ran'] = True 

# ==========================================
# 2. 登入與註冊模組
# ==========================================
if 'logged_in' not in st.session_state:
    st.markdown("##  大隊部準則管理系統")
    tab1, tab2 = st.tabs([" 系統登入", " 新進班隊註冊"])
    
    with tab1:
        login_id = st.text_input("帳號 (Login ID)")
        password = st.text_input("密碼 (Password)", type="password")
        if st.button("登入"):
            conn = get_db_connection()
            try:
                # 🛡️ 參數化查詢：將帳號密碼作為 tuple 傳入 params，防禦 SQL Injection
                user = pd.read_sql_query("SELECT * FROM users WHERE login_id=%s AND password=%s", conn, params=(login_id, password))
                if not user.empty:
                    if user.iloc[0]['status'] == '待審核':
                        st.warning("⚠️ 您的帳號尚未開通，請等待幹部審核。")
                    elif user.iloc[0]['status'] == '停權':
                        st.error("🚨 您的帳號因欠裝已被扣押鎖死！請聯絡長官處理。")
                    else:
                        for col in user.columns:
                            st.session_state[col] = user.iloc[0][col]
                        st.session_state['logged_in'] = True
                        log_action(login_id, "登入", "使用者成功登入系統")
                        st.rerun()
                else:
                    st.error("❌ 帳號或密碼錯誤 / 帳號不存在")
            finally:
                release_connection(conn)

    with tab2:
        st.info("新進班隊請在此註冊，送出後將由幹部審核開通。")
        reg_squadron = st.selectbox("所屬中隊", [ "學員一中隊","學員二中隊","學生一中隊", "學生二中隊" ])
        reg_unit = st.text_input("班隊全銜 (例：煙幕士兵班115-1期)")
        reg_id = st.text_input("設定登入帳號")
        reg_pw = st.text_input("設定登入密碼", type="password")
        reg_date = st.date_input("結訓日期")
        
        if st.button("送出註冊申請"):
            if reg_unit and reg_id and reg_pw:
                conn = get_db_connection()
                try:
                    c = conn.cursor()
                    c.execute("SELECT COUNT(*) FROM users WHERE login_id=%s OR pending_login_id=%s", (reg_id, reg_id))
                    if c.fetchone()[0] > 0:
                        st.error("❌ 此帳號已被使用，請更換名稱！")
                    else:
                        c.execute("INSERT INTO users (login_id, password, role, unit, squadron, title, name, discharge_date, status, setup_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                  (reg_id, reg_pw, 'L5', reg_unit, reg_squadron, '訓員', '代表', reg_date.strftime('%Y-%m-%d'), '待審核', 1))
                        conn.commit()
                        log_action(reg_id, "註冊申請", f"{reg_squadron} {reg_unit} 提出註冊申請")
                        st.success("✅ 註冊申請已送出！請等待幹部核准後即可登入。")
                finally:
                    release_connection(conn)
            else:
                st.warning("請填寫所有欄位")
    st.stop()

# ⚡ 登入成功後，立刻觸發幽靈引擎 (每日只掃 1 次)
run_ghost_cleanup()

# ==========================================
# 3. 介面顯示邏輯與左側選單
# ==========================================
if st.session_state.role in ['L1', 'L2', 'L3']:
    display_name = f"{st.session_state.squadron}{st.session_state.title} {st.session_state.name}"
elif st.session_state.role == 'L4':
    display_name = f"{st.session_state.squadron}{st.session_state.title} {st.session_state.name}"
else:
    display_name = f"{st.session_state.unit}"

with st.sidebar:
    st.markdown(f"### {display_name}")
    st.markdown(f"ID: {st.session_state.login_id}")
    st.markdown("---")
    
    if st.session_state.role == 'L5':
        menu = st.radio("功能導覽", ["首頁", "準則借閱", "準則歸還", "綜合查詢"])
    else:
        menu = st.radio("管理作業", ["首頁", "審核與管理", "綜合查詢", "操作紀錄"])
    
    st.markdown("---")
    if st.button("登出"):
        log_action(st.session_state.login_id, "登出", "使用者登出系統")
        st.session_state.clear()
        st.rerun()

# ==========================================
# 4. 主畫面邏輯
# ==========================================
conn = get_db_connection()
try:
    if menu == "首頁":
        st.header("📊 首頁")
        
        if st.session_state.role == 'L5':
            col1, col2 = st.columns([2, 1])
            with col1:
                st.markdown(f"**所屬單位：** {st.session_state.squadron} - {st.session_state.unit}")
                if st.session_state.discharge_date:
                    d_date = datetime.strptime(str(st.session_state.discharge_date), '%Y-%m-%d').date()
                    today = datetime.now().date()
                    days_left = (d_date - today).days
                    if days_left < 0:
                        st.error(f"🚨 已逾結訓日！請盡速完成裝備歸還。")
                    elif days_left <= 1:
                        st.error(f"🚨 結訓倒數：{days_left} 天！請立即處理未歸還準則。")
                    elif days_left <= 3:
                        st.warning(f"⚠️ 結訓倒數：{days_left} 天！請準備歸還準則。")
                    else:
                        st.info(f"📅 距離結訓日還有：{days_left} 天")
                
                # L5：待領取準則填寫
                pending_claim = pd.read_sql_query(f"SELECT id, book_name FROM books WHERE owner_id='{st.session_state.login_id}' AND status='保留待領取'", conn)
                if not pending_claim.empty:
                    st.warning("⚠️ 您有已核准但尚未綁定序號的準則！請對照實體書進行批次登錄。")
                    grouped = pending_claim.groupby('book_name')
                    with st.form("batch_claim_form"):
                        st.info("💡 若部分準則【尚未發下來】，請直接將該欄位「留空」，系統會自動為您保留該筆額度以便後續登錄。")
                        claim_data = {}
                        for book_name, group in grouped:
                            qty = len(group)
                            st.markdown(f"**📘 {book_name}** (待領額度：**{qty}** 本)")
                            serials_str = st.text_input("請輸入實體序號 (多本請用逗號 , 隔開)", key=f"serials_{book_name}", placeholder="例如: M2A2001, M2A2002")
                            # 優化文字，清楚區分「還沒拿到」與「確定短少」
                            is_short = st.checkbox(f"☑️ 異常回報：若確定「不會再領到」剩下的書才勾選此項 (系統會註銷剩餘額度退回庫房)", key=f"short_{book_name}")
                            st.markdown("---")
                            claim_data[book_name] = {
                                "ids": group['id'].tolist(),
                                "serials_str": serials_str,
                                "is_short": is_short,
                                "qty": qty
                            }
                            
                        if st.form_submit_button("💾 確認送出實領準則"):
                            c = conn.cursor()
                            has_error = False
                            
                            for b_name, data in claim_data.items():
                                raw_serials = [s.strip() for s in data["serials_str"].split(',') if s.strip()]
                                entered_qty = len(raw_serials)
                                approved_qty = int(data["qty"])
                                ids = data["ids"]
                                
                                # 1. 數量超過防呆
                                if entered_qty > approved_qty:
                                    st.error(f"❌ {b_name} 輸入的序號數量 ({entered_qty}本) 超過待領額度 ({approved_qty}本)！")
                                    has_error = True
                                    break
                                
                                # 2. 【全新擴充】完全沒填且沒勾少領 -> 代表這科還沒發，直接跳過保留原狀
                                if entered_qty == 0 and not data["is_short"]:
                                    continue
                                
                                # 3. 處理資料庫更新
                                for i in range(approved_qty):
                                    placeholder_id = int(ids[i])
                                    
                                    # 針對有填寫實體序號的部分，進行過戶與綁定
                                    if i < entered_qty:
                                        new_serial = raw_serials[i]
                                        c.execute("SELECT id, status FROM books WHERE serial_number=%s", (new_serial,))
                                        exist_check = c.fetchone()
                                        
                                        if exist_check:
                                            if exist_check[1] == '在庫':
                                                c.execute(f"UPDATE books SET status='借閱中', owner_id='{st.session_state.login_id}' WHERE id={int(exist_check[0])}")
                                                c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id={placeholder_id}")
                                            else:
                                                st.error(f"❌ 衝突！序號 {new_serial} 已被借閱中！")
                                                has_error = True
                                                break
                                        else:
                                            c.execute("UPDATE books SET serial_number=%s, status='借閱中' WHERE id=%s", (new_serial, placeholder_id))
                                    
                                    # 針對沒填寫到序號的額度（即 i >= entered_qty）
                                    else:
                                        if data["is_short"]:
                                            # 有勾選異常回報 -> 標記為少領異常，等待幹部退庫結案
                                            c.execute(f"UPDATE books SET status='少領異常' WHERE id={placeholder_id}")
                                        else:
                                            # 沒勾選 -> 代表晚點才會拿到，不更新狀態，讓它繼續維持 '保留待領取'
                                            pass
                                            
                            if not has_error:
                                conn.commit()
                                log_action(st.session_state.login_id, "領取綁定", "完成待領取準則之序號分批/完整綁定")
                                st.success("✅ 序號綁定完成！庫房已自動配對更新。")
                                import time
                                time.sleep(1.5)
                                st.rerun()
                
                # L5：我的持有清單
                st.markdown("#### 📦 我的持有清單")
                agg_df = pd.read_sql_query(f"SELECT book_name as 書名, COUNT(*) as 總數量 FROM books WHERE owner_id='{st.session_state.login_id}' AND status='借閱中' GROUP BY book_name", conn)
                if agg_df.empty:
                    st.info("目前名下無任何借閱準則。")
                else:
                    st.dataframe(agg_df, use_container_width=True)

                my_books = pd.read_sql_query(f"SELECT id, book_name as 書名, serial_number as 序號 FROM books WHERE owner_id='{st.session_state.login_id}' AND status='借閱中'", conn)
                if not my_books.empty:
                    st.markdown("#### 🔧 自主修改實體序號")
                    st.info("💡 若發現系統紀錄的序號與實體書不符，請點擊下方對應的準則展開修改。")
                    edited_dfs = {}
                    for b_name in my_books['書名'].unique():
                        with st.expander(f"📘 點擊展開修改：{b_name}"):
                            b_df = my_books[my_books['書名'] == b_name].reset_index(drop=True)
                            edited_dfs[b_name] = st.data_editor(b_df, hide_index=True, disabled=["id", "書名"], width='stretch', key=f"edit_my_{b_name}")
                            
                    if st.button("💾 批次修正所有序號"):
                        c = conn.cursor()
                        has_err = False
                        
                        for b_name, edited_df in edited_dfs.items():
                            original_df = my_books[my_books['書名'] == b_name].reset_index(drop=True)
                            for index, row in edited_df.iterrows():
                                old_serial = str(original_df.iloc[index]['序號']).strip()
                                new_serial = str(row['序號']).strip()
                                book_id = int(row['id']) 
                                
                                if old_serial != new_serial:
                                    if not new_serial:
                                        st.error(f"❌ 【{b_name}】的序號不可改為空白！")
                                        has_err = True
                                        break
                                    
                                    c.execute("SELECT id, status, owner_id FROM books WHERE serial_number=%s", (new_serial,))
                                    exist_check = c.fetchone()
                                    
                                    if exist_check:
                                        exist_id, exist_status, exist_owner = exist_check
                                        if exist_status == '在庫':
                                            c.execute(f"UPDATE books SET status='借閱中', owner_id='{st.session_state.login_id}' WHERE id={int(exist_id)}")
                                            c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id={book_id}")
                                            
                                            now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                            c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "序號綁定", f"將佔位符 {old_serial} 退回庫房，綁定真實庫存 {new_serial}"))
                                        else:
                                            st.error(f"❌ 衝突！序號 【{new_serial}】 正被【{exist_owner}】借閱中！請確認實體書狀況。")
                                            has_err = True
                                            break
                                    else:
                                        c.execute("UPDATE books SET serial_number=%s WHERE id=%s", (new_serial, book_id))
                                        now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                        c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "修正序號", f"將 {b_name} 的序號 {old_serial} 修正為 {new_serial}"))
                                        
                            if has_err: break
                                
                        if not has_err:
                            conn.commit()
                            st.success("✅ 所有序號已修正！")
                            import time
                            time.sleep(1.5)
                            st.rerun()

                st.markdown("---")
                st.markdown("#### 📤 待幹部審核清單 (歸還中)")
                returning_books = pd.read_sql_query(f"SELECT book_name as 書名, serial_number as 序號 FROM books WHERE owner_id='{st.session_state.login_id}' AND status='歸還中'", conn)
                if not returning_books.empty:
                    st.info("⏳ 以下準則已送出歸還申請，正等待幹部審核。在審核完成前，請妥善保管實體準則。")
                    st.dataframe(returning_books, hide_index=True, use_container_width=True)
                else:
                    st.success("目前沒有等待幹部審核的準則。")

            # ======== 🟢 L5：訓員 (帳號安全，嚴格限制修改次數) ========
            with col2:
                st.markdown("#### ⚙️ 帳號安全與資料設定")
                st.write(f"免審核修改額度：**{st.session_state.setup_count} 次**")
                
                with st.form("l5_setup_form"):
                    st.info("💡 儲存後需重新登入。")
                    new_id = st.text_input("修改帳號 (Login ID)", value=st.session_state.login_id)
                    new_pwd = st.text_input("修改密碼 (必填)", type="password")
                    
                    if st.form_submit_button("確認修改"):
                        if not new_pwd:
                            st.warning("密碼為必填！")
                        elif st.session_state.setup_count > 0:
                            c = conn.cursor()
                            c.execute("SELECT COUNT(*) FROM users WHERE (login_id=%s OR pending_login_id=%s) AND id!=%s", (new_id, new_id, int(st.session_state.id)))
                            if c.fetchone()[0] > 0:
                                st.error("❌ 帳號已被其他人使用，請更換！")
                            else:
                                old_login_id = st.session_state.login_id 
                                try:
                                    c.execute("UPDATE users SET login_id=%s, password=%s, setup_count=0 WHERE id=%s", (new_id, new_pwd, int(st.session_state.id)))
                                    c.execute("UPDATE books SET owner_id=%s WHERE owner_id=%s", (new_id, old_login_id))
                                    c.execute("UPDATE borrow_requests SET login_id=%s WHERE login_id=%s", (new_id, old_login_id))
                                    c.execute("UPDATE action_logs SET user_id=%s WHERE user_id=%s", (new_id, old_login_id))
                                    
                                    conn.commit() 
                                    
                                    now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                    c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, new_id, "資料修改", "修改了帳密並同步過戶名下所有準則"))
                                    conn.commit()
                                    
                                    st.success("✅ 修改成功！所有準則已隨帳號轉移。系統將自動登出...")
                                    import time
                                    time.sleep(2)
                                    for key in list(st.session_state.keys()): del st.session_state[key]
                                    st.rerun()
                                except Exception as e:
                                    conn.rollback() 
                                    st.error(f"❌ 寫入異常。錯誤碼: {e}")
                        else:
                            st.error("❌ 您的修改額度已用畢。")

        # ======== 🟢 L4：區隊長/文書兵 (戰情看板 + 姓名/帳密修改) ========
        elif st.session_state.role == 'L4':
            col1, col2 = st.columns([2, 1])
            with col1:
                st.markdown(f"**{display_name}**長官好，以下為今日概況：")
                sq_list = [s.strip() for s in st.session_state.squadron.split(',')]
                sq_in_clause = "'" + "','".join(sq_list) + "'"
                
                pending_reg = pd.read_sql_query(f"SELECT COUNT(*) FROM users WHERE status='待審核' AND squadron IN ({sq_in_clause})", conn).iloc[0,0]
                pending_bor = pd.read_sql_query(f"SELECT COUNT(*) FROM borrow_requests br JOIN users u ON br.login_id = u.login_id WHERE br.status='待審核' AND u.squadron IN ({sq_in_clause})", conn).iloc[0,0]
                pending_ret = pd.read_sql_query(f"SELECT COUNT(*) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='歸還中' AND u.squadron IN ({sq_in_clause})", conn).iloc[0,0]
                pending_abn = pd.read_sql_query(f"SELECT COUNT(*) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='少領異常' AND u.squadron IN ({sq_in_clause})", conn).iloc[0,0]
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("📝 待開通帳號", f"{pending_reg} 件")
                c2.metric("📥 待核准借閱", f"{pending_bor} 件")
                c3.metric("📤 待審核準則", f"{pending_ret} 件")
                c4.metric("🔴 領取異常警示", f"{pending_abn} 件")
            
            with col2:
                st.markdown("#### ⚙️ 帳密設置")
                st.write(f"姓名免審核修改額度：**{st.session_state.setup_count} 次**")
                if st.session_state.get('pending_name'):
                    st.warning("⏳ 您的申請已送出，等待中隊長核准。核准前請繼續以原帳號辦公。")
                
                with st.form("l4_setup_form"):
                    st.info("💡 第一次登入請修改真實姓名與專屬帳號。後續交接將送交中隊長審核。")
                    new_name = st.text_input("姓名(第一次更改免審，改帳密不要動這格)", value=st.session_state.name)
                    new_id = st.text_input("新帳號(無更改次數限制)", value=st.session_state.login_id)
                    new_pwd = st.text_input("新密碼(無更改次數限制)", type="password")
                    
                    if st.form_submit_button("送出變更"):
                        if not new_pwd:
                            st.error("請輸入新密碼！")
                        else:
                            c = conn.cursor()
                            uid = int(st.session_state.id)
                            final_name = new_name.strip() if new_name.strip() else st.session_state.name
                            final_id = new_id.strip() if new_id.strip() else st.session_state.login_id
                            
                            c.execute("SELECT COUNT(*) FROM users WHERE (login_id=%s OR pending_login_id=%s) AND id!=%s", (final_id, final_id, uid))
                            if c.fetchone()[0] > 0:
                                st.error("❌ 申請失敗！此【專屬帳號】已被佔用或被圈存申請中！")
                            else:
                                if st.session_state.setup_count > 0:
                                    c.execute("UPDATE users SET name=%s, login_id=%s, password=%s, setup_count=0 WHERE id=%s", (final_name, final_id, new_pwd, uid))
                                    conn.commit()
                                    log_action(st.session_state.login_id, "幹部實名設定", f"設定姓名為 {final_name}")
                                    st.success("✅ 設定成功！請使用新帳密重新登入。")
                                    import time
                                    time.sleep(1.5)
                                    st.session_state.clear()
                                    st.rerun()
                                else:
                                    if final_name != st.session_state.name:
                                        c.execute("UPDATE users SET login_id=%s, password=%s, pending_name=%s WHERE id=%s", (final_id, new_pwd, final_name, uid))
                                        conn.commit()
                                        log_action(st.session_state.login_id, "提出交接申請", f"申請移交給 {final_name}")
                                        st.success("✅ 帳號與密碼已生效！【姓名】已提交給中隊長等待核准。")
                                        import time
                                        time.sleep(1.5)
                                        st.session_state.clear() 
                                        st.rerun()
                                    else:
                                        c.execute("UPDATE users SET login_id=%s, password=%s, pending_name=NULL, pending_login_id=NULL WHERE id=%s", (final_id, new_pwd, uid))
                                        conn.commit()
                                        st.success("✅ 帳號與密碼修改成功。")
                                        import time
                                        time.sleep(1.5)
                                        st.session_state.clear() 
                                        st.rerun()

        # ======== 🟢 L2 & L3：大隊部/中隊部 (純修改帳密，無次數限制) ========
        elif st.session_state.role in ['L2', 'L3']:
            st.markdown("#### ⚙️ 高階幹部專屬帳密設置")
            with st.form("l23_setup_form"):
                st.info("💡 高階幹部可無限次修改您的「專屬帳號」與「密碼」。")
                new_id = st.text_input("新帳號", value=st.session_state.login_id)
                new_pwd = st.text_input("新密碼 (必填)", type="password")
                
                if st.form_submit_button("確認修改"):
                    if not new_pwd:
                        st.error("請輸入新密碼！")
                    else:
                        c = conn.cursor()
                        uid = int(st.session_state.id)
                        final_id = new_id.strip() if new_id.strip() else st.session_state.login_id
                        
                        c.execute("SELECT COUNT(*) FROM users WHERE (login_id=%s OR pending_login_id=%s) AND id!=%s", (final_id, final_id, uid))
                        if c.fetchone()[0] > 0:
                            st.error("❌ 修改失敗！此帳號已被他人使用！")
                        else:
                            # 繞過免審額度，直接強制覆蓋寫入資料庫
                            c.execute("UPDATE users SET login_id=%s, password=%s WHERE id=%s", (final_id, new_pwd, uid))
                            conn.commit()
                            st.success("✅ 帳號與密碼修改成功！系統將自動登出...")
                            import time
                            time.sleep(1.5)
                            st.session_state.clear() 
                            st.rerun()
        else:
            st.markdown(f"**{display_name}**，長官好今日概況良好。")

    elif menu == "準則借閱" and st.session_state.role == 'L5':
        st.header("📥 準則借閱與回報")
        
        # 🚀 升級三標籤：加入每日清點回報
        tabs_l5_borrow = st.tabs(["📚 借閱申請", "💬 Line 借還書回報", "📱 Line 準則清點回報"])
        
        # ======== 🟢 分頁 1：原本的借閱申請邏輯 ========
        with tabs_l5_borrow[0]:
            if 'borrow_success' in st.session_state:
                st.success(st.session_state.borrow_success)

            stock_df = pd.read_sql_query("SELECT book_name as 書名, COUNT(*) as 可用庫存 FROM books WHERE status='在庫' GROUP BY book_name", conn)
            if not stock_df.empty:
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.dataframe(stock_df, hide_index=True)
                with col2:
                    book_choice = st.selectbox("選擇需要借閱的準則", stock_df['書名'].tolist())
                    max_stock = int(stock_df[stock_df['書名'] == book_choice]['可用庫存'].iloc[0])
                    qty = st.number_input("申請數量 (已鎖定最高可用庫存)", min_value=1, max_value=max_stock, value=1)
                    
                    c = conn.cursor()
                    c.execute(f"SELECT COUNT(*) FROM books WHERE owner_id='{st.session_state.login_id}' AND book_name='{book_choice}' AND status!='在庫'")
                    total_existing = int(c.fetchone()[0])
                    
                    can_submit = True
                    if total_existing > 0:
                        st.info(f"已重複借閱 **{total_existing}** 本此準則。")
                        confirm_extra = st.checkbox("☑️ 我已知有此本準則，此為「缺少數量再額外申請」 (打勾後即可送出)", key="chk_extra_borrow")
                        if not confirm_extra:
                            can_submit = False
                    
                    if can_submit:
                        if st.button("✅ 送出借閱申請"):
                            c = conn.cursor()
                            c.execute("INSERT INTO borrow_requests (login_id, unit, book_name, quantity, status) VALUES (%s,%s,%s,%s,%s)",
                                      (st.session_state.login_id, st.session_state.unit, book_choice, int(qty), '待審核'))
                            
                            c.execute(f"SELECT id FROM books WHERE book_name='{book_choice}' AND status='在庫' LIMIT {qty}")
                            book_ids = [str(b[0]) for b in c.fetchall()]
                            if book_ids:
                                c.execute(f"UPDATE books SET status='審核中(已圈存)', owner_id='{st.session_state.login_id}' WHERE id IN ({','.join(book_ids)})")
                                
                            now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                            c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "送出借閱", f"申請並圈存 {book_choice} 共 {qty} 本"))
                            conn.commit()
                            
                            if 'chk_extra_borrow' in st.session_state: del st.session_state['chk_extra_borrow']
                            st.session_state.borrow_success = f"✅ 已成功送出申請：{book_choice} 共 {qty} 本！，請等待文書兵核准發放。"
                            st.rerun()

        # ======== 🟢 分頁 2：Line 借還書報表生成 ========
        with tabs_l5_borrow[1]:
            st.subheader("💬 Line 借還書回報")
            st.info("💡 請在送出申請後，點擊下方按鈕產生回報文字，並複製貼至 Line 群組。")
            
            # 🚀 升級：下拉式選單
            report_cadre = st.selectbox("回報對象", ["文書兵", "分隊長", "區隊長"], key="borrow_cadre")
            
            if st.button("🚀 生成借還書清單", type="primary"):
                my_id = st.session_state.login_id
                my_unit = st.session_state.unit
                
                # 1. 抓取剛剛送出的「待審核」借閱
                br_df = pd.read_sql_query(f"SELECT book_name, quantity FROM borrow_requests WHERE login_id='{my_id}' AND status='待審核'", conn)
                
                # 2. 抓取目前點選的「歸還中」書目
                rt_df = pd.read_sql_query(f"SELECT book_name FROM books WHERE owner_id='{my_id}' AND status='歸還中'", conn)
                
                # 🚀 升級：對齊軍規報告格式
                msg_l5 = f"報告{report_cadre}\n"
                msg_l5 += f"班隊名稱：{my_unit}\n"
                msg_l5 += "借還書清單：\n\n"
                
                # 借閱區塊
                msg_l5 += "【申請借閱】：\n"
                if not br_df.empty:
                    for _, r in br_df.iterrows():
                        msg_l5 += f"{r['book_name']}*{r['quantity']}\n"
                else:
                    msg_l5 += "無\n"
                    
                # 歸還區塊
                msg_l5 += "\n【申請歸還】：\n"
                if not rt_df.empty:
                    rt_group = rt_df.groupby('book_name').size()
                    for b_name, count in rt_group.items():
                        msg_l5 += f"{b_name}*{count}\n"
                else:
                    msg_l5 += "無\n"
                    
                st.success("✨ 回報文字生成完畢！請點擊下方框框全選複製：")
                st.text_area("借還書複製區", value=msg_l5.strip(), height=300, key="borrow_area")

        # ======== 🟢 分頁 3：Line 準則清點回報 ========
        with tabs_l5_borrow[2]:
            st.subheader("📱 Line 準則清點回報")
            st.info("💡 產生目前名下所有「借閱中」準則的序號清單，方便每日清點回報。")
            
            # 🚀 升級：下拉式選單
            inv_cadre = st.selectbox("回報對象", ["文書兵", "分隊長", "區隊長"], key="inv_cadre")
            
            if st.button("🚀 生成清點報表", type="primary", key="btn_inv_report"):
                my_id = st.session_state.login_id
                my_unit = st.session_state.unit
                
                inv_df = pd.read_sql_query(f"SELECT book_name, serial_number FROM books WHERE owner_id='{my_id}' AND status='借閱中'", conn)
                
                # 🚀 升級：對齊軍規報告格式
                inv_msg = f"報告{inv_cadre}\n"
                inv_msg += f"班隊名稱：{my_unit}\n"
                inv_msg += "準則清點：\n\n"
                
                if inv_df.empty:
                    inv_msg += "目前名下無借閱中準則。\n"
                else:
                    grouped = inv_df.groupby('book_name')
                    for b_name, group in grouped:
                        qty = len(group)
                        serials = group['serial_number'].tolist()
                        serials_str = ",".join([str(s).strip() for s in serials])
                        
                        inv_msg += f"{b_name}*{qty}\n"
                        inv_msg += f"{serials_str}\n\n"
                        
                st.success("✨ 清點回報文字生成完畢！請全選複製貼至 Line：")
                st.text_area("清點複製區", value=inv_msg.strip(), height=300, key="inv_text_area")
                
    elif menu == "準則歸還" and st.session_state.role == 'L5':
        st.header("📤 準則歸還")
        books_df = pd.read_sql_query(f"SELECT id, book_name as 書名, serial_number as 序號 FROM books WHERE owner_id='{st.session_state.login_id}' AND status='借閱中'", conn)
        
        if not books_df.empty:
            st.info("💡 【快捷歸還】：勾選各準則標題旁的「☑️ 全數歸還此項」即可將該類準則全數歸還。\n💡 【部分歸還】：展開個別序號清單，單獨勾選要歸還的序號。")
            
            # === 🚀 終極防護：建立「跨區塊記憶保險箱」 ===
            if 'l5_partial_return_memory' not in st.session_state:
                st.session_state['l5_partial_return_memory'] = {}
                
            # 🛡️ 步驟 1：在畫面重繪前，攔截所有被勾選的單獨序號，存入保險箱
            for b_name in books_df['書名'].unique():
                editor_key = f"return_editor_{b_name}"
                if editor_key in st.session_state:
                    edits = st.session_state[editor_key].get("edited_rows", {})
                    temp_df = books_df[books_df['書名'] == b_name].reset_index(drop=True)
                    for r_idx_str, edit_dict in edits.items():
                        if "勾選歸還" in edit_dict:
                            r_idx = int(r_idx_str)
                            if r_idx < len(temp_df):
                                book_id = temp_df.at[r_idx, 'id']
                                # 寫入記憶
                                st.session_state['l5_partial_return_memory'][book_id] = edit_dict["勾選歸還"]

            category_checks = {} 
            edited_return_dfs = {}
            
            # 繪製畫面
            for b_name in books_df['書名'].unique():
                b_df = books_df[books_df['書名'] == b_name].reset_index(drop=True)
                qty = len(b_df)
                
                st.markdown(f"### 📘 {b_name}")
                col_chk, col_exp = st.columns([2.5, 7.5])
                
                with col_chk:
                    # 每項準則獨立的「全還」按鈕
                    category_checks[b_name] = st.checkbox(f"☑️ 全數歸還此項 ({qty}本)", key=f"all_ret_{b_name}")
                    
                with col_exp:
                    with st.expander(f"🔽 展開個別序號 (點擊查看)"):
                        if category_checks[b_name]:
                            # 如果外面勾了全選，裡面就直接顯示提示，鎖定個別操作
                            st.success(f"✨ 已選擇全數歸還！送出後將一併歸還這 {qty} 本準則。")
                            edited_return_dfs[b_name] = None 
                        else:
                            # 🛡️ 步驟 2：從保險箱讀取記憶，精準還原每一本書剛剛的勾選狀態
                            initial_checks = []
                            for _, row in b_df.iterrows():
                                b_id = row['id']
                                initial_checks.append(st.session_state['l5_partial_return_memory'].get(b_id, False))
                                
                            b_df.insert(0, "勾選歸還", initial_checks)
                            editor_key = f"return_editor_{b_name}"
                            edited_return_dfs[b_name] = st.data_editor(
                                b_df, 
                                hide_index=True, 
                                disabled=["id", "書名", "序號"], 
                                width='stretch', 
                                key=editor_key
                            )
                st.markdown("---") # 加上分隔線，視覺更俐落
                
            # 唯一安全出口：送出按鈕
            if st.button("📤 送出目前的勾選項目", type="primary", use_container_width=True):
                selected_ids = []
                for b_name in books_df['書名'].unique():
                    if category_checks[b_name]:
                        # 該科目全選
                        full_b_df = books_df[books_df['書名'] == b_name]
                        selected_ids.extend(full_b_df["id"].tolist())
                    elif edited_return_dfs[b_name] is not None:
                        # 該科目部分勾選
                        edited_df = edited_return_dfs[b_name]
                        checked_rows = edited_df[edited_df["勾選歸還"] == True]
                        selected_ids.extend(checked_rows["id"].tolist())
                
                if selected_ids:
                    selected_ids = list(set(selected_ids)) 
                    id_list_str = ','.join(map(str, selected_ids))
                    
                    c = conn.cursor()
                    # 撈出勾選的項目有哪幾種書，各幾本
                    c.execute(f"SELECT book_name, COUNT(id) FROM books WHERE id IN ({id_list_str}) GROUP BY book_name")
                    return_details = c.fetchall()
                    
                    c.execute(f"UPDATE books SET status='歸還中' WHERE id IN ({id_list_str})")
                    now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 迴圈寫入標準格式
                    for b_name, qty in return_details:
                        c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
                                  (now_time, st.session_state.login_id, "申請歸還", f"申請 {st.session_state.unit} 歸還 {b_name} {qty} 本"))
                    conn.commit()
                    
                    if 'l5_partial_return_memory' in st.session_state: 
                        del st.session_state['l5_partial_return_memory']
                        
                    st.success(f"✅ 已送出 {len(selected_ids)} 本歸還申請！等待幹部審核。")
                    import time
                    time.sleep(1.5)
                    st.rerun()
                    
                    # 任務成功，銷毀保險箱
                    if 'l5_partial_return_memory' in st.session_state: 
                        del st.session_state['l5_partial_return_memory']
                        
                    st.success(f"✅ 已送出 {len(selected_ids)} 本歸還申請！等待幹部審核。")
                    import time
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.warning("⚠️ 您尚未勾選任何需要歸還的準則！")
        else:
            st.success("✨ 您名下目前沒有需要歸還的準則！")

    elif menu == "審核與管理" and st.session_state.role in ['L1', 'L2', 'L3', 'L4']:
        st.header("⚙️ 審核與管理後台")
        
        if st.session_state.role == 'L1':
            st.error("👑 系統管理員模式：可強制修改全域使用者資料")
            # 升級 1：在 SQL 查詢中正式加入 title(職務) 與 name(姓名)
            all_users = pd.read_sql_query("SELECT id, login_id, password, role, squadron, unit, title, name, status, setup_count FROM users ORDER BY id", conn)
            
            st.info("💡 提示：ID 與 系統階級(role) 鎖定防呆，其餘皆可直接點擊表格修改。")
            edited_u = st.data_editor(all_users, use_container_width=True, disabled=["id", "role"], key="l1_admin_editor")
            
            if st.button("💾 強制儲存變更", type="primary"):
                c = conn.cursor()
                try:
                    for index, row in edited_u.iterrows():
                        # 升級 2：安全過濾空白欄位，避免表格裡的空白變成 "None" 字串寫入資料庫
                        safe_title = str(row['title']) if pd.notna(row['title']) else ""
                        safe_name = str(row['name']) if pd.notna(row['name']) else ""
                        safe_squadron = str(row['squadron']) if pd.notna(row['squadron']) else ""
                        safe_unit = str(row['unit']) if pd.notna(row['unit']) else ""
                        
                        # 升級 3：將職務(title)與姓名(name)正式接入寫入引擎
                        c.execute("""
                            UPDATE users 
                            SET login_id=%s, password=%s, squadron=%s, unit=%s, title=%s, name=%s, status=%s, setup_count=%s 
                            WHERE id=%s
                        """, (
                            str(row['login_id']), str(row['password']), 
                            safe_squadron, safe_unit, 
                            safe_title, safe_name,
                            str(row['status']), int(row['setup_count']), 
                            int(row['id'])
                        ))
                    conn.commit()
                    log_action("SYSTEM_L1", "上帝模式修改", "L1 強制覆蓋了全域使用者資料(含姓名與職務)")
                    st.success("✅ 資料庫已強制更新！")
                    import time
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"❌ 儲存失敗！可能有帳號重複或格式錯誤。詳細原因：{e}")

            # ==========================================
            # ✨ 新增：CSV 無損同步擴充引擎 (就接在儲存失敗的 except 下方)
            # ==========================================
            st.markdown("---")
            st.subheader("📥 準則資料庫擴充與同步")
            st.info("💡 當您更新了 GitHub 上的 `準則資料庫.csv` 後，點擊此按鈕即可將【新增加的書目或數量】匯入系統，不會影響現有的借閱紀錄。")
            
            if st.button("🔄 從最新 CSV 同步新增準則", type="primary", use_container_width=True):
                if CSV_FILE and os.path.exists(CSV_FILE):
                    try:
                        # 讀取 CSV
                        try:
                            df_books = pd.read_csv(CSV_FILE, encoding='big5')
                        except UnicodeDecodeError:
                            df_books = pd.read_csv(CSV_FILE, encoding='utf-8')
                            
                        c = conn.cursor()
                        insert_count = 0
                        skip_count = 0
                        
                        for index, row in df_books.iterrows():
                            if '書刊名稱' in row and pd.notna(row['書刊名稱']):
                                raw_title = str(row['書刊名稱']).strip()
                                
                                pub_date = ""
                                if '出版日期' in row and pd.notna(row['出版日期']):
                                    raw_date = str(row['出版日期']).strip()
                                    if raw_date.endswith('.0'): raw_date = raw_date[:-2]
                                    pub_date = raw_date
                                    
                                book_title = f"{raw_title} [{pub_date}]" if pub_date else raw_title
                                
                                qty = 1
                                if '數量' in row and pd.notna(row['數量']):
                                    qty = int(row['數量'])
                                elif '化訓準則館' in row and pd.notna(row['化訓準則館']):
                                    qty = int(row['化訓準則館'])
                                    
                                for i in range(1, qty + 1):
                                    serial = f"{book_title}-{i:03d}"
                                    
                                    # 🚀 神級防呆：ON CONFLICT DO NOTHING
                                    # 因為我們現在使用 psycopg2 原生 SQL 寫法，要先確定資料表有 UNIQUE 約束
                                    # 我們改用更安全的先 SELECT 後 INSERT 寫法，確保相容性
                                    c.execute("SELECT id FROM books WHERE serial_number=%s", (serial,))
                                    if not c.fetchone():
                                        c.execute("""
                                            INSERT INTO books (book_name, serial_number, owner_id, status) 
                                            VALUES (%s, %s, %s, %s)
                                        """, (book_title, serial, '在庫', '在庫'))
                                        insert_count += 1
                                    else:
                                        skip_count += 1
                                        
                        conn.commit()
                        st.success(f"✅ 同步完成！成功從 CSV 新增了 **{insert_count}** 本全新準則，並安全略過了 {skip_count} 本已存在的準則。")
                        
                        tz_tw = timezone(timedelta(hours=8))
                        now_time = datetime.now(tz_tw).strftime("%Y-%m-%d %H:%M:%S")
                        log_action("SYSTEM_L1", "CSV 擴充同步", f"管理員執行同步，新增了 {insert_count} 本準則")
                        
                    except Exception as e:
                        conn.rollback()
                        st.error(f"❌ 同步失敗，請檢查 CSV 格式。詳細原因：{e}")
                else:
                    st.error("❌ 系統找不到 CSV 檔案！請確認 GitHub 上的檔案名稱是否包含「準則資料庫」且副檔名為 .csv。")
                            
        elif st.session_state.role == 'L3':
            st.subheader("中隊後台")
            pending_l4 = pd.read_sql_query(f"SELECT id, title as 職務, name as 原姓名, pending_name as 申請新姓名 FROM users WHERE role='L4' AND squadron='{st.session_state.squadron}' AND pending_name IS NOT NULL", conn)
            if not pending_l4.empty:
                st.warning("⚠️ 您有待核准的所屬幹部交接申請：")
                for idx, row in pending_l4.iterrows():
                    st.write(f"**{row['職務']} {row['原姓名']}** 申請將業務移交給 👉 **{row['申請新姓名']}**")
                    colA, colB, colC = st.columns([1,1,3])
                    with colA:
                        if st.button("✅ 核准替換", key=f"app_{row['id']}"):
                            c = conn.cursor()
                            c.execute("UPDATE users SET name=%s, pending_name=NULL WHERE id=%s", (row['申請新姓名'], int(row['id'])))
                            conn.commit()
                            log_action(st.session_state.login_id, "核准交接", f"核准 {row['職務']} 交接給 {row['申請新姓名']}")
                            st.success("✅ 已核准！交接完成。")
                            import time
                            time.sleep(1.5)
                            st.rerun()
                    with colB:
                        if st.button("❌踢退", key=f"rej_{row['id']}"):
                            c = conn.cursor()
                            c.execute("UPDATE users SET pending_name=NULL WHERE id=%s", (int(row['id']),))
                            conn.commit()
                            st.success("✅ 已踢退該交接申請。")
                            st.rerun()
                st.markdown("---")
            else:
                st.info("✅ 目前無待核准的幹部交接申請。")
            
            st.markdown("#### 👥 訓員(L5)班隊管理")
            l5_users = pd.read_sql_query(f"SELECT id, squadron as 中隊, unit as 班隊, login_id as 帳號, setup_count as 免審額度 FROM users WHERE role='L5' AND squadron='{st.session_state.squadron}'", conn)
            tabs = st.tabs(["班隊中隊調整", "帳密修改權限"])
            with tabs[0]:
                if not l5_users.empty:
                    edited_l5 = st.data_editor(
                        l5_users, hide_index=True, disabled=["id", "帳號", "免審額度"], use_container_width=True,
                        column_config={"中隊": st.column_config.SelectboxColumn("所屬中隊", options=["學生一中隊", "學生二中隊", "學員一中隊", "學員二中隊"], required=True), "班隊": st.column_config.TextColumn("受訓全銜", required=True)}
                    )
                    if st.button("💾 儲存資料"):
                        c = conn.cursor()
                        for index, row in edited_l5.iterrows():
                            c.execute(f"UPDATE users SET squadron='{row['中隊']}', unit='{row['班隊']}' WHERE id={int(row['id'])}")
                        conn.commit()
                        st.success("✅ 資料已更新！")
                        st.rerun()
                else:
                    st.info("尚未有任何屬於您的訓員(L5)註冊資料。")
            with tabs[1]:
                if not l5_users.empty:
                    grant_df = l5_users[['id', '中隊', '班隊', '帳號', '免審額度']].copy()
                    grant_df.insert(0, "勾選", False)
                    edited_grant = st.data_editor(grant_df, hide_index=True)
                    sel_grant = edited_grant[edited_grant["勾選"] == True]["id"].tolist()
                    if st.button("🔓 批次發放 1 次修改權限") and sel_grant:
                        c = conn.cursor()
                        c.execute(f"UPDATE users SET setup_count=1 WHERE id IN ({','.join(map(str, sel_grant))})")
                        conn.commit()
                        st.success("✅ 已成功下放修改額度給勾選的班隊！")
                        st.rerun()
                else:
                    st.info("目前無資料可發放權限。")

        elif st.session_state.role == 'L4':
            is_doc = "人事" in st.session_state.title or "文書" in st.session_state.title
            tabs = st.tabs(["註冊開通", "準則借閱核准", "準則歸還", "結訓日與帳密修改", "💬 line借還書回報"]) if is_doc else st.tabs(["註冊開通", "準則歸還", "結訓日與帳密修改", "💬 Line借還書回報"])
            sq_list = [s.strip() for s in st.session_state.squadron.split(',')]
            sq_in_clause = "'" + "','".join(sq_list) + "'"
                
            with tabs[0]:
                st.subheader("📝 班隊註冊開通")
                reg_df = pd.read_sql_query(f"SELECT id, squadron as 中隊, unit as 班隊, login_id as 帳號, discharge_date as 結訓日 FROM users WHERE status='待審核' AND squadron IN ({sq_in_clause})", conn)
                if not reg_df.empty:
                    reg_df.insert(0, "核准", False)
                    edited_reg = st.data_editor(reg_df, hide_index=True)
                    sel_reg = edited_reg[edited_reg["核准"] == True]["id"].tolist()
                    if st.button("✅ 批次開通勾選帳號") and sel_reg:
                        c = conn.cursor()
                        c.execute(f"UPDATE users SET status='啟用' WHERE id IN ({','.join(map(str, sel_reg))})")
                        conn.commit()
                        st.success("已成功開通！")
                        st.rerun()
                else:
                    st.info("目前無待審核的註冊。")
                    
            if is_doc:
                with tabs[1]:
                    st.subheader("📚 準則批次核准 (發放額度與砍單)")
                    req_df = pd.read_sql_query(f"SELECT br.id as 單號, br.login_id as 帳號, br.unit as 班隊, br.book_name as 書名, br.quantity as 申請數量 FROM borrow_requests br JOIN users u ON br.login_id = u.login_id WHERE br.status='待審核' AND u.squadron IN ({sq_in_clause}) ORDER BY br.unit, br.book_name, br.id", conn)
                    
                    if not req_df.empty:
                        # === 🚀 終極防護 1：建立記憶保險箱，在表格被洗掉前先存檔 ===
                        if 'saved_req_qty' not in st.session_state:
                            st.session_state['saved_req_qty'] = {}
                            
                        if "req_batch_editor_v2" in st.session_state:
                            edits = st.session_state["req_batch_editor_v2"].get("edited_rows", {})
                            for r_idx, edit_dict in edits.items():
                                try:
                                    idx_int = int(r_idx)
                                    if "核准數量" in edit_dict and idx_int < len(req_df):
                                        req_id = req_df.at[idx_int, '單號'] # 綁定唯一單號
                                        st.session_state['saved_req_qty'][req_id] = edit_dict['核准數量']
                                except Exception:
                                    pass
                        # ============================================================

                        owned_counts = []
                        c = conn.cursor()
                        for _, row in req_df.iterrows():
                            c.execute(f"SELECT COUNT(*) FROM books WHERE owner_id='{row['帳號']}' AND book_name='{row['書名']}' AND status IN ('借閱中', '保留待領取', '少領異常')")
                            owned_counts.append(c.fetchone()[0])
                        
                        req_df.insert(4, "已持有數", owned_counts)
                        
                        col_info, col_chk = st.columns([3, 1])
                        with col_info: st.info("💡 提示：若需「砍單」，請修改【核准數量】(填 0 代表踢退)。")
                        with col_chk:
                            st.write("") 
                            select_all = st.checkbox("☑️ 全選所有準則")
                            
                        req_df.insert(0, "勾選", select_all)
                        req_df['核准數量'] = req_df['申請數量'] 
                        
                        # === 🚀 終極防護 2：表格重繪前，把保險箱裡的數字無縫倒回去 ===
                        for i, row in req_df.iterrows():
                            req_id = row['單號']
                            if req_id in st.session_state['saved_req_qty']:
                                req_df.at[i, '核准數量'] = st.session_state['saved_req_qty'][req_id]
                        # ============================================================
                        
                        edited_req = st.data_editor(
                            req_df, hide_index=True, disabled=["單號", "帳號", "班隊", "書名", "申請數量", "已持有數"], width='stretch',  
                            column_config={
                                "勾選": st.column_config.CheckboxColumn("勾選"), 
                                "核准數量": st.column_config.NumberColumn("核准(可修改)", min_value=0),
                                "單號": None, "帳號": None
                            },
                            key="req_batch_editor_v2" 
                        )
                        sel_reqs = edited_req[edited_req["勾選"] == True]
                        
                        if st.button("✅ 批次送出勾選的準則", type="primary"):
                            if not sel_reqs.empty:
                                c = conn.cursor()
                                for idx, row in sel_reqs.iterrows():
                                    req_id = int(row['單號'])
                                    req_login = str(row['帳號'])
                                    req_book = str(row['書名'])
                                    req_qty = int(row['申請數量'])
                                    approve_qty = int(row['核准數量'])
                                    if approve_qty > req_qty: approve_qty = req_qty
                                    if approve_qty < 0: approve_qty = 0
                                        
                                    c.execute(f"SELECT id FROM books WHERE book_name='{req_book}' AND status='審核中(已圈存)' AND owner_id='{req_login}' LIMIT {req_qty}")
                                    reserved_ids = [b[0] for b in c.fetchall()]
                                    approved_ids = reserved_ids[:approve_qty]
                                    rejected_ids = reserved_ids[approve_qty:]
                                    
                                    if approved_ids: c.execute(f"UPDATE books SET status='保留待領取' WHERE id IN ({','.join(map(str, approved_ids))})")
                                    if rejected_ids: c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id IN ({','.join(map(str, rejected_ids))})")
                                        
                                    now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                    if approve_qty > 0:
                                        c.execute(f"UPDATE borrow_requests SET status='已核准(實發{approve_qty}本)' WHERE id={req_id}")
                                        c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "核准借閱", f"核准 {req_book} {approve_qty} 本給 {row['班隊']}"))
                                    else:
                                        c.execute(f"UPDATE borrow_requests SET status='已踢退(砍單退件)' WHERE id={req_id}")
                                        c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "踢退借閱", f"全數踢退 {row['班隊']} 的 {req_book} 申請"))
                                
                                conn.commit()
                                
                                # 🚀 任務完成，將雙重記憶體徹底銷毀
                                if "req_batch_editor_v2" in st.session_state:
                                    del st.session_state["req_batch_editor_v2"]
                                if "saved_req_qty" in st.session_state:
                                    del st.session_state["saved_req_qty"]
                                    
                                st.success(f"✅ 批次審核完成！共處理 {len(sel_reqs)} 本準則。")
                                import time
                                time.sleep(1.5)
                                st.rerun()
                            else:
                                st.warning("⚠️ 請先在表格前方勾選要處理的準則！")
                    else:
                        st.info("目前無待審核的準則。")

                    st.markdown("---")
                    st.subheader("🔴 領取異常警示")
                    abnormal_df = pd.read_sql_query(f"SELECT b.id, u.unit as 班隊, b.book_name as 書名, b.serial_number as 序號 FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='少領異常' AND u.squadron IN ({sq_in_clause}) ORDER BY u.unit, b.book_name", conn)
                    
                    if not abnormal_df.empty:
                        st.error("⚠️ 發現訓員回報少領準則！請確認實體無誤後，將未領之額度釋放回庫房。")
                        edited_abn_dfs = {}
                        abn_checks = {}
                        for unit_name in abnormal_df['班隊'].unique():
                            st.markdown(f"### 🏢 異常單位：【{unit_name}】")
                            unit_df = abnormal_df[abnormal_df['班隊'] == unit_name]
                            for b_name in unit_df['書名'].unique():
                                b_df = unit_df[unit_df['書名'] == b_name].reset_index(drop=True)
                                qty = len(b_df)
                                u_key = f"abn_{unit_name}_{b_name}"
                                col_chk, col_exp = st.columns([1.5, 8.5])
                                with col_chk:
                                    st.write("")
                                    abn_checks[u_key] = st.checkbox(f"☑️ 全結案 ({qty}本)", key=f"abn_all_{u_key}")
                                with col_exp:
                                    with st.expander(f"📘 {b_name} (待釋放 {qty} 本)"):
                                        if abn_checks[u_key]:
                                            st.success(f"✨ 已勾選全數結案！這 {qty} 本準則將釋放回庫房。")
                                            edited_abn_dfs[u_key] = None
                                        else:
                                            b_df.insert(0, "✅ 結案", False)
                                            edited_abn_dfs[u_key] = st.data_editor(b_df, hide_index=True, disabled=["id", "班隊", "書名", "序號"], width='stretch', column_config={"✅ 結案": st.column_config.CheckboxColumn("✅ 結案(退庫)"), "id": None, "班隊": None, "書名": None}, key=f"abn_chk_{u_key}")
                            st.markdown("---")

                        if st.button("🔄 批次釋放勾選的異常庫存", type="primary"):
                            resolved_ids = []
                            for unit_name in abnormal_df['班隊'].unique():
                                unit_df = abnormal_df[abnormal_df['班隊'] == unit_name]
                                for b_name in unit_df['書名'].unique():
                                    u_key = f"abn_{unit_name}_{b_name}"
                                    if abn_checks[u_key]:
                                        full_b_df = unit_df[unit_df['書名'] == b_name]
                                        resolved_ids.extend(full_b_df["id"].tolist())
                                    elif edited_abn_dfs[u_key] is not None:
                                        checked_rows = edited_abn_dfs[u_key][edited_abn_dfs[u_key]["✅ 結案"] == True]
                                        resolved_ids.extend(checked_rows["id"].tolist())
                            if resolved_ids:
                                c = conn.cursor()
                                c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id IN ({','.join(map(str, resolved_ids))})")
                                now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "異常處理", f"將少領的 {len(resolved_ids)} 本額度釋放回庫房"))
                                conn.commit()
                                st.success(f"✅ 成功結案！已釋放 {len(resolved_ids)} 本準則回大庫房。")
                                import time
                                time.sleep(1.5)
                                st.rerun()
                            else:
                                st.warning("⚠️ 尚未勾選任何處理項目！")
                    else:
                        st.success("目前無異常少領通報。")

            return_tab = tabs[2] if is_doc else tabs[1]
            with return_tab:
                st.subheader("📥 準則歸還")
                return_df = pd.read_sql_query(f"SELECT b.id, u.unit as 班隊, b.book_name as 書名, b.serial_number as 序號, b.owner_id FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='歸還中' AND u.squadron IN ({sq_in_clause}) ORDER BY u.unit, b.book_name", conn)
                
                if not return_df.empty:
                    st.caption("**【快捷審核】**：班隊「✅ 全審核」或準則「✅ 審核」按鈕\n* **【單筆審核】**：點擊「🔽 展開序號」，勾選序號。")
                    
                    unit_actions = {}
                    book_actions = {}
                    edited_receive_dfs = {}
                    
                    for unit_name in return_df['班隊'].unique():
                        # ✨ 第一層：班隊專屬卡片
                        with st.container(border=True):
                            # 🚀 修復：### 後面加上空白，讓它變成真正的大標題！
                            st.markdown(f"##### 🏢 【{unit_name}】")
                            
                            # 🚀 特殊化：為班隊全收按鈕加上專屬提示與更長的文字
                            st.markdown("**🎯 班隊批次快捷操作：**")
                            unit_actions[unit_name] = st.radio(
                                f"【{unit_name}】批次處理",
                                ["🔽展開","✅全審核","❌全踢退"],
                                horizontal=True,
                                key=f"u_rad_{unit_name}",
                                label_visibility="collapsed"
                            )
                            
                            if unit_actions[unit_name] == "✅ 全審核":
                                st.success(f"✨ 將全數審核【{unit_name}】所有歸還準則！")
                            elif unit_actions[unit_name] == "❌ 全踢退":
                                st.error(f"🚨 將全數踢退【{unit_name}】所有歸還準則！")
                            else:
                                st.divider() # 畫一條線，隔開班隊總開關與底下書本明細
                                unit_df = return_df[return_df['班隊'] == unit_name]
                                for b_name in unit_df['書名'].unique():
                                    b_df = unit_df[unit_df['書名'] == b_name].reset_index(drop=True)
                                    qty = len(b_df)
                                    u_b_key = f"{unit_name}_{b_name}"
                                    
                                    # 🚀 降級：拿掉標題符號，改用普通粗體字，讓準則名稱不要太大
                                    st.markdown(f"**📘 {b_name}** (待處理 {qty} 本)")
                                    
                                    # 書本層級的按鈕維持精簡
                                    book_actions[u_b_key] = st.radio(
                                        f"{b_name} 處理",
                                        ["明細", "✅ 審核", "❌ 踢退"],
                                        horizontal=True,
                                        key=f"b_rad_{u_b_key}",
                                        label_visibility="collapsed"
                                    )
                                    
                                    if book_actions[u_b_key] == "✅ 審核":
                                        st.success(f"✨ 將全審核此項 {qty} 本！")
                                    elif book_actions[u_b_key] == "❌ 踢退":
                                        st.error(f"🚨 將全踢退此項 {qty} 本！")
                                    else:
                                        with st.expander("🔽 展開序號"):
                                            b_df.insert(0, "❌踢退", False)
                                            b_df.insert(0, "✅審核", False)
                                            edited_receive_dfs[u_b_key] = st.data_editor(
                                                b_df, 
                                                hide_index=True, 
                                                disabled=["id", "班隊", "書名", "序號", "owner_id"], 
                                                use_container_width=True, 
                                                column_config={
                                                    "✅審核": st.column_config.CheckboxColumn("✅審核"), 
                                                    "❌踢退": st.column_config.CheckboxColumn("❌踢退"), 
                                                    "id": None, "班隊": None, "書名": None, "owner_id": None
                                                }, 
                                                key=f"editor_{u_b_key}"
                                            )
                                    st.write("") # 增加項目間距
                    
                    st.markdown("---")
                    if st.button("💾 送出審核結果", type="primary", use_container_width=True):
                        received_ids = []
                        rejected_ids = []
                        
                        for unit_name in return_df['班隊'].unique():
                            if unit_actions[unit_name] == "✅ 全審核":
                                unit_df = return_df[return_df['班隊'] == unit_name]
                                received_ids.extend(unit_df['id'].tolist())
                            elif unit_actions[unit_name] == "❌ 全踢退":
                                unit_df = return_df[return_df['班隊'] == unit_name]
                                rejected_ids.extend(unit_df['id'].tolist())
                            else:
                                unit_df = return_df[return_df['班隊'] == unit_name]
                                for b_name in unit_df['書名'].unique():
                                    u_b_key = f"{unit_name}_{b_name}"
                                    if book_actions.get(u_b_key) == "✅ 審核":
                                        b_df = unit_df[unit_df['書名'] == b_name]
                                        received_ids.extend(b_df['id'].tolist())
                                    elif book_actions.get(u_b_key) == "❌ 踢退":
                                        b_df = unit_df[unit_df['書名'] == b_name]
                                        rejected_ids.extend(b_df['id'].tolist())
                                    elif edited_receive_dfs.get(u_b_key) is not None:
                                        edited_df = edited_receive_dfs[u_b_key]
                                        recv_rows = edited_df[edited_df["✅審核"] == True]
                                        received_ids.extend(recv_rows["id"].tolist())
                                        rej_rows = edited_df[edited_df["❌踢退"] == True]
                                        rejected_ids.extend(rej_rows["id"].tolist())
                        
                        has_action = False
                        c = conn.cursor()
                        now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                        
                        if received_ids:
                            id_list_str = ','.join(map(str, received_ids))
                            c.execute(f"SELECT u.unit, b.book_name, COUNT(b.id) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.id IN ({id_list_str}) GROUP BY u.unit, b.book_name")
                            recv_details = c.fetchall()
                            
                            c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id IN ({id_list_str})")
                            
                            for u_name, b_name, qty in recv_details:
                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
                                          (now_time, st.session_state.login_id, "歸還審核", f"核准 {u_name} 歸還 {b_name} {qty} 本"))
                            has_action = True
                            
                        if rejected_ids:
                            id_list_str = ','.join(map(str, rejected_ids))
                            c.execute(f"SELECT u.unit, b.book_name, COUNT(b.id) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.id IN ({id_list_str}) GROUP BY u.unit, b.book_name")
                            rej_details = c.fetchall()
                            
                            c.execute(f"UPDATE books SET status='借閱中' WHERE id IN ({id_list_str})")
                            
                            for u_name, b_name, qty in rej_details:
                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
                                          (now_time, st.session_state.login_id, "踢退歸還", f"踢退 {u_name} 歸還 {b_name} {qty} 本"))
                            has_action = True
                            
                        if has_action:
                            conn.commit()
                            st.success(f"✅ 審核作業完成！收訖 {len(received_ids)} 本，踢退退回 {len(rejected_ids)} 本。")
                            import time
                            time.sleep(1.5)
                            st.rerun()
                        else:
                            st.warning("⚠️ 您尚未選擇任何審核或踢退動作！")
                else:
                    st.success("目前各班隊皆無待歸還準則！")

                st.markdown("---")
                st.subheader("🚨 結訓準則未繳")
                st.info("💡 這裡顯示已結訓、帳號凍結清單。\n準則都已歸還，請勾選並點擊「已歸還」。")
                
                cbrn_df = pd.read_sql_query(f"SELECT b.id, u.login_id as 扣押帳號, u.unit as 原班隊, b.book_name as 書名, b.serial_number as 序號 FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.login_id LIKE 'cbrn%' AND u.squadron IN ({sq_in_clause}) ORDER BY u.login_id, b.book_name", conn)
                
                if not cbrn_df.empty:
                    cbrn_df.insert(0, "✅ 已歸還", False)
                    edited_cbrn = st.data_editor(cbrn_df, hide_index=True, disabled=["id", "扣押帳號", "原班隊", "書名", "序號"], width='stretch', column_config={"✅ 已歸還": st.column_config.CheckboxColumn("✅ 已歸還"), "id": None}, key="cbrn_recovery_table")
                    
                    if st.button("🚔 批次執行已歸還", type="primary"):
                        recovered_rows = edited_cbrn[edited_cbrn["✅ 已歸還"] == True]
                        recovered_ids = recovered_rows["id"].tolist()
                        
                        if recovered_ids:
                            c = conn.cursor()
                            now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                            
                            c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id IN ({','.join(map(str, recovered_ids))})")
                            c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "準則尋獲", f"從扣押帳號中尋獲並退庫共 {len(recovered_ids)} 本準則"))
                            
                            unique_cbrn_accounts = recovered_rows["扣押帳號"].unique()
                            for cbrn_acc in unique_cbrn_accounts:
                                c.execute(f"SELECT COUNT(*) FROM books WHERE owner_id='{cbrn_acc}' AND status!='在庫'")
                                if int(c.fetchone()[0]) == 0:
                                    c.execute(f"DELETE FROM users WHERE login_id='{cbrn_acc}'")
                                    c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, "SYSTEM", "欠單結案", f"扣押帳號 {cbrn_acc} 欠裝已全數追回，帳號徹底銷毀。"))
                            
                            conn.commit()
                            st.success(f"✅ 成功追回 {len(recovered_ids)} 本準則並退回大庫房！")
                            import time
                            time.sleep(1.5)
                            st.rerun()
                        else:
                            st.warning("⚠️ 請先勾選已歸還的準則！")
                else:
                    st.success("✨ 目前沒有任何結訓欠準則扣押帳號！")

            rescue_tab = tabs[3] if is_doc else tabs[2]
            with rescue_tab:
                st.subheader("👤 訓員結訓日修改與帳密救援")
                # 修正 1 & 2：補上 SELECT 並且保留 id，拿掉多餘的逗號
                l5_users = pd.read_sql_query(f"SELECT id, squadron as 中隊, unit as 班隊, login_id as 訓員帳號, discharge_date as 結訓日 FROM users WHERE role='L5' AND status='啟用' AND squadron IN ({sq_in_clause})", conn)
                
                if not l5_users.empty:
                    l5_users['結訓日'] = pd.to_datetime(l5_users['結訓日'], errors='coerce').dt.date
                    
                    # 修正 3：利用 "id": None 讓 id 在畫面上隱形，但底層仍保留資料
                    edited_date = st.data_editor(
                        l5_users, 
                        hide_index=True, 
                        disabled=["id", "中隊", "班隊", "訓員帳號"], 
                        column_config={
                            "id": None,  # 隱藏身分證
                            "結訓日": st.column_config.DateColumn("結訓日期", format="YYYY-MM-DD")
                        }
                    )
                    
                    if st.button("💾 儲存結訓日變更"):
                        c = conn.cursor()
                        has_err = False
                        for index, row in edited_date.iterrows():
                            if pd.notna(row['結訓日']):
                                try:
                                    u_id = int(row['id']) # 這裡需要用到 id
                                    new_date = str(row['結訓日'])
                                    c.execute("UPDATE users SET discharge_date=%s WHERE id=%s", (new_date, u_id))
                                except Exception:
                                    has_err = True
                        if not has_err:
                            conn.commit()
                            st.success("✅ 結訓日期已成功更新！")
                            import time
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("❌ 更新結訓日發生異常！")
                        
                    # 修正 4：重置密碼的表格，同樣把 'id' 抓進來但隱藏顯示
                    reset_df = l5_users[['id', '中隊', '班隊', '訓員帳號']].copy()
                    reset_df.insert(0, "選取", False)
                    
                    edited_u = st.data_editor(
                        reset_df, 
                        hide_index=True,
                        column_config={"id": None} # 隱藏身分證
                    )
                    
                    sel_reset = edited_u[edited_u["選取"] == True]["id"].tolist() # 這裡需要用到 id
                    if st.button("🔄 勾選批次重置為 army1234") and sel_reset:
                        c = conn.cursor()
                        c.execute(f"UPDATE users SET password='army1234', setup_count=1 WHERE id IN ({','.join(map(str, sel_reset))})")
                        conn.commit()
                        st.success("✅ 已成功重置密碼為 army1234，並恢復 1 次修改權限！")
                        st.rerun()
                else:
                    st.info("目前無可管理的訓員資料。")

                st.markdown("---")
                st.subheader("🤖 結訓日逾期帳號自動清查引擎")
                st.success("""✨ **系統全自動警戒中**：大隊部主機已接管清查作業。

每日過 24:00 後，系統將自動於背景掃描：
1. 直接註銷無欠裝之結訓帳號。
2. 自動扣押欠裝帳號，強制改名為 `cbrn` 系列並鎖定。
3. 自動清運 7 日前已被註銷之無效日誌。

💡 **您無需再進行任何手動掃描操作！**""")

            # ==========================================
            # 💬 Line 借還書對話自動生成器 (中隊彙總版 + 三格選單)
            # ==========================================
            with tabs[-1]:
                st.subheader("💬 Line 借還書對話自動生成器")
                st.info("💡 選擇您管轄的「中隊」，系統會自動統整該中隊底下所有班隊的借還書目。")
                
                # 升級：改為下拉選擇「中隊」，自動支援跨中隊管轄的文書兵
                sq_list = [s.strip() for s in st.session_state.squadron.split(',')]
                target_squadron = st.selectbox("請選擇要匯出的中隊", sq_list)
                
                # 🚀 升級為三格選單：稱呼、日期月曆、時間滾輪 (切成 3 欄)
                col1, col2, col3 = st.columns(3)
                with col1:
                    contact_person = st.text_input("開頭稱呼", value="劉姐")
                with col2:
                    tz_tw = timezone(timedelta(hours=8))
                    sel_date = st.date_input("預計日期", value=datetime.now(tz_tw).date())
                with col3:
                    # 預設下午 16:30，方便部隊作息
                    sel_time = st.time_input("預計時間", value=datetime.strptime("16:30", "%H:%M").time())
                    
                # 系統自動將選單結果，無縫接軌融合成軍規文字格式 (例：3/10（二）1630)
                tw_wd = ["一", "二", "三", "四", "五", "六", "日"][sel_date.weekday()]
                borrow_time_str = f"{sel_date.month}/{sel_date.day}（{tw_wd}）{sel_time.strftime('%H%M')}"
                    
                if st.button("🚀 生成中隊彙總報表", type="primary"):
                    c = conn.cursor()
                    # 1. 抓取該中隊下「所有班隊」的借閱清單
                    borrow_query = f"""
                        SELECT u.unit, b.book_name, COUNT(b.id) as qty
                         FROM books b
                        JOIN users u ON b.owner_id = u.login_id 
                        WHERE u.squadron='{target_squadron}' AND b.status='保留待領取' 
                        GROUP BY u.unit, b.book_name
                    """
                    borrow_df = pd.read_sql_query(borrow_query, conn)
                    
                    # 2. 抓取該中隊下「所有班隊」的歸還清單
                    return_query = f"""
                        SELECT u.unit, b.book_name, COUNT(b.id) as qty 
                        FROM books b 
                        JOIN users u ON b.owner_id = u.login_id 
                        WHERE u.squadron='{target_squadron}' AND b.status='歸還中' 
                        GROUP BY u.unit, b.book_name
                    """
                    return_df = pd.read_sql_query(return_query, conn)
                    
                    # 3. 組合文字
                    msg = f"{contact_person}好，{target_squadron}借書清單\n"
                    msg += f"借閱時間：{borrow_time_str}\n\n"
                    
                    # 找出所有今天有借還動作的班隊
                    all_units = set()
                    if not borrow_df.empty: all_units.update(borrow_df['unit'].tolist())
                    if not return_df.empty: all_units.update(return_df['unit'].tolist())
                    
                    if not all_units:
                        msg += "今日無任何班隊送出借還書申請。\n"
                    else:
                        for unit in sorted(list(all_units)):
                            msg += f"==== 【{unit}】 ====\n"
                            
                            # 借閱區塊
                            msg += "借閱書目：\n"
                            if not borrow_df.empty:
                                unit_borrow = borrow_df[borrow_df['unit'] == unit]
                                if not unit_borrow.empty:
                                    for _, row in unit_borrow.iterrows():
                                        msg += f"{row['book_name']}*{int(row['qty'])}\n"
                                else:
                                    msg += "無\n"
                            else:
                                msg += "無\n"
                                
                            # 歸還區塊
                            msg += "\n歸還書目：\n"
                            if not return_df.empty:
                                unit_return = return_df[return_df['unit'] == unit]
                                if not unit_return.empty:
                                    for _, row in unit_return.iterrows():
                                        msg += f"{row['book_name']}*{int(row['qty'])}\n"
                                else:
                                    msg += "無\n"
                            else:
                                msg += "無\n"
                            msg += "\n"
                            
                    st.success("✨ 中隊彙總報表生成完畢！請點擊框框內全選複製：")
                    st.text_area("複製區", value=msg.strip(), height=400)

    elif menu == "綜合查詢":
        st.header("🔍綜合查詢")
        # 依照階級給予不同的查詢權限
        if st.session_state.role == 'L5':
            search_type = st.radio("查詢模式", ["查書名", "查序號"], horizontal=True)
        else:
            search_type = st.radio("查詢模式", ["查書名", "查序號", "中隊持有現況"], horizontal=True)

        if search_type == "查書名" or search_type == "查序號":
            keyword = st.text_input("請輸入關鍵字")
            if st.button("搜尋") and keyword:
                if "書名" in search_type:
                    query = "SELECT u.squadron as 中隊, u.unit as 班隊, COUNT(b.id) as 數量 FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.book_name LIKE %s GROUP BY u.squadron, u.unit"
                    res = pd.read_sql_query(query, conn, params=(f"%{keyword}%",))
                    st.dataframe(res, use_container_width=True)
                else:
                    query = "SELECT u.squadron as 中隊, u.unit as 班隊, b.book_name as 書名, b.status as 狀態 FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.serial_number = %s"
                    res = pd.read_sql_query(query, conn, params=(keyword,))
                    st.dataframe(res, use_container_width=True)

        elif search_type == "中隊持有現況":
            st.subheader(f"🗂️ 【{st.session_state.squadron}】所屬班隊準則持有現況")
            st.info("💡 點擊下方各班隊名稱，即可展開查看該班隊目前持有的所有準則與詳細序號。")
            
            if st.session_state.role in ['L1', 'L2']:
                unit_query = "SELECT DISTINCT u.unit FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status IN ('借閱中', '保留待領取', '少領異常', '歸還中')"
            else:
                sq_list = [s.strip() for s in st.session_state.squadron.split(',')]
                sq_in_clause = "'" + "','".join(sq_list) + "'"
                unit_query = f"SELECT DISTINCT u.unit FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.squadron IN ({sq_in_clause}) AND b.status IN ('借閱中', '保留待領取', '少領異常', '歸還中')"
                
            units_df = pd.read_sql_query(unit_query, conn)
            if units_df.empty:
                st.success("目前所屬中隊無任何班隊持有準則 (皆已歸還或無借閱)。")
            else:
                for unit_name in units_df['unit']:
                    with st.expander(f"🏢 班隊：【{unit_name}】"):
                        books_df = pd.read_sql_query(f"SELECT b.book_name, COUNT(b.id) as qty FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.unit='{unit_name}' AND b.status IN ('借閱中', '保留待領取', '少領異常', '歸還中') GROUP BY b.book_name", conn)
                        
                        for _, book_row in books_df.iterrows():
                            book_title = book_row['book_name']
                            b_qty = book_row['qty']
                            st.markdown(f"**📘 {book_title}** (共 **{b_qty}** 本)")
                            serials_df = pd.read_sql_query(f"SELECT b.serial_number, b.status FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.unit='{unit_name}' AND b.book_name='{book_title}' AND b.status IN ('借閱中', '保留待領取', '少領異常', '歸還中')", conn)
                            
                            display_serials = []
                            for _, s_row in serials_df.iterrows():
                                sn = s_row['serial_number']
                                st_val = s_row['status']
                                if st_val == '借閱中':
                                    display_serials.append(f"{sn}")
                                else:
                                    display_serials.append(f"{sn} ({st_val})")
                                    
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

    elif menu == "操作紀錄" and st.session_state.role in ['L1', 'L2', 'L3', 'L4']:
        st.header("🗂️ 操作紀錄")
        
        search_keyword = st.text_input("🔍 搜尋紀錄 (可輸入班隊名稱、動作、準則名稱等)")
        
        log_query = """
            SELECT a.timestamp as 時間, 
                   COALESCE(
                       CASE 
                           WHEN u.role = 'L5' THEN u.unit
                           WHEN u.role IN ('L1', 'L2', 'L3', 'L4') THEN u.squadron || '-' || u.title || CASE WHEN u.name IS NOT NULL AND u.name != '' AND u.name != '代表' THEN '(' || u.name || ')' ELSE '' END
                           ELSE a.user_id 
                       END, a.user_id
                   ) as 操作者, 
                   a.action as 系統動作, 
                   a.details as 詳細內容 
            FROM action_logs a
            LEFT JOIN users u ON a.user_id = u.login_id
        """
        
        if search_keyword:
            safe_kw = search_keyword.replace("'", "''")
            log_query += f" WHERE a.details LIKE '%%{safe_kw}%%' OR a.action LIKE '%%{safe_kw}%%' OR u.unit LIKE '%%{safe_kw}%%' OR u.name LIKE '%%{safe_kw}%%'"
            
        log_query += " ORDER BY a.id DESC LIMIT 200"
        logs_df = pd.read_sql_query(log_query, conn)
        
        if logs_df.empty:
            st.warning("沒有找到符合條件的操作紀錄。")
        else:
            import re
            def parse_details(row):
                text = str(row['詳細內容'])
                # 正規表達式：精準捕捉標準格式
                match = re.search(r'^(核准|申請|踢退)\s+(.*?)\s+(歸還|借閱)\s+(.*?)\s+(\d+)\s*本$', text)
                
                if match:
                    return pd.Series([match.group(1), match.group(2), match.group(3), match.group(4), f"{match.group(5)} 本", ""])
                else:
                    return pd.Series(["-", "-", "-", "-", "-", text])

            logs_df[['操作指令', '對象/班隊', '動作細節', '準則名稱(含版本)', '數量', '其他操作細節']] = logs_df.apply(parse_details, axis=1)
            display_df = logs_df[['時間', '操作者', '操作指令', '對象/班隊', '動作細節', '準則名稱(含版本)', '數量', '其他操作細節']]
            
            st.dataframe(display_df, use_container_width=True, hide_index=True)
finally:
    release_connection(conn)


















