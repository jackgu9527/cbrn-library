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
# ⚡ 全新幽靈背景引擎：結訓日 24:00 全自動清查 (無 cbrn 版)
# ==========================================
def run_ghost_cleanup():
    if 'ghost_engine_ran' in st.session_state:
        return
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        tz_tw = timezone(timedelta(hours=8))
        today_str = datetime.now(tz_tw).strftime('%Y-%m-%d')
        now_time = datetime.now(tz_tw).strftime("%Y-%m-%d %H:%M:%S")
        
        # 1. 處理逾期 (帳號轉凍結 + 自動代還)
        c.execute(f"SELECT id, login_id, unit FROM users WHERE role='L5' AND discharge_date < '{today_str}' AND status='啟用'")
        overdue_users = c.fetchall()
        for u_id, u_login, u_unit in overdue_users:
            c.execute(f"UPDATE books SET status='歸還中' WHERE owner_id='{u_login}' AND status IN ('借閱中', '保留待領取', '少領異常')")
            c.execute(f"UPDATE users SET status='結訓凍結' WHERE id={u_id}")
            c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, "SYSTEM", "結訓凍結", f"班隊 {u_unit} 已結訓，系統自動代為送出歸還並凍結帳號。"))
                
        # 2. 清除已結清的凍結帳號 (0 本書 = 幹部已點收完畢 = 自動刪除)
        c.execute("SELECT id, login_id, unit FROM users WHERE role='L5' AND status='結訓凍結'")
        frozen_users = c.fetchall()
        for f_id, f_login, f_unit in frozen_users:
            c.execute(f"SELECT COUNT(*) FROM books WHERE owner_id='{f_login}'")
            if c.fetchone()[0] == 0:
                c.execute(f"DELETE FROM users WHERE id={f_id}")
                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, "SYSTEM", "帳號註銷", f"班隊 {f_unit} 裝備已結清，系統自動刪除凍結帳號。"))
                    
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
    
    # 根據不同階級與職務，給予專屬的左側導覽列
    if st.session_state.role == 'L5':
        menu = st.radio("功能導覽", [
            "🏠 首頁", 
            "📤 準則借閱", 
            "📥 準則歸還", 
            "💬 Line 報表專區", 
            "🔍 綜合查詢"
        ])
    elif st.session_state.role == 'L4':
        # 判斷是否為文書兵
        is_doc = "人事" in st.session_state.title or "文書" in st.session_state.title
        if is_doc:
            menu = st.radio("文書作業", [
                "🏠 首頁", 
                "👥 帳號管理", 
                "📤 準則借閱核准", 
                "📥 準則歸還核准", 
                "💬 Line 報表專區", 
                "📊 中隊持有現況", 
                "🔍 綜合查詢", 
                "🗂️ 操作紀錄"
            ])
        else:
            menu = st.radio("幹部管理", [
                "🏠 首頁", 
                "👥 帳號管理", 
                "📥 準則歸還核准", 
                "💬 Line 報表專區", 
                "📊 中隊持有現況", 
                "🔍 綜合查詢", 
                "🗂️ 操作紀錄"
            ])
    elif st.session_state.role == 'L3':
        menu = st.radio("高階督導", [
            "🏠 首頁", 
            "👥 人事管理", 
            "📊 中隊持有現況", 
            "🔍 綜合查詢", 
            "🗂️ 操作紀錄"
        ])
    elif st.session_state.role in ['L1', 'L2']:
        menu = st.radio("系統管理", [
            "🏠 首頁", 
            "⚙️ 系統與帳號全域管理", 
            "📊 中隊持有現況", 
            "🔍 綜合查詢", 
            "🗂️ 操作紀錄"
        ])
    
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
    if menu in ["首頁", "🏠 首頁"]:
        st.header("📊 首頁")
        
        if st.session_state.role == 'L5':
            # === 🎯 智慧引導：新進/更換人員強制修改帳密 ===
            if st.session_state.setup_count > 0:
                with st.container(border=True):
                    st.error("🆕 **新人員/新帳號登入：請先設定您的專屬帳號與密碼**")
                    st.info("💡 為確保帳號安全，請修改預設帳密。修改完成後此視窗將自動關閉，未來若忘記帳密請洽 L4 幹部。")
                    col_id, col_pw, col_btn = st.columns([3, 3, 2])
                    with col_id:
                        new_id = st.text_input("設定新帳號", value=st.session_state.login_id, key="setup_new_id")
                    with col_pw:
                        new_pwd = st.text_input("設定新密碼", type="password", placeholder="建議至少8碼", key="setup_new_pw")
                    with col_btn:
                        st.write(" ")
                        if st.button("🚀 確認修改並開通", type="primary", use_container_width=True):
                            if not new_pwd:
                                st.warning("請輸入密碼！")
                            else:
                                c = conn.cursor()
                                c.execute("SELECT COUNT(*) FROM users WHERE login_id=%s AND id!=%s", (new_id, int(st.session_state.id)))
                                if c.fetchone()[0] > 0:
                                    st.error("❌ 此帳號已被佔用！")
                                else:
                                    old_id = st.session_state.login_id
                                    c.execute("UPDATE users SET login_id=%s, password=%s, setup_count=0 WHERE id=%s", (new_id, new_pwd, int(st.session_state.id)))
                                    c.execute("UPDATE books SET owner_id=%s WHERE owner_id=%s", (new_id, old_id))
                                    c.execute("UPDATE borrow_requests SET login_id=%s WHERE login_id=%s", (new_id, old_id))
                                    c.execute("UPDATE action_logs SET user_id=%s WHERE user_id=%s", (new_id, old_id))
                                    conn.commit()
                                    log_action(new_id, "新進設定", "完成首次登入帳密修改")
                                    st.success("✅ 設定成功！請重新登入。")
                                    import time; time.sleep(1.5); st.session_state.clear(); st.rerun()
                st.markdown("---")

            # === 📊 訓員戰情看板 (全幅無側邊欄) ===
            st.markdown(f"**所屬單位：** {st.session_state.squadron} - {st.session_state.unit}")
            if st.session_state.discharge_date:
                d_date = datetime.strptime(str(st.session_state.discharge_date), '%Y-%m-%d').date()
                today = datetime.now().date()
                days_left = (d_date - today).days
                if days_left < 0: st.error(f"🚨 已逾結訓日！請盡速完成裝備歸還。")
                elif days_left <= 3: st.warning(f"⚠️ 結訓倒數：{days_left} 天！")
                else: st.info(f"📅 距離結訓日還有：{days_left} 天")

            # 待領取與持有清單 (維持原本全幅設計)
            pending_claim = pd.read_sql_query(f"SELECT id, book_name FROM books WHERE owner_id='{st.session_state.login_id}' AND status='保留待領取'", conn)
            if not pending_claim.empty:
                st.warning("⚠️ 您有已核准但尚未綁定序號的準則！請對照實體書進行批次登錄。")
                with st.form("batch_claim_form"):
                    st.info("💡 若部分準則尚未發放，請「留空」即可；若確定不會再領到，請勾選「異常回報」。")
                    grouped = pending_claim.groupby('book_name')
                    claim_data = {}
                    for b_name, group in grouped:
                        qty = len(group)
                        st.markdown(f"**📘 {b_name}** (待領：**{qty}** 本)")
                        serials_str = st.text_input("請輸入實體序號 (逗號隔開)", key=f"serials_{b_name}")
                        is_short = st.checkbox(f"☑️ 異常回報：確定「不會再領到」剩下的書才勾選", key=f"short_{b_name}")
                        claim_data[b_name] = {"ids": group['id'].tolist(), "serials_str": serials_str, "is_short": is_short, "qty": qty}
                    
                    if st.form_submit_button("💾 確認送出實領準則"):
                        c = conn.cursor(); has_error = False
                        for b_name, data in claim_data.items():
                            raw_s = [s.strip() for s in data["serials_str"].split(',') if s.strip()]
                            entered_qty, app_qty, ids = len(raw_s), int(data["qty"]), data["ids"]
                            if entered_qty > app_qty: st.error(f"❌ {b_name} 數量超過額度！"); has_error = True; break
                            if entered_qty == 0 and not data["is_short"]: continue
                            for i in range(app_qty):
                                p_id = int(ids[i])
                                if i < entered_qty:
                                    new_s = raw_s[i]
                                    c.execute("SELECT id, status FROM books WHERE serial_number=%s", (new_s,))
                                    check = c.fetchone()
                                    if check and check[1] == '在庫':
                                        c.execute(f"UPDATE books SET status='借閱中', owner_id='{st.session_state.login_id}' WHERE id={int(check[0])}")
                                        c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id={p_id}")
                                    elif not check:
                                        c.execute("UPDATE books SET serial_number=%s, status='借閱中' WHERE id=%s", (new_s, p_id))
                                    else: st.error(f"❌ 序號 {new_s} 已被借閱！"); has_error = True; break
                                elif data["is_short"]: c.execute(f"UPDATE books SET status='少領異常' WHERE id={p_id}")
                        if not has_error: conn.commit(); st.success("✅ 序號綁定完成！"); import time; time.sleep(1.5); st.rerun()

            st.markdown("#### 📦 我的持有清單")
            my_books = pd.read_sql_query(f"SELECT id, book_name as 書名, serial_number as 序號 FROM books WHERE owner_id='{st.session_state.login_id}' AND status='借閱中'", conn)
            if my_books.empty: st.info("目前無借閱準則。")
            else:
                st.dataframe(my_books[['書名', '序號']], use_container_width=True, hide_index=True)
                with st.expander("🔧 自主修正實體序號"):
                    edited_dfs = {}
                    for b_name in my_books['書名'].unique():
                        b_df = my_books[my_books['書名'] == b_name].reset_index(drop=True)
                        edited_dfs[b_name] = st.data_editor(b_df, hide_index=True, disabled=["id", "書名"], key=f"edit_my_{b_name}")
                    if st.button("💾 批次修正序號"):
                        c = conn.cursor(); has_err = False
                        for b_name, e_df in edited_dfs.items():
                            orig_df = my_books[my_books['書名'] == b_name].reset_index(drop=True)
                            for idx, row in e_df.iterrows():
                                old_s, new_s, b_id = str(orig_df.iloc[idx]['序號']).strip(), str(row['序號']).strip(), int(row['id'])
                                if old_s != new_s:
                                    c.execute("SELECT id, status FROM books WHERE serial_number=%s", (new_s,))
                                    check = c.fetchone()
                                    if check and check[1] == '在庫':
                                        c.execute(f"UPDATE books SET status='借閱中', owner_id='{st.session_state.login_id}' WHERE id={int(check[0])}")
                                        c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id={b_id}")
                                    else: c.execute("UPDATE books SET serial_number=%s WHERE id=%s", (new_s, b_id))
                        if not has_err: conn.commit(); st.success("✅ 序號已修正！"); import time; time.sleep(1); st.rerun()

            st.markdown("---")
            st.markdown("#### 📤 待幹部審核清單 (歸還中)")
            returning_books = pd.read_sql_query(f"SELECT book_name as 書名, serial_number as 序號 FROM books WHERE owner_id='{st.session_state.login_id}' AND status='歸還中'", conn)
            if not returning_books.empty: st.dataframe(returning_books, hide_index=True, use_container_width=True)
            else: st.success("目前無歸還中準則。")

        # ======== 🟢 L4：區隊長/文書兵 ========
        elif st.session_state.role == 'L4':
            # === 🎯 智慧引導：新進/更換幹部強制修改 ===
            if st.session_state.setup_count > 0:
                with st.container(border=True):
                    st.error("🆕 **新進/更換幹部：請先設定您的姓名與專屬帳密**")
                    st.info("💡 為確保紀錄正確，請填寫您的真實姓名與密碼。日後姓名僅能由中隊長更改。")
                    c1, c2, c3 = st.columns(3)
                    with c1: new_name = st.text_input("您的姓名", value=st.session_state.name, key="l4_setup_name")
                    with c2: new_id = st.text_input("專屬帳號", value=st.session_state.login_id, key="l4_setup_id")
                    with c3: new_pwd = st.text_input("專屬密碼", type="password", key="l4_setup_pw")
                    
                    if st.button("🚀 確認開通", type="primary", use_container_width=True):
                        if not new_pwd or not new_name: st.warning("姓名與密碼為必填！")
                        else:
                            c = conn.cursor()
                            c.execute("SELECT COUNT(*) FROM users WHERE login_id=%s AND id!=%s", (new_id, int(st.session_state.id)))
                            if c.fetchone()[0] > 0: st.error("❌ 此帳號已被佔用！")
                            else:
                                c.execute("UPDATE users SET name=%s, login_id=%s, password=%s, setup_count=0 WHERE id=%s", (new_name, new_id, new_pwd, int(st.session_state.id)))
                                conn.commit()
                                log_action(new_id, "幹部開通", f"完成首次登入設定，姓名：{new_name}")
                                st.success("✅ 設定成功！請重新登入。")
                                import time; time.sleep(1.5); st.session_state.clear(); st.rerun()
                st.markdown("---")

            col1, col2 = st.columns([2, 1])
            with col1:
                st.markdown(f"**{display_name}**長官好，以下為今日概況：")
                sq_list = [s.strip() for s in st.session_state.squadron.split(',')]
                sq_in_clause = "'" + "','".join(sq_list) + "'"
                
                pending_reg = pd.read_sql_query(f"SELECT COUNT(*) FROM users WHERE status='待審核' AND squadron IN ({sq_in_clause})", conn).iloc[0,0]
                pending_bor = pd.read_sql_query(f"SELECT COUNT(*) FROM borrow_requests br JOIN users u ON br.login_id = u.login_id WHERE br.status='待審核' AND u.squadron IN ({sq_in_clause})", conn).iloc[0,0]
                pending_ret = pd.read_sql_query(f"SELECT COUNT(*) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='歸還中' AND u.squadron IN ({sq_in_clause})", conn).iloc[0,0]
                pending_abn = pd.read_sql_query(f"SELECT COUNT(*) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='少領異常' AND u.squadron IN ({sq_in_clause})", conn).iloc[0,0]
                
                c_m1, c_m2, c_m3, c_m4 = st.columns(4)
                c_m1.metric("📝 待開通帳號", f"{pending_reg} 件")
                c_m2.metric("📥 待核准借閱", f"{pending_bor} 件")
                c_m3.metric("📤 待審核準則", f"{pending_ret} 件")
                c_m4.metric("🔴 領取異常警示", f"{pending_abn} 件")
            
            with col2:
                with st.expander("⚙️ 日常帳密修改 (無次數限制)", expanded=False):
                    st.info("💡 姓名僅能由 L3 中隊長變更。此處僅供修改帳號與密碼。")
                    new_id = st.text_input("新帳號", value=st.session_state.login_id, key="l4_daily_id")
                    new_pwd = st.text_input("新密碼", type="password", key="l4_daily_pw")
                    if st.button("💾 儲存變更"):
                        if not new_pwd: st.error("請輸入新密碼！")
                        else:
                            c = conn.cursor()
                            c.execute("SELECT COUNT(*) FROM users WHERE login_id=%s AND id!=%s", (new_id, int(st.session_state.id)))
                            if c.fetchone()[0] > 0: st.error("❌ 帳號被佔用！")
                            else:
                                c.execute("UPDATE users SET login_id=%s, password=%s WHERE id=%s", (new_id, new_pwd, int(st.session_state.id)))
                                conn.commit()
                                st.success("✅ 修改成功！請重新登入。")
                                import time; time.sleep(1.5); st.session_state.clear(); st.rerun()

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

    elif menu in ["準則借閱", "📤 準則借閱"] and st.session_state.role == 'L5':
        st.header("📤 準則借閱申請")
        st.info("💡 請選擇您需要借閱的準則與數量，送出後請等待幹部核准。")
        
        c = conn.cursor()
        c.execute("SELECT book_name, COUNT(id) FROM books WHERE status='在庫' GROUP BY book_name")
        available_books = c.fetchall()
        
        if not available_books:
            st.warning("目前庫房沒有可借閱的準則。")
        else:
            # === ✨ 升級功能：全域預設借閱數量 ===
            st.markdown("#### 🎯 第一步：設定預設數量")
            default_req_qty = st.number_input("請輸入欲借閱的數量 (例如：貴班隊人數)", min_value=1, value=1, help="設定後，下方所有選取的準則都會自動帶入此數量")
            st.markdown("---")
            
            st.markdown("#### 📚 第二步：選擇準則")
            book_options = [f"{b[0]} (庫存: {b[1]}本)" for b in available_books]
            selected_books = st.multiselect("選擇要借閱的準則", book_options)
            
            if selected_books:
                borrow_requests = {}
                can_submit = True  # 🟢 總提交開關
                
                for selection in selected_books:
                    with st.container(border=True):
                        b_name = selection.split(" (")[0]
                        max_qty = int(selection.split("庫存: ")[1].replace("本)", ""))
                        
                        # 🔍 啟動防呆偵測雷達：檢查是否已經持有
                        c.execute(f"SELECT COUNT(*) FROM books WHERE owner_id='{st.session_state.login_id}' AND book_name='{b_name}' AND status!='在庫'")
                        total_existing = int(c.fetchone()[0])
                        
                        # === ✨ 智慧帶入預設數量 (若庫存不足，則安全帶入最大庫存) ===
                        auto_val = min(default_req_qty, max_qty)
                        
                        qty = st.number_input(f"欲借閱【{b_name}】的數量", min_value=1, max_value=max_qty, value=auto_val, key=f"req_{b_name}")
                        borrow_requests[b_name] = qty
                        
                        # 🚨 觸發重複借閱防呆機制
                        if total_existing > 0:
                            st.warning(f"⚠️ 系統偵測到您名下已有 **{total_existing}** 本【{b_name}】。")
                            confirm_extra = st.checkbox(f"☑️ 我確認此為「缺少數量再額外申請」", key=f"chk_extra_{b_name}")
                            if not confirm_extra:
                                can_submit = False
                
                st.markdown("---")
                # 🛡️ 根據防呆結果決定是否顯示按鈕
                if can_submit:
                    if st.button("🚀 送出借閱申請", type="primary", use_container_width=True):
                        now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                        for b_name, qty in borrow_requests.items():
                            c.execute("INSERT INTO borrow_requests (login_id, unit, book_name, quantity, status) VALUES (%s, %s, %s, %s, %s)", 
                                      (st.session_state.login_id, st.session_state.unit, b_name, qty, '待審核'))
                            c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)",
                                      (now_time, st.session_state.login_id, "申請借閱", f"申請 {b_name} {qty} 本"))
                        conn.commit()
                        st.success("✅ 申請已送出！請等待幹部核准。")
                        import time; time.sleep(1.5); st.rerun()
                else:
                    st.error("🚨 發現重複借閱項目！請勾選上方確認框後，才能送出申請。")
    elif menu in ["💬 Line 報表專區", "Line 報表專區"] and st.session_state.role == 'L5':
        st.header("💬 Line 借還書回報")
        tabs = st.tabs(["🚚 借還書回報", "📱 裝備清點回報"])
        
        with tabs[0]:
            st.info("💡 請在送出申請後，點擊下方產生回報文字貼至 Line。")
            if st.button("🚀 生成借還書清單", type="primary"):
                br_df = pd.read_sql_query(f"SELECT book_name, quantity FROM borrow_requests WHERE login_id='{st.session_state.login_id}' AND status='待審核'", conn)
                rt_df = pd.read_sql_query(f"SELECT book_name FROM books WHERE owner_id='{st.session_state.login_id}' AND status='歸還中'", conn)
                
                msg = f"報告，班隊：{st.session_state.unit}\n借還書清單：\n\n【申請借閱】：\n"
                if not br_df.empty:
                    for _, r in br_df.iterrows(): msg += f"{r['book_name']}*{r['quantity']}\n"
                else: msg += "無\n"
                
                msg += "\n【申請歸還】：\n"
                if not rt_df.empty:
                    rt_group = rt_df.groupby('book_name').size()
                    for b_name, count in rt_group.items(): msg += f"{b_name}*{count}\n"
                else: msg += "無\n"
                st.text_area("📋 借還書複製區", value=msg.strip(), height=250)
                
        with tabs[1]:
            st.info("💡 產出目前名下所有「借閱中」準則的序號清單，供每日清點。")
            if st.button("🚀 生成清點報表", type="primary"):
                inv_df = pd.read_sql_query(f"SELECT book_name, serial_number FROM books WHERE owner_id='{st.session_state.login_id}' AND status='借閱中'", conn)
                msg = f"報告，班隊：{st.session_state.unit}\n準則清點：\n\n"
                if inv_df.empty: msg += "無\n"
                else:
                    grouped = inv_df.groupby('book_name')
                    for b_name, group in grouped:
                        msg += f"{b_name}*{len(group)}\n{','.join(group['serial_number'].tolist())}\n\n"
                st.text_area("📋 清點複製區", value=msg.strip(), height=250)
                
    elif menu in ["準則歸還", "📥 準則歸還"] and st.session_state.role == 'L5':
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

    elif menu in ["審核與管理", "⚙️ 系統與帳號全域管理", "👥 人事管理", "👥 帳號管理", "📤 準則借閱核准", "📥 準則歸還核准", "💬 Line 報表專區"] and st.session_state.role in ['L1', 'L2', 'L3', 'L4']:
        st.header("⚙️ 審核與管理後台")
        
        if st.session_state.role == 'L1':
            st.error("👑 系統管理員模式：可強制修改全域使用者資料")
            
        # ===============================================
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
                            
                elif menu in ["👥 人事管理", "審核與管理"] and st.session_state.role == 'L3':
                    st.subheader("👥 所屬幹部 (L4) 管理中心")
                    st.info("💡 您可直接在此表中調整幹部的所屬中隊與職務。若遇幹部人員更換，請勾選後點擊「發放強制修改權限」。")
        
        # 只撈取該中隊的 L4 幹部
        l4_users = pd.read_sql_query(f"SELECT id, squadron as 中隊, title as 職務, name as 姓名, login_id as 帳號, setup_count as 修改權限 FROM users WHERE role='L4' AND squadron='{st.session_state.squadron}'", conn)
        
        if not l4_users.empty:
            l4_users.insert(0, "選取", False)
            edited_l4 = st.data_editor(
                l4_users, hide_index=True, disabled=["id", "姓名", "帳號", "修改權限"], use_container_width=True,
                column_config={
                    "中隊": st.column_config.SelectboxColumn("管理中隊 (可多選逗號分隔)", required=True),
                    "職務": st.column_config.TextColumn("職務", required=True)
                }
            )
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("💾 儲存【中隊】與【職務】變更", type="primary", use_container_width=True):
                    c = conn.cursor()
                    for idx, row in edited_l4.iterrows():
                        c.execute("UPDATE users SET squadron=%s, title=%s WHERE id=%s", (row['中隊'], row['職務'], int(row['id'])))
                    conn.commit()
                    st.success("✅ 資料已成功更新！")
                    import time; time.sleep(1); st.rerun()
            with col2:
                sel_l4 = edited_l4[edited_l4["選取"] == True]["id"].tolist()
                if st.button("🔓 發放「強制修改權限」(供幹部更換交接用)", use_container_width=True):
                    if sel_l4:
                        c = conn.cursor()
                        c.execute(f"UPDATE users SET setup_count=1 WHERE id IN ({','.join(map(str, sel_l4))})")
                        conn.commit()
                        st.success("✅ 權限已發放！該幹部下次登入將被強制要求重設姓名與帳密。")
                        import time; time.sleep(1.5); st.rerun()
                    else:
                        st.warning("⚠️ 請先勾選要發放權限的幹部！")
        else:
            st.success("目前無所屬的 L4 幹部資料。")

        elif st.session_state.role == 'L4':
            sq_list = [s.strip() for s in st.session_state.squadron.split(',')]
            sq_in_clause = "'" + "','".join(sq_list) + "'"
            is_doc = "人事" in st.session_state.title or "文書" in st.session_state.title

            if menu == "👥 帳號管理":
                st.subheader("👥 人事與帳號管理中心")
                acc_tabs = st.tabs(["📝 新進班隊開通", "👤 結訓日與復權救援"])
                
                with acc_tabs[0]:
                    st.markdown("#### 待審核名單")
                    reg_df = pd.read_sql_query(f"SELECT id, squadron as 中隊, unit as 班隊, login_id as 帳號, discharge_date as 結訓日 FROM users WHERE status='待審核' AND squadron IN ({sq_in_clause})", conn)
                    if not reg_df.empty:
                        reg_df.insert(0, "✅ 開通", False)
                        reg_df.insert(1, "❌ 否決(刪除)", False)
                        edited_reg = st.data_editor(reg_df, hide_index=True)
                        if st.button("🚀 送出審核結果", type="primary"):
                            c = conn.cursor()
                            to_approve = edited_reg[edited_reg["✅ 開通"] == True]["id"].tolist()
                            to_reject = edited_reg[edited_reg["❌ 否決(刪除)"] == True]["id"].tolist()
                            if to_approve:
                                c.execute(f"UPDATE users SET status='啟用' WHERE id IN ({','.join(map(str, to_approve))})")
                            if to_reject:
                                c.execute(f"DELETE FROM users WHERE id IN ({','.join(map(str, to_reject))})")
                            conn.commit()
                            st.success(f"已處理 {len(to_approve)} 筆開通，{len(to_reject)} 筆刪除！")
                            import time; time.sleep(1.5); st.rerun()
                    else:
                        st.info("目前無待審核的註冊申請。")

                with acc_tabs[1]:
                    st.markdown("#### 👤 結訓日與權限救援中心")
                    st.info("💡 直接點擊表格修改結訓日。勾選最左方方塊可批次執行「權限發放」或「密碼重置」。")
                    
                    l5_users = pd.read_sql_query(f"SELECT id, squadron as 中隊, unit as 班隊, login_id as 訓員帳號, status as 狀態, discharge_date as 結訓日 FROM users WHERE role='L5' AND status IN ('啟用', '結訓凍結') AND squadron IN ({sq_in_clause})", conn)
                    
                    if not l5_users.empty:
                        l5_users['結訓日'] = pd.to_datetime(l5_users['結訓日'], errors='coerce').dt.date
                        l5_users.insert(0, "選取", False)
                        
                        edited_u = st.data_editor(
                            l5_users, hide_index=True, disabled=["id", "中隊", "班隊", "訓員帳號", "狀態"], use_container_width=True,
                            column_config={
                                "id": None, 
                                "結訓日": st.column_config.DateColumn("結訓日期 (點擊修改)", format="YYYY-MM-DD")
                            }
                        )
                        
                        col1, col2, col3 = st.columns(3)
                        sel_ids = edited_u[edited_u["選取"] == True]["id"].tolist()
                        
                        with col1:
                            if st.button("💾 儲存結訓日變更 (自動解除凍結)", type="primary", use_container_width=True):
                                c = conn.cursor()
                                for idx, row in edited_u.iterrows():
                                    if pd.notna(row['結訓日']):
                                        new_status = '啟用' if row['狀態'] == '結訓凍結' else row['狀態']
                                        c.execute("UPDATE users SET discharge_date=%s, status=%s WHERE id=%s", (str(row['結訓日']), new_status, int(row['id'])))
                                conn.commit()
                                st.success("✅ 結訓日已更新！")
                                import time; time.sleep(1); st.rerun()
                                
                        with col2:
                            if st.button("🔓 發放強制修改權限 (供人員更換)", use_container_width=True):
                                if sel_ids:
                                    c = conn.cursor()
                                    c.execute(f"UPDATE users SET setup_count=1 WHERE id IN ({','.join(map(str, sel_ids))})")
                                    conn.commit()
                                    st.success("✅ 權限已發放！訓員登入將跳出修改視窗。")
                                    import time; time.sleep(1); st.rerun()
                                else: st.warning("請先勾選名單！")
                                    
                        with col3:
                            if st.button("🔑 批次重置密碼為 army1234", use_container_width=True):
                                if sel_ids:
                                    c = conn.cursor()
                                    c.execute(f"UPDATE users SET password='army1234' WHERE id IN ({','.join(map(str, sel_ids))})")
                                    conn.commit()
                                    st.success("✅ 密碼已重置為預設！")
                                    import time; time.sleep(1); st.rerun()
                                else: st.warning("請先勾選名單！")
                    else:
                        st.success("目前無可管理的訓員資料。")

            elif menu == "📤 準則借閱核准" and is_doc:
                st.subheader("📚 借閱準則審核")
                req_df = pd.read_sql_query(f"SELECT br.id as 單號, br.login_id as 帳號, br.unit as 班隊, br.book_name as 書名, br.quantity as 申請數量 FROM borrow_requests br JOIN users u ON br.login_id = u.login_id WHERE br.status='待審核' AND u.squadron IN ({sq_in_clause}) ORDER BY br.unit, br.book_name, br.id", conn)
                
                if not req_df.empty:
                    owned_counts = []
                    c = conn.cursor()
                    for _, row in req_df.iterrows():
                        c.execute(f"SELECT COUNT(*) FROM books WHERE owner_id='{row['帳號']}' AND book_name='{row['書名']}' AND status IN ('借閱中', '保留待領取', '少領異常')")
                        owned_counts.append(c.fetchone()[0])
                    req_df['已持有數'] = owned_counts
                    
                    st.caption("**【快捷核准】**：班隊「✅全核准」或準則「✅核准」\n**【單筆修改】**：選擇「📋自訂」，修改核准發放的數量(填 0 即為踢退)。")
                    
                    unit_actions = {}
                    book_actions = {}
                    final_decisions = {}
                    
                    for unit_name in req_df['班隊'].unique():
                        with st.container(border=True):
                            st.markdown(
                                f"""<div style="text-align: center; margin-bottom: 10px; width: 100%; overflow: hidden;">
                                    <span style="font-size: clamp(14px, 4.5vw, 22px); font-weight: bold; color: #1C83E1; white-space: nowrap; letter-spacing: -0.5px;">【{unit_name}】</span>
                                </div>""", unsafe_allow_html=True
                            )
                            
                            unit_actions[unit_name] = st.radio(f"【{unit_name}】批次處理", ["🔽展開", "✅全核准", "❌全踢退"], horizontal=True, key=f"u_req_{unit_name}", label_visibility="collapsed")
                            unit_df = req_df[req_df['班隊'] == unit_name]
                            
                            if unit_actions[unit_name] == "✅全核准":
                                st.success(f"✨ 將全數核准發放【{unit_name}】申請的所有準則！")
                                for _, row in unit_df.iterrows(): final_decisions[row['單號']] = row['申請數量']
                            elif unit_actions[unit_name] == "❌全踢退":
                                st.error(f"🚨 將全數踢退【{unit_name}】申請的所有準則！")
                                for _, row in unit_df.iterrows(): final_decisions[row['單號']] = 0
                            else:
                                st.divider()
                                for _, row in unit_df.iterrows():
                                    req_id, b_name, req_qty, owned = row['單號'], row['書名'], row['申請數量'], row['已持有數']
                                    st.markdown(f"**📘 {b_name}** (申請: **{req_qty}** 本 | 已持有: {owned} 本)")
                                    book_actions[req_id] = st.radio(f"處理 {req_id}", ["📋自訂", "✅核准", "❌踢退"], horizontal=True, key=f"b_req_rad_{req_id}", label_visibility="collapsed")
                                    
                                    if book_actions[req_id] == "✅核准":
                                        st.success(f"✨ 核准發放 {req_qty} 本"); final_decisions[req_id] = req_qty
                                    elif book_actions[req_id] == "❌踢退":
                                        st.error(f"🚨 踢退此項申請"); final_decisions[req_id] = 0
                                    else:
                                        approve_qty = st.number_input(f"設定核准數量", min_value=0, max_value=int(req_qty), value=int(req_qty), key=f"num_{req_id}", help="輸入 0 視同踢退此項目")
                                        final_decisions[req_id] = approve_qty
                                    st.write("")
                    
                    st.markdown("---")
                    if st.button("💾 送出核准結果", type="primary", use_container_width=True):
                        c = conn.cursor()
                        processed_count = 0
                        for _, row in req_df.iterrows():
                            req_id, req_login, req_book, req_qty, req_unit = row['單號'], row['帳號'], row['書名'], row['申請數量'], row['班隊']
                            approve_qty = final_decisions.get(req_id, 0)
                            if approve_qty > req_qty: approve_qty = req_qty
                            if approve_qty < 0: approve_qty = 0
                            
                            c.execute(f"SELECT id FROM books WHERE book_name='{req_book}' AND status='在庫' LIMIT {req_qty}")
                            reserved_ids = [b[0] for b in c.fetchall()]
                            if not reserved_ids:
                                c.execute(f"SELECT id FROM books WHERE book_name='{req_book}' AND status='審核中(已圈存)' AND owner_id='{req_login}' LIMIT {req_qty}")
                                reserved_ids = [b[0] for b in c.fetchall()]
                                
                            approved_ids, rejected_ids = reserved_ids[:approve_qty], reserved_ids[approve_qty:]
                            
                            if approved_ids: c.execute(f"UPDATE books SET status='保留待領取', owner_id='{req_login}' WHERE id IN ({','.join(map(str, approved_ids))})")
                            if rejected_ids: c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id IN ({','.join(map(str, rejected_ids))})")
                                
                            now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                            if approve_qty > 0:
                                c.execute(f"UPDATE borrow_requests SET status='已核准(實發{approve_qty}本)' WHERE id={req_id}")
                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "核准借閱", f"核准 {req_book} {approve_qty} 本給 {req_unit}"))
                            else:
                                c.execute(f"UPDATE borrow_requests SET status='已踢退(砍單退件)' WHERE id={req_id}")
                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "踢退借閱", f"全數踢退 {req_unit} 的 {req_book} 申請"))
                            processed_count += 1
                        conn.commit()
                        st.success(f"✅ 批次審核完成！共處理 {processed_count} 筆申請。")
                        import time; time.sleep(1.5); st.rerun()
                else:
                    st.info("目前無待核准的準則。")

                st.markdown("---")
                st.subheader("🔴 領取異常警示 (少領退庫)")
                abnormal_df = pd.read_sql_query(f"SELECT b.id, u.unit as 班隊, b.book_name as 書名, b.serial_number as 序號 FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='少領異常' AND u.squadron IN ({sq_in_clause}) ORDER BY u.unit, b.book_name", conn)
                if not abnormal_df.empty:
                    st.error("⚠️ 發現訓員回報少領準則！請確認實體無誤後，將未領之額度釋放回庫房。")
                    edited_abn_dfs, abn_checks = {}, {}
                    for unit_name in abnormal_df['班隊'].unique():
                        st.markdown(f"### 🏢 異常單位：【{unit_name}】")
                        unit_df = abnormal_df[abnormal_df['班隊'] == unit_name]
                        for b_name in unit_df['書名'].unique():
                            b_df = unit_df[unit_df['書名'] == b_name].reset_index(drop=True)
                            u_key = f"abn_{unit_name}_{b_name}"
                            col_chk, col_exp = st.columns([1.5, 8.5])
                            with col_chk:
                                st.write(""); abn_checks[u_key] = st.checkbox(f"☑️ 全結案 ({len(b_df)}本)", key=f"abn_all_{u_key}")
                            with col_exp:
                                with st.expander(f"📘 {b_name} (待釋放 {len(b_df)} 本)"):
                                    if abn_checks[u_key]:
                                        st.success(f"✨ 已勾選全數結案！這 {len(b_df)} 本準則將釋放回庫房。")
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
                                if abn_checks[u_key]: resolved_ids.extend(unit_df[unit_df['書名'] == b_name]["id"].tolist())
                                elif edited_abn_dfs[u_key] is not None: resolved_ids.extend(edited_abn_dfs[u_key][edited_abn_dfs[u_key]["✅ 結案"] == True]["id"].tolist())
                        if resolved_ids:
                            c = conn.cursor()
                            c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id IN ({','.join(map(str, resolved_ids))})")
                            now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                            c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "異常處理", f"將少領的 {len(resolved_ids)} 本額度釋放回庫房"))
                            conn.commit()
                            st.success(f"✅ 成功結案！已釋放 {len(resolved_ids)} 本準則回大庫房。")
                            import time; time.sleep(1.5); st.rerun()
                        else:
                            st.warning("⚠️ 尚未勾選任何處理項目！")
                else:
                    st.success("目前無異常少領通報。")

            elif menu == "📥 準則歸還核准":
                st.subheader("📥 歸還點收與遺失追查")
                ret_tabs = st.tabs(["📥 待點收清單", "🚨 遺失裝備追查榜"])
                
                with ret_tabs[0]:
                    return_df = pd.read_sql_query(f"SELECT b.id, u.unit as 班隊, b.book_name as 書名, b.serial_number as 序號, b.owner_id FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='歸還中' AND u.squadron IN ({sq_in_clause}) ORDER BY u.unit, b.book_name", conn)
                    if not return_df.empty:
                        st.caption("**【快捷審核】**：班隊「✅ 全收」或準則「✅ 審核」\n**【踢退為遺失】**：若實體短少，請點「❌ 踢退」，該裝備將轉入『遺失追查榜』。")
                        unit_actions, book_actions, edited_receive_dfs = {}, {}, {}
                        
                        for unit_name in return_df['班隊'].unique():
                            with st.container(border=True):
                                st.markdown(
                                    f"""<div style="text-align: center; margin-bottom: 10px; width: 100%; overflow: hidden;">
                                        <span style="font-size: clamp(14px, 4.5vw, 22px); font-weight: bold; color: #1C83E1; white-space: nowrap; letter-spacing: -0.5px;">【{unit_name}】</span>
                                    </div>""", unsafe_allow_html=True
                                )
                                unit_actions[unit_name] = st.radio(f"【{unit_name}】批次處理", ["🔽展開","✅全審核","❌全踢退"], horizontal=True, key=f"u_rad_{unit_name}", label_visibility="collapsed")
                                
                                if unit_actions[unit_name] == "✅全審核":
                                    st.success(f"✨ 將全數審核【{unit_name}】所有歸還準則！")
                                elif unit_actions[unit_name] == "❌全踢退":
                                    st.error(f"🚨 將全數踢退並列為遺失！")
                                else:
                                    st.divider()
                                    unit_df = return_df[return_df['班隊'] == unit_name]
                                    for b_name in unit_df['書名'].unique():
                                        b_df = unit_df[unit_df['書名'] == b_name].reset_index(drop=True)
                                        u_b_key = f"{unit_name}_{b_name}"
                                        st.markdown(f"**📘 {b_name}** (待處理 {len(b_df)} 本)")
                                        book_actions[u_b_key] = st.radio(f"{b_name} 處理", ["📋明細", "✅ 審核", "❌ 踢退"], horizontal=True, key=f"b_rad_{u_b_key}", label_visibility="collapsed")
                                        
                                        if book_actions[u_b_key] == "✅ 審核": st.success(f"✨ 將全審核此項 {len(b_df)} 本！")
                                        elif book_actions[u_b_key] == "❌ 踢退": st.error(f"🚨 將全踢退此項 {len(b_df)} 本為遺失！")
                                        else:
                                            with st.expander("🔽 展開序號"):
                                                b_df.insert(0, "❌踢退", False); b_df.insert(0, "✅審核", False)
                                                edited_receive_dfs[u_b_key] = st.data_editor(
                                                    b_df, hide_index=True, disabled=["id", "班隊", "書名", "序號", "owner_id"], use_container_width=True, 
                                                    column_config={"✅審核": st.column_config.CheckboxColumn("✅審核"), "❌踢退": st.column_config.CheckboxColumn("❌踢退(轉遺失)"), "id": None, "班隊": None, "書名": None, "owner_id": None}, 
                                                    key=f"editor_{u_b_key}"
                                                )
                                        st.write("")
                        
                        st.markdown("---")
                        if st.button("💾 送出點收結果", type="primary", use_container_width=True):
                            received_ids, rejected_ids = [], []
                            for unit_name in return_df['班隊'].unique():
                                if unit_actions[unit_name] == "✅全審核": received_ids.extend(return_df[return_df['班隊'] == unit_name]['id'].tolist())
                                elif unit_actions[unit_name] == "❌全踢退": rejected_ids.extend(return_df[return_df['班隊'] == unit_name]['id'].tolist())
                                else:
                                    unit_df = return_df[return_df['班隊'] == unit_name]
                                    for b_name in unit_df['書名'].unique():
                                        u_b_key = f"{unit_name}_{b_name}"
                                        if book_actions.get(u_b_key) == "✅ 審核": received_ids.extend(unit_df[unit_df['書名'] == b_name]['id'].tolist())
                                        elif book_actions.get(u_b_key) == "❌ 踢退": rejected_ids.extend(unit_df[unit_df['書名'] == b_name]['id'].tolist())
                                        elif edited_receive_dfs.get(u_b_key) is not None:
                                            edited_df = edited_receive_dfs[u_b_key]
                                            received_ids.extend(edited_df[edited_df["✅審核"] == True]["id"].tolist())
                                            rejected_ids.extend(edited_df[edited_df["❌踢退"] == True]["id"].tolist())
                            
                            has_action = False
                            c = conn.cursor()
                            now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                            
                            if received_ids:
                                id_list_str = ','.join(map(str, received_ids))
                                c.execute(f"SELECT u.unit, b.book_name, COUNT(b.id) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.id IN ({id_list_str}) GROUP BY u.unit, b.book_name")
                                recv_details = c.fetchall()
                                c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id IN ({id_list_str})")
                                for u_name, b_name, qty in recv_details:
                                    c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "歸還點收", f"收訖 {u_name} 歸還 {b_name} {qty} 本"))
                                has_action = True
                                
                            if rejected_ids:
                                id_list_str = ','.join(map(str, rejected_ids))
                                c.execute(f"SELECT u.unit, b.book_name, COUNT(b.id) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.id IN ({id_list_str}) GROUP BY u.unit, b.book_name")
                                rej_details = c.fetchall()
                                c.execute(f"UPDATE books SET status='遺失待賠' WHERE id IN ({id_list_str})")
                                for u_name, b_name, qty in rej_details:
                                    c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "歸還踢退", f"踢退 {u_name} 歸還 {b_name} {qty} 本，轉列遺失追查"))
                                has_action = True
                                
                            if has_action:
                                conn.commit()
                                st.success(f"✅ 審核完成！收訖退庫 {len(received_ids)} 本，踢退列遺失 {len(rejected_ids)} 本。")
                                import time; time.sleep(1.5); st.rerun()
                            else:
                                st.warning("⚠️ 您尚未選擇任何審核或踢退動作！")
                    else:
                        st.success("目前各班隊皆無待歸還準則！")

                with ret_tabs[1]:
                    st.markdown("#### 🚨 遺失裝備追查榜")
                    st.info("💡 遭踢退之準則將列管於此，若尋獲實體書或完成賠償，請勾選結案退庫。")
                    lost_df = pd.read_sql_query(f"SELECT b.id, u.unit as 班隊, b.book_name as 書名, b.serial_number as 序號 FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='遺失待賠' AND u.squadron IN ({sq_in_clause}) ORDER BY u.unit, b.book_name", conn)
                    
                    if not lost_df.empty:
                        lost_df.insert(0, "✅ 尋獲/賠償結案", False)
                        edited_lost = st.data_editor(lost_df, hide_index=True, disabled=["id", "班隊", "書名", "序號"], width='stretch', column_config={"✅ 尋獲/賠償結案": st.column_config.CheckboxColumn("✅ 尋獲/賠償結案"), "id": None}, key="lost_recovery_table")
                        if st.button("🚔 批次執行結案退庫", type="primary"):
                            resolved_rows = edited_lost[edited_lost["✅ 尋獲/賠償結案"] == True]
                            resolved_ids = resolved_rows["id"].tolist()
                            if resolved_ids:
                                c = conn.cursor()
                                now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id IN ({','.join(map(str, resolved_ids))})")
                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "遺失結案", f"尋獲或完成賠償，退庫共 {len(resolved_ids)} 本準則"))
                                conn.commit()
                                st.success(f"✅ 成功結案 {len(resolved_ids)} 本準則並退回大庫房！")
                                import time; time.sleep(1.5); st.rerun()
                            else:
                                st.warning("⚠️ 請先勾選結案的準則！")
                    else:
                        st.success("✨ 裝備妥善率 100%！目前中隊無任何遺失待賠之準則！")

                # =============== L4 幹部的 Line 報表 ===============
    elif menu in ["💬 Line 報表專區", "Line 報表專區"] and st.session_state.role == 'L4':
        st.subheader("💬 Line 報表自動生成器")
        line_tabs = st.tabs(["🚚 借還動態彙總", "📦 裝備總清點(含遺失)"])
        sq_list = [s.strip() for s in st.session_state.squadron.split(',')]
        is_doc = "人事" in st.session_state.title or "文書" in st.session_state.title
        
        with line_tabs[0]:
            st.info("💡 產出今日「待領取」與「歸還中」之包裹物流清單。")
            if is_doc: target_squadron_dyn = st.selectbox("請選擇中隊 (動態彙總)", sq_list, key="dyn_sq")
            else: 
                target_squadron_dyn = sq_list[0]
                st.write(f"📍 **目前產出中隊：** {target_squadron_dyn}")
                
            if st.button("🚀 生成借還動態報表", type="primary"):
                borrow_df = pd.read_sql_query(f"SELECT u.unit, b.book_name, COUNT(b.id) as qty FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.squadron='{target_squadron_dyn}' AND b.status IN ('審核中(已圈存)', '保留待領取') GROUP BY u.unit, b.book_name", conn)
                return_df = pd.read_sql_query(f"SELECT u.unit, b.book_name, COUNT(b.id) as qty FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.squadron='{target_squadron_dyn}' AND b.status='歸還中' GROUP BY u.unit, b.book_name", conn)
                
                now = datetime.now(timezone(timedelta(hours=8)))
                tw_wd = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
                date_str = f"{now.month}/{now.day}（{tw_wd}）"
                msg = f"劉姐好，{target_squadron_dyn}借還書清單\n時間：{date_str}\n\n"
                
                all_units = set()
                if not borrow_df.empty: all_units.update(borrow_df['unit'].tolist())
                if not return_df.empty: all_units.update(return_df['unit'].tolist())
                
                if not all_units: msg += "今日無待辦物流。\n"
                else:
                    for unit in sorted(list(all_units)):
                        msg += f"==== 【{unit}】 ====\n借閱書目：\n"
                        b_u = borrow_df[borrow_df['unit'] == unit] if not borrow_df.empty else pd.DataFrame()
                        if not b_u.empty:
                            for _, r in b_u.iterrows(): msg += f"{r['book_name']}*{int(r['qty'])}\n"
                        else: msg += "無\n"
                        msg += "\n歸還書目：\n"
                        r_u = return_df[return_df['unit'] == unit] if not return_df.empty else pd.DataFrame()
                        if not r_u.empty:
                            for _, r in r_u.iterrows(): msg += f"{r['book_name']}*{int(r['qty'])}\n"
                        else: msg += "無\n"
                        msg += "\n"
                st.text_area("📋 複製區", value=msg.strip(), height=350)

        with line_tabs[1]:
            st.info("💡 拉出中隊下所有「借閱中」、「歸還中」、「遺失待賠」之準則清單。")
            if is_doc: target_squadron_inv = st.selectbox("請選擇中隊 (總清點)", sq_list, key="inv_sq")
            else: 
                target_squadron_inv = sq_list[0]
                st.write(f"📍 **目前產出中隊：** {target_squadron_inv}")
                
            if st.button("🚀 生成裝備總清點報表", type="primary"):
                inv_df = pd.read_sql_query(f"SELECT u.unit, b.book_name, b.serial_number, b.status FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.squadron='{target_squadron_inv}' AND b.status IN ('借閱中', '歸還中', '遺失待賠') ORDER BY u.unit, b.book_name", conn)
                now = datetime.now(timezone(timedelta(hours=8)))
                tw_wd = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
                inv_msg = f"劉姐好，{target_squadron_inv}裝備清點總表\n時間：{now.month}/{now.day}（{tw_wd}）\n\n"
                
                if inv_df.empty: inv_msg += "目前無外散之裝備。\n"
                else:
                    for unit in inv_df['unit'].unique():
                        inv_msg += f"==== 【{unit}】 ====\n"
                        u_df = inv_df[inv_df['unit'] == unit]
                        for b_name in u_df['book_name'].unique():
                            b_df = u_df[u_df['book_name'] == b_name]
                            inv_msg += f"📘 {b_name} * {len(b_df)}\n"
                            serials = [str(r['serial_number']).strip() + ("(遺失)" if r['status']=='遺失待賠' else "(待退庫)" if r['status']=='歸還中' else "") for _, r in b_df.iterrows()]
                            inv_msg += f"[{', '.join(serials)}]\n\n"
                st.text_area("📋 清點複製區", value=inv_msg.strip(), height=350)

    elif menu in ["綜合查詢", "🔍 綜合查詢"]:
        st.header("🔍 綜合查詢")
        # 拆分後，這裡只剩下最純粹的書名與序號查詢，全階級通用
        search_type = st.radio("查詢模式", ["查書名", "查序號"], horizontal=True)

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

    elif menu == "📊 中隊持有現況":
        st.header(f"📊 【{st.session_state.squadron}】所屬班隊準則持有現況")
        st.info("💡 點擊下方各班隊名稱，即可展開查看該班隊目前持有的所有準則與詳細序號。")
        
        if st.session_state.role in ['L1', 'L2']:
            unit_query = "SELECT DISTINCT u.unit FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status IN ('借閱中', '保留待領取', '少領異常', '歸還中')"
        else:
            sq_list = [s.strip() for s in st.session_state.squadron.split(',')]
            sq_in_clause = "'" + "','".join(sq_list) + "'"
            unit_query = f"SELECT DISTINCT u.unit FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.squadron IN ({sq_in_clause}) AND b.status IN ('借閱中', '保留待領取', '少領異常', '歸還中')"
            
        units_df = pd.read_sql_query(unit_query, conn)
        if units_df.empty:
            st.success("✨ 目前所屬中隊無任何班隊持有準則 (皆已歸還或無借閱)。")
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

    elif menu in ["操作紀錄", "🗂️ 操作紀錄"] and st.session_state.role in ['L1', 'L2', 'L3', 'L4']:
        st.header("🗂️ 系統操作紀錄")
        
        search_keyword = st.text_input("🔍 搜尋紀錄 (可輸入班隊、動作、準則名稱等)", placeholder="例如：借閱、M2A2、第一中隊...")
        
        log_query = """
            SELECT a.timestamp as 時間, 
                   COALESCE(
                       CASE 
                           WHEN u.role = 'L5' THEN u.unit
                           WHEN u.role IN ('L1', 'L2', 'L3', 'L4') THEN u.squadron || '-' || u.title || CASE WHEN u.name IS NOT NULL AND u.name != '' AND u.name != '代表' THEN '(' || u.name || ')' ELSE '' END
                           ELSE a.user_id 
                       END, a.user_id
                   ) as 操作者, 
                   a.action as 動作, 
                   a.details as 詳細內容 
            FROM action_logs a
            LEFT JOIN users u ON a.user_id = u.login_id
        """
        if search_keyword:
            safe_kw = search_keyword.replace("'", "''")
            log_query += f" WHERE a.details LIKE '%%{safe_kw}%%' OR a.action LIKE '%%{safe_kw}%%' OR u.unit LIKE '%%{safe_kw}%%' OR u.name LIKE '%%{safe_kw}%%'"
            
        log_query += " ORDER BY a.id DESC LIMIT 300"
        logs_df = pd.read_sql_query(log_query, conn)
        
        if logs_df.empty:
            st.info("📭 目前無操作紀錄。")
        else:
            # 加入精美表情符號映射
            def add_emoji(action):
                act = str(action)
                if '借閱' in act: return f"📤 {act}"
                if '歸還' in act: return f"📥 {act}"
                if '核准' in act: return f"✅ {act}"
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


















