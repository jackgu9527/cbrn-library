import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
import os
import glob
import psycopg2
from psycopg2 import pool
from psycopg2 import IntegrityError
import warnings
import extra_streamlit_components as stx  # 🚀 新增餅乾套件
import requests  # 🚀 新增 LINE 通訊模組

# 關閉 Pandas 對於未嚴格使用 SQLAlchemy 的警告
warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

# ==========================================
# 1. 系統初始化與資料庫設定 (渦輪加速連線池)
# ==========================================
st.set_page_config(page_title="大隊部準則管理系統", layout="wide")

# === 🍪 餅乾通行證管理器 ===
cookie_manager = stx.CookieManager()

# 🚨 終極登出攔截器：確保銷毀指令能完整傳達到瀏覽器
if st.session_state.get('logout_triggered'):
    try:
        cookie_manager.delete('sys_user_token')
    except KeyError:
        pass
        
    st.session_state.clear()
    st.session_state['force_logout'] = True
    st.session_state['sys_toast'] = "👋 登出成功！安全連線已銷毀。"

# === 🚀 全域快閃通知 (Toast) 接收器 ===
if 'sys_toast' in st.session_state:
    st.toast(st.session_state['sys_toast'])
    del st.session_state['sys_toast']

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
csv_candidates = [f for f in glob.glob(os.path.join(BASE_DIR, '*.csv')) if '準則資料庫' in f]
if not csv_candidates:
    csv_candidates = glob.glob(os.path.join(BASE_DIR, '*.csv'))
CSV_FILE = csv_candidates[0] if csv_candidates else None

@st.cache_resource(ttl=3600)
def get_pool():
    return pool.ThreadedConnectionPool(1, 20, st.secrets["DATABASE_URL"], connect_timeout=5)

def get_db_connection():
    db_pool = get_pool()
    conn = db_pool.getconn()
    try:
        with conn.cursor() as c:
            c.execute("SELECT 1")
    except Exception:
        db_pool.putconn(conn, close=True)
        conn = db_pool.getconn()
    return conn

def release_connection(conn):
    try:
        get_pool().putconn(conn)
    except Exception:
        pass

def send_line_notify(message):
    try:
        token = st.secrets.get("LINE_NOTIFY_TOKEN")
        if not token: return
        headers = {"Authorization": f"Bearer {token}"}
        data = {"message": message}
        requests.post("https://notify-api.line.me/api/notify", headers=headers, data=data)
    except Exception:
        pass 

def apply_shadow_sort(df, has_unit=False):
    if df.empty or 'status' not in df.columns or 'book_name' not in df.columns:
        return df
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
                        login_id TEXT UNIQUE, password TEXT, role TEXT, 
                        squadron TEXT, title TEXT, discharge_date DATE, 
                        status TEXT DEFAULT '啟用'
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
                ('admin', '1234', 'L1', '大隊部', '系統管理員', None, '啟用'),
                ('l1_s1', '1234', 'L1', '學生一中隊', '中隊長', None, '啟用'),
                ('l1_s2', '1234', 'L1', '學生二中隊', '中隊長', None, '啟用'),
                ('l1_a1', '1234', 'L1', '學員一中隊', '中隊長', None, '啟用'),
                ('l1_a2', '1234', 'L1', '學員二中隊', '中隊長', None, '啟用'),
                ('l1_u1', '1234', 'L1', '聯合中隊①', '文書兵', None, '啟用'),
                ('l1_u2', '1234', 'L1', '聯合中隊②', '文書兵', None, '啟用'),
                ('l2_test', '1234', 'L2', '學生一中隊', '煙幕士兵班115-1期', '2026-12-31', '啟用')
            ]
            c.executemany("INSERT INTO users (login_id, password, role, squadron, title, discharge_date, status) VALUES (%s,%s,%s,%s,%s,%s,%s)", default_users)
        
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
                            pub_date = str(row['出版日期']).strip()[:-2] if '出版日期' in row and pd.notna(row['出版日期']) and str(row['出版日期']).strip().endswith('.0') else str(row.get('出版日期', '')).strip()
                            book_title = f"{raw_title} [{pub_date}]" if pub_date else raw_title
                            
                            qty = int(row['數量']) if '數量' in row and pd.notna(row['數量']) else int(row.get('化訓準則館', 1))
                            for i in range(1, qty + 1):
                                insert_data.append((book_title, f"{book_title}-{i:03d}", '在庫', '在庫'))
                    c.executemany("INSERT INTO books (book_name, serial_number, owner_id, status) VALUES (%s,%s,%s,%s)", insert_data)
                except Exception as e: pass
        conn.commit()
    finally:
        release_connection(conn)

try:
    init_db()
except Exception as e:
    st.error(f"資料庫連線失敗！請檢查 Secrets 或網路狀態。詳細錯誤：{e}")
    st.stop()

# ==========================================
# ⚡ 幽靈背景引擎：結訓日 24:00 全自動清查
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
        
        c.execute(f"SELECT id, login_id, title FROM users WHERE role='L2' AND discharge_date < '{today_str}' AND status='啟用'")
        overdue_users = c.fetchall()
        for u_id, u_login, u_title in overdue_users:
            c.execute(f"UPDATE books SET status='歸還中' WHERE owner_id='{u_login}' AND status IN ('借閱中', '保留待領取', '少領異常')")
            c.execute(f"UPDATE users SET status='結訓凍結' WHERE id={u_id}")
            c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, "SYSTEM", "結訓凍結", f"班隊 {u_title} 已結訓，自動代為歸還並凍結帳號。"))
                
        c.execute("SELECT id, login_id, title FROM users WHERE role='L2' AND status='結訓凍結'")
        frozen_users = c.fetchall()
        for f_id, f_login, f_title in frozen_users:
            c.execute(f"SELECT COUNT(*) FROM books WHERE owner_id='{f_login}'")
            if c.fetchone()[0] == 0:
                c.execute(f"DELETE FROM users WHERE id={f_id}")
                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, "SYSTEM", "帳號註銷", f"班隊 {f_title} 準則已結清，自動刪除凍結帳號。"))
                    
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
if 'logged_in' not in st.session_state and not st.session_state.get('force_logout'):
    stored_user = cookie_manager.get('sys_user_token')
    if stored_user:
        conn = get_db_connection()
        try:
            safe_user_id = str(stored_user)
            user = pd.read_sql_query("SELECT * FROM users WHERE login_id=%s", conn, params=(safe_user_id,))
            if not user.empty and user.iloc[0]['status'] not in ['待審核', '停權', '結訓凍結']:
                for col in user.columns: st.session_state[col] = user.iloc[0][col]
                st.session_state['logged_in'] = True
        finally:
            release_connection(conn)

if 'logged_in' not in st.session_state:
    st.markdown("##  大隊部準則管理系統")
    tab1, tab2 = st.tabs([" 系統登入", " 班隊註冊"])
    
    with tab1:
        login_id = st.text_input("帳號 (Login ID)")
        password = st.text_input("密碼 (Password)", type="password")
        if st.button("登入", type="primary"):
            conn = get_db_connection()
            try:
                user = pd.read_sql_query("SELECT * FROM users WHERE login_id=%s AND password=%s", conn, params=(login_id, password))
                if not user.empty:
                    if user.iloc[0]['status'] == '待審核': st.warning("⚠️ 您的帳號尚未開通，請等待幹部審核。")
                    elif user.iloc[0]['status'] == '停權': st.error("🚨 您的帳號因違規停權！請聯絡幹部處理。")
                    elif user.iloc[0]['status'] == '結訓凍結': st.error("❄️ 您的班隊已結訓，帳號已凍結鎖定！若有準則問題請聯絡幹部。")
                    else:
                        for col in user.columns: st.session_state[col] = user.iloc[0][col]
                        st.session_state['logged_in'] = True
                        cookie_manager.set('sys_user_token', login_id, expires_at=datetime.now() + timedelta(days=30))
                        log_action(login_id, "登入", "使用者成功登入系統")
                        import time; time.sleep(0.5) 
                        st.rerun()
                else: st.error("❌ 帳號或密碼錯誤")
            finally:
                release_connection(conn)

    with tab2:
        # 🚀 升級 Tooltip
        st.subheader("班隊註冊", help="新進班隊請在此註冊，送出後將由幹部審核開通。")
        reg_squadron = st.selectbox("所屬中隊", ["學員一中隊", "學員二中隊", "學生一中隊", "學生二中隊", "聯合中隊①", "聯合中隊②", "大隊部"])
        reg_title = st.text_input("班隊全銜 (將作為系統顯示名稱)")
        reg_id = st.text_input("設定登入帳號")
        reg_pw = st.text_input("設定登入密碼", type="password")
        reg_date = st.date_input("結訓日期")
        
        if st.button("送出註冊申請"):
            if reg_title and reg_id and reg_pw:
                conn = get_db_connection()
                try:
                    c = conn.cursor()
                    c.execute("SELECT COUNT(*) FROM users WHERE login_id=%s", (reg_id,))
                    if c.fetchone()[0] > 0: st.error("❌ 此帳號已被使用！")
                    else:
                        c.execute("INSERT INTO users (login_id, password, role, squadron, title, discharge_date, status) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                  (reg_id, reg_pw, 'L2', reg_squadron, reg_title, reg_date.strftime('%Y-%m-%d'), '待審核'))
                        conn.commit()
                        log_action(reg_id, "註冊申請", f"{reg_squadron} {reg_title} 提出註冊申請")
                        st.session_state['sys_toast'] = "✅ 註冊申請已送出！請等待幹部審核後即可登入。"
                        st.rerun()
                finally:
                    release_connection(conn)
            else: st.warning("請填寫所有欄位")
    st.stop()

run_ghost_cleanup()

# ==========================================
# 3. 介面顯示邏輯與左側指揮樞紐
# ==========================================
user_sq = str(st.session_state.squadron).strip()

if user_sq == '大隊部': 
    sq_list = ['大隊部', '聯合中隊①', '聯合中隊②', '學員一中隊', '學員二中隊', '學生一中隊', '學生二中隊']
elif user_sq == '聯合中隊①': 
    sq_list = ['聯合中隊①', '學員一中隊', '學生一中隊']
elif user_sq == '聯合中隊②': 
    sq_list = ['聯合中隊②', '學員二中隊', '學生二中隊']
else: 
    sq_list = [user_sq]

with st.sidebar:
    st.markdown(f"### {'🧑‍✈️' if st.session_state.role == 'L1' else '🎓'} {st.session_state.title}")
    st.markdown(f"🆔 {st.session_state.login_id}")
    st.markdown("---")
    
    if st.session_state.role == 'L1':
        if len(sq_list) > 1:
            st.session_state['current_sq'] = st.selectbox("🏢 當前指揮視角", sq_list, key="global_sq_selector")
        else:
            st.session_state['current_sq'] = sq_list[0]
            st.markdown(f"📍 **管轄中隊：** `{st.session_state['current_sq']}`")
    else:
        st.session_state['current_sq'] = st.session_state.squadron
        st.markdown(f"📍 **所屬中隊：** `{st.session_state['current_sq']}`")
        
    st.markdown("---")
    
    if st.session_state.role == 'L1':
        menu_options = ["🏠 首頁", "👥 帳號管理", "📤 準則借閱審核", "📥 準則歸還審核", "💬 回報專區", "📊 準則現況", "🔍 綜合查詢", "🗂️ 操作紀錄"]
        if user_sq == '大隊部': 
            menu_options.insert(2, "⚙️ 系統管理")
    else:
        menu_options = ["🏠 首頁", "📤 準則借閱", "🏷️ 序號登載", "📥 準則歸還", "💬 回報專區", "🔍 綜合查詢"]
        
    menu = st.radio("功能導覽", menu_options)
    
    st.markdown("---")
    if st.button("🚪 登出系統"):
        st.session_state['logout_triggered'] = True
        st.rerun()

target_sq = st.session_state.get('current_sq', user_sq)
if target_sq == '大隊部':
    target_sq_list = ['大隊部', '學員一中隊', '學員二中隊', '學生一中隊', '學生二中隊']
elif target_sq == '聯合中隊①':
    target_sq_list = ['聯合中隊①', '學員一中隊', '學生一中隊']
elif target_sq == '聯合中隊②':
    target_sq_list = ['聯合中隊②', '學員二中隊', '學生二中隊']
else:
    target_sq_list = [target_sq]
    
st.session_state.dynamic_sq_in_clause = "'" + "','".join(target_sq_list) + "'"

# ==========================================
# 4. 主畫面邏輯
# ==========================================
conn = get_db_connection()
try:
    if menu in ["首頁", "🏠 首頁"]:
        # 🚀 升級 Tooltip
        st.header("📊 首頁", help="查看今日營區戰情概況、待辦事項總覽與個人準則狀態。")
        
        # ======== 🟢 L1：幹部 / 管理員視角 ========
        if st.session_state.role == 'L1':
            target_sq = st.session_state.get('current_sq', '')
            st.markdown(f"**{st.session_state.title}** 長官好，以下為【{target_sq}】今日戰情概況：")
            
            dyn_in = st.session_state.dynamic_sq_in_clause
            sq_filter = f"IN ({dyn_in})"
            
            pending_reg = pd.read_sql_query(f"SELECT COUNT(*) FROM users WHERE status='待審核' AND squadron {sq_filter}", conn).iloc[0,0]
            pending_bor = pd.read_sql_query(f"SELECT COUNT(*) FROM borrow_requests br JOIN users u ON br.login_id = u.login_id WHERE br.status='待審核' AND u.squadron {sq_filter}", conn).iloc[0,0]
            pending_ret = pd.read_sql_query(f"SELECT COUNT(*) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='歸還中' AND u.squadron {sq_filter}", conn).iloc[0,0]
            pending_abn = pd.read_sql_query(f"SELECT COUNT(*) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='少領異常' AND u.squadron {sq_filter}", conn).iloc[0,0]
            
            c_m1, c_m2, c_m3, c_m4 = st.columns(4)
            c_m1.metric("📝 待審核帳號", f"{pending_reg} 件")
            c_m2.metric("📥 待借閱準則", f"{pending_bor} 件")
            c_m3.metric("📤 待歸還準則", f"{pending_ret} 件")
            c_m4.metric("🔴 借閱異常警示", f"{pending_abn} 件")
            st.markdown("---")

        # ======== 🟢 L2：訓員視角 ========
        elif st.session_state.role == 'L2':
            st.markdown(f"**所屬單位：** {st.session_state.squadron} - {st.session_state.title}")
            if st.session_state.discharge_date:
                d_date = datetime.strptime(str(st.session_state.discharge_date), '%Y-%m-%d').date()
                today = datetime.now().date()
                days_left = (d_date - today).days
                if days_left < 0: st.error(f"🚨 已逾結訓日！請盡速完成準則歸還。")
                elif days_left <= 3: st.warning(f"⚠️ 結訓倒數：{days_left} 天！")
                else: st.info(f"📅 距離結訓日還有：{days_left} 天")

            st.markdown("#### 📦 準則狀態總覽")
            
            br_df = pd.read_sql_query(f"SELECT book_name, quantity FROM borrow_requests WHERE login_id='{st.session_state.login_id}' AND status='待審核'", conn)
            bk_df = pd.read_sql_query(f"SELECT book_name, status FROM books WHERE owner_id='{st.session_state.login_id}' AND status IN ('保留待領取', '借閱中', '歸還中')", conn)

            status_items = []
            if not br_df.empty:
                for _, r in br_df.groupby('book_name')['quantity'].sum().reset_index().iterrows():
                    status_items.append({'book_name': r['book_name'], 'qty': int(r['quantity']), 'status': '申請中'})
            if not bk_df.empty:
                st_map = {'保留待領取': '已審核', '借閱中': '借閱中', '歸還中': '歸還中'}
                for _, r in bk_df.groupby(['book_name', 'status']).size().reset_index(name='qty').iterrows():
                    status_items.append({'book_name': r['book_name'], 'qty': int(r['qty']), 'status': st_map.get(r['status'], r['status'])})

            if not status_items:
                st.success("✨ 您目前沒有任何準則。")
            else:
                df_items = apply_shadow_sort(pd.DataFrame(status_items))
                style_map = {'申請中': ('🔵', '#4da6ff'), '已審核': ('🟡', '#ffb84d'), '借閱中': ('🟢', '#4CAF50'), '歸還中': ('🔴', '#ff6666')}
                
                for _, r in df_items.iterrows():
                    icon, color = style_map.get(r['status'], ('🔹', 'gray'))
                    with st.container(border=True):
                        st.markdown(f"""
                        <div style="font-size: 15px; font-weight: bold; color: {color}; margin-bottom: 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                            {icon} {r['book_name']}
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 14px; color: {color}; padding-left: 28px;">
                            <span>(共 {r['qty']} 本)</span><span style="text-align: right;">狀態：{r['status']}</span>
                        </div>
                        """, unsafe_allow_html=True)
                        
        # ======== 🟢 全局共用：個人設定修改面板 ========
        st.markdown("---")
        with st.expander("⚙️ 個人帳號與資料設置", expanded=False):
            # 🚀 升級 Tooltip
            if st.session_state.role == 'L1':
                st.markdown("#### ⚙️ 個人設定", help="幹部可隨時修改您的顯示職稱、登入帳號與密碼。")
                col_t, col_i, col_p = st.columns(3)
                with col_t: new_title = st.text_input("職務", value=st.session_state.title, key="daily_title")
                with col_i: new_id = st.text_input("登入帳號", value=st.session_state.login_id, key="daily_id")
                with col_p: new_pwd = st.text_input("登入密碼", type="password", placeholder="若不修改請留空", key="daily_pw")
            else:
                st.markdown("#### ⚙️ 個人設定", help="訓員可隨時修改您的登入帳號與密碼。(班隊全銜由幹部統一管理)")
                new_title = st.session_state.title 
                col_i, col_p = st.columns(2)
                with col_i: new_id = st.text_input("登入帳號", value=st.session_state.login_id, key="daily_id")
                with col_p: new_pwd = st.text_input("登入密碼", type="password", placeholder="若不修改請留空", key="daily_pw")
            
            if st.button("💾 儲存設定", key="save_daily_settings", type="primary"):
                c = conn.cursor()
                uid = int(st.session_state.id)
                final_id = new_id.strip() if new_id.strip() else st.session_state.login_id
                final_title = new_title.strip() if new_title.strip() else st.session_state.title
                
                c.execute("SELECT COUNT(*) FROM users WHERE login_id=%s AND id!=%s", (final_id, uid))
                if c.fetchone()[0] > 0: 
                    st.error("❌ 此帳號已被使用！")
                else:
                    pw_update = ", password=%s" if new_pwd else ""
                    params = [final_id, new_pwd, final_title, uid] if new_pwd else [final_id, final_title, uid]
                    
                    old_id = st.session_state.login_id
                    c.execute(f"UPDATE users SET login_id=%s{pw_update}, title=%s WHERE id=%s", tuple(params))
                    
                    if old_id != final_id:
                        c.execute("UPDATE books SET owner_id=%s WHERE owner_id=%s", (final_id, old_id))
                        c.execute("UPDATE borrow_requests SET login_id=%s WHERE login_id=%s", (final_id, old_id))
                        c.execute("UPDATE action_logs SET user_id=%s WHERE user_id=%s", (final_id, old_id))
                        
                    conn.commit()
                    st.success("✅ 設定已儲存！系統將重新載入...")
                    import time; time.sleep(1); st.session_state.clear(); st.rerun()

    # ======== 🟢 L2 專屬業務區 ========
    elif menu in ["序號登載", "🏷️ 序號登載"] and st.session_state.role == 'L2':
        # 🚀 升級 Tooltip
        st.header("🏷️ 序號登載", help="請將領取到的實體準則序號登載入系統。若有多本請用「半形逗號 ( , )」隔開；若發生實體數量短少，可勾選『借閱異常』進行通報。")

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
                            st.markdown(f"<div style='font-size: 15px; font-weight: bold; color: #ffb84d; margin-bottom: 8px;'>🟡 {b_name}</div><div style='font-size: 14px; color: black; padding-left: 28px; margin-bottom: 8px;'>(共 {qty} 本) 📝 請登載序號 (請用 , 隔開)</div>", unsafe_allow_html=True)
                            user_input = st.text_input(f"隱藏標題_{b_name}_p", label_visibility="collapsed", key=f"p_{b_name}")
                            abnormal = st.checkbox(f"☑️ 借閱異常：剩餘準則未借閱到勾選。", key=f"abn_{b_name}")
                            form_data[f"p_{b_name}"] = {'type': 'pending', 'ids': b_ids, 'input': user_input, 'abnormal': abnormal, 'b_name': b_name}

                    elif st_val == '借閱中':
                        current_s = [str(r['serial_number']).strip() for _, r in b_rows.iterrows() if pd.notna(r['serial_number'])]
                        with st.container(border=True):
                            st.markdown(f"<div style='font-size: 15px; font-weight: bold; color: #4CAF50; margin-bottom: 8px;'>🟢 {b_name}</div><div style='font-size: 14px; color: black; padding-left: 28px; margin-bottom: 8px;'>(共 {qty} 本) 📝 校正序號 (請用 , 隔開)</div>", unsafe_allow_html=True)
                            user_input = st.text_input(f"隱藏標題_{b_name}_c", value=", ".join(current_s), label_visibility="collapsed", key=f"c_{b_name}")
                            form_data[f"c_{b_name}"] = {'type': 'correct', 'rows': b_rows.to_dict('records'), 'input': user_input, 'b_name': b_name}

                st.markdown("---")
                if st.form_submit_button("💾 儲存序號", type="primary", use_container_width=True):
                    c = conn.cursor()
                    has_err = False
                    success_cnt = 0
                    
                    for key, data in form_data.items():
                        raw_input = [s.strip() for s in data['input'].split(',') if s.strip()]
                        b_name = data['b_name']
                        
                        if data['type'] == 'pending':
                            p_ids = data['ids']
                            if len(raw_input) > len(p_ids):
                                st.error(f"❌ 【{b_name}】輸入序號數量 ({len(raw_input)}) 超過待領取額度 ({len(p_ids)})！")
                                has_err = True; continue
                                
                            for i in range(len(p_ids)):
                                b_id = p_ids[i]
                                if i < len(raw_input):
                                    new_s = raw_input[i]
                                    c.execute("SELECT id, status FROM books WHERE serial_number=%s", (new_s,))
                                    check = c.fetchone()
                                    if check and check[1] == '在庫':
                                        c.execute(f"UPDATE books SET status='借閱中', owner_id='{st.session_state.login_id}' WHERE id={int(check[0])}")
                                        c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id={b_id}")
                                        success_cnt += 1
                                    elif not check:
                                        c.execute("UPDATE books SET serial_number=%s, status='借閱中' WHERE id=%s", (new_s, b_id))
                                        success_cnt += 1
                                    else:
                                        st.error(f"❌ 【{b_name}】序號 {new_s} 已被借閱！")
                                        has_err = True; break
                                elif data['abnormal']:
                                    c.execute(f"UPDATE books SET status='少領異常' WHERE id={b_id}")
                                    success_cnt += 1
                                    
                        elif data['type'] == 'correct':
                            b_rows = data['rows']
                            if len(raw_input) != len(b_rows) and len(raw_input) > 0:
                                st.error(f"❌ 【{b_name}】校正數量 ({len(raw_input)}) 與已借閱數量 ({len(b_rows)}) 不符！")
                                has_err = True; continue
                                
                            if len(raw_input) == len(b_rows):
                                for i, r in enumerate(b_rows):
                                    b_id = int(r['id'])
                                    old_s = str(r['serial_number']).strip()
                                    new_s = raw_input[i]
                                    if old_s != new_s:
                                        c.execute("SELECT id, status FROM books WHERE serial_number=%s", (new_s,))
                                        check = c.fetchone()
                                        if check and check[1] == '在庫':
                                            c.execute(f"UPDATE books SET status='借閱中', owner_id='{st.session_state.login_id}' WHERE id={int(check[0])}")
                                            c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id={b_id}")
                                            success_cnt += 1
                                        elif not check:
                                            c.execute("UPDATE books SET serial_number=%s WHERE id=%s", (new_s, b_id))
                                            success_cnt += 1
                                        else:
                                            st.error(f"❌ 【{b_name}】校正失敗：序號 {new_s} 已被他人借閱！")
                                            has_err = True; break
                                            
                    if not has_err and success_cnt > 0:
                        conn.commit()
                        st.session_state['sys_toast'] ="✅ 序號儲存成功！"
                        st.rerun()
                    elif not has_err and success_cnt == 0:
                        st.warning("⚠️ 尚未輸入或修改任何序號。")
    
    elif menu in ["準則借閱", "📤 準則借閱"] and st.session_state.role == 'L2':
        st.header("📤 準則借閱申請")
        c = conn.cursor()
        c.execute("SELECT book_name, COUNT(id) FROM books WHERE status='在庫' GROUP BY book_name")
        available_books = c.fetchall()
        
        if not available_books:
            st.warning("庫房無可借閱的準則。")
        else:
            # 🚀 升級 Tooltip
            st.subheader("🎯 設置預設借閱數量", help="設定後，下方所有選取的準則都會自動帶入此數量")
            default_req_qty = st.number_input("請輸入欲借閱的數量 (例如：貴班隊人數)", min_value=1, value=1)
            st.markdown("---")
            
            st.markdown("---")
            # 🚀 升級 Tooltip
            st.subheader("📚 第二步：選擇準則", help="請從下拉選單中挑選您需要的準則。選取後，下方會自動展開該準則的數量設定卡片。")
            book_options = [f"{b[0]} (庫存: {b[1]}本)" for b in available_books]
            selected_books = st.multiselect("選擇要借閱的準則", book_options)  # 👈 就是這行剛才被吃掉了！
              
            if selected_books:
                borrow_requests = {}
                can_submit = True 
                
                for selection in selected_books:
                    with st.container(border=True):
                        b_name = selection.split(" (")[0]
                        max_qty = int(selection.split("庫存: ")[1].replace("本)", ""))
                        
                        c.execute(f"SELECT COUNT(*) FROM books WHERE owner_id='{st.session_state.login_id}' AND book_name='{b_name}' AND status!='在庫'")
                        owned_count = int(c.fetchone()[0])
                        
                        c.execute(f"SELECT SUM(quantity) FROM borrow_requests WHERE login_id='{st.session_state.login_id}' AND book_name='{b_name}' AND status='待審核'")
                        pending_req = c.fetchone()[0]
                        pending_count = int(pending_req) if pending_req else 0
                        total_existing = owned_count + pending_count
                        
                        auto_val = min(default_req_qty, max_qty)
                        qty = st.number_input(f"欲借閱【{b_name}】的數量", min_value=1, max_value=max_qty, value=auto_val, key=f"req_{b_name}")
                        borrow_requests[b_name] = qty
                        
                        if total_existing > 0:
                            if pending_count > 0:
                                st.error(f"🚨 系統攔截：您目前已有 **{pending_count}** 本【{b_name}】正在「等待幹部審核中」，請勿重複送單！")
                                can_submit = False
                            else:
                                st.warning(f"⚠️ 系統偵測到您名下已持有 **{owned_count}** 本【{b_name}】。")
                                confirm_extra = st.checkbox(f"☑️ 我確認此為「缺少數量再額外申請」", key=f"chk_extra_{b_name}")
                                if not confirm_extra:
                                    can_submit = False
                
                st.markdown("---")
                if can_submit:
                    if st.button("🚀 送出借閱申請", type="primary", use_container_width=True):
                        now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                        for b_name, qty in borrow_requests.items():
                            c.execute("INSERT INTO borrow_requests (login_id, unit, book_name, quantity, status) VALUES (%s, %s, %s, %s, %s)", 
                                      (st.session_state.login_id, st.session_state.title, b_name, qty, '待審核'))
                            c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)",
                                      (now_time, st.session_state.login_id, "申請借閱", f"申請 {b_name} {qty} 本"))
                        conn.commit()
                        st.session_state['sys_toast'] ="✅ 申請已送出！請等待幹部審核。"
                        st.rerun()
                else:
                    st.error("🚨 發現重複借閱項目！請勾選上方確認框後，才能送出申請。")

    elif menu in ["💬 回報專區", "回報專區"] and st.session_state.role == 'L2':
        st.header("💬 Line 借還書回報")
        tabs = st.tabs(["🚚 借還書回報", "📱 準則清點回報"])
        
        with tabs[0]:
            # 🚀 升級 Tooltip
            st.subheader("🚚 借還書回報", help="請點擊下方生成清單，並點擊黑框右上角的「📋」一秒複製！")
            if st.button("🚀 生成借還書清單", type="primary"):
                br_pending = pd.read_sql_query(f"SELECT book_name, SUM(quantity) as qty FROM borrow_requests WHERE login_id='{st.session_state.login_id}' AND status='待審核' GROUP BY book_name", conn)
                bk_reserved = pd.read_sql_query(f"SELECT book_name, COUNT(id) as qty FROM books WHERE owner_id='{st.session_state.login_id}' AND status='保留待領取' GROUP BY book_name", conn)
                rt_df = pd.read_sql_query(f"SELECT book_name, COUNT(id) as qty FROM books WHERE owner_id='{st.session_state.login_id}' AND status='歸還中' GROUP BY book_name", conn)
                
                msg = f"報告，班隊：{st.session_state.title}\n借還書清單：\n\n【申請借閱】：\n"
                
                borrow_items = []
                if not br_pending.empty:
                    for _, r in br_pending.iterrows(): borrow_items.append({'book_name': r['book_name'], 'qty': int(r['qty']), 'status': '申請中'})
                if not bk_reserved.empty:
                    for _, r in bk_reserved.iterrows(): borrow_items.append({'book_name': r['book_name'], 'qty': int(r['qty']), 'status': '已審核'})
                
                if borrow_items:
                    df_b = apply_shadow_sort(pd.DataFrame(borrow_items))
                    for _, r in df_b.iterrows(): msg += f"{r['book_name']} * {r['qty']} ({r['status']})\n"
                else: 
                    msg += "無\n"
                
                msg += "\n【申請歸還】：\n"
                if not rt_df.empty:
                    rt_df['status'] = '歸還中'
                    rt_df = apply_shadow_sort(rt_df)
                    for _, r in rt_df.iterrows(): msg += f"{r['book_name']} * {int(r['qty'])} (歸還中)\n"
                else: msg += "無\n"
                
                st.code(msg.strip(), language="text")
                
        with tabs[1]:
            # 🚀 升級 Tooltip
            st.subheader("📱 準則清點回報", help="產出目前名下所有準則總數。點擊黑框右上角「📋」複製。")
            if st.button("🚀 生成清點報表", type="primary"):
                inv_df = pd.read_sql_query(f"SELECT book_name, status, COUNT(id) as qty FROM books WHERE owner_id='{st.session_state.login_id}' AND status IN ('借閱中', '歸還中') GROUP BY book_name, status", conn)
                msg = f"報告，班隊：{st.session_state.title}\n準則清點：\n\n"
                if inv_df.empty: msg += "無\n"
                else:
                    inv_df = apply_shadow_sort(inv_df)
                    for _, r in inv_df.iterrows():
                        msg += f"{r['book_name']} * {int(r['qty'])} ({r['status']})\n"
                
                st.code(msg.strip(), language="text")

    elif menu in ["準則歸還", "📥 準則歸還"] and st.session_state.role == 'L2':
        # 🚀 升級 Tooltip
        st.header("📤 準則歸還", help="【快捷歸還】：勾選各準則標題旁的「☑️ 全數歸還此項」即可將該類準則全數歸還。\n\n【部分歸還】：展開個別序號清單，單獨勾選要歸還的序號。")
        books_df = pd.read_sql_query(f"SELECT id, book_name as 書名, serial_number as 序號 FROM books WHERE owner_id='{st.session_state.login_id}' AND status='借閱中'", conn)
        
        if not books_df.empty:
            if 'l2_partial_return_memory' not in st.session_state:
                st.session_state['l2_partial_return_memory'] = {}
                
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
                                st.session_state['l2_partial_return_memory'][book_id] = edit_dict["勾選歸還"]

            category_checks = {} 
            edited_return_dfs = {}
            
            for b_name in books_df['書名'].unique():
                b_df = books_df[books_df['書名'] == b_name].reset_index(drop=True)
                qty = len(b_df)
                
                st.markdown(f"### 📘 {b_name}")
                col_chk, col_exp = st.columns([2.5, 7.5])
                
                with col_chk:
                    category_checks[b_name] = st.checkbox(f"☑️ 全數歸還此項 ({qty}本)", key=f"all_ret_{b_name}")
                    
                with col_exp:
                    with st.expander(f"🔽 展開個別序號 (點擊查看)"):
                        if category_checks[b_name]:
                            st.success(f"✨ 已選擇全數歸還！送出後將一併歸還這 {qty} 本準則。")
                            edited_return_dfs[b_name] = None 
                        else:
                            initial_checks = []
                            for _, row in b_df.iterrows():
                                b_id = row['id']
                                initial_checks.append(st.session_state['l2_partial_return_memory'].get(b_id, False))
                                
                            b_df.insert(0, "勾選歸還", initial_checks)
                            editor_key = f"return_editor_{b_name}"
                            edited_return_dfs[b_name] = st.data_editor(
                                b_df, 
                                hide_index=True, 
                                disabled=["id", "書名", "序號"], 
                                width='stretch', 
                                key=editor_key
                            )
                st.markdown("---") 
                
            if st.button("📤 送出目前的勾選項目", type="primary", use_container_width=True):
                selected_ids = []
                for b_name in books_df['書名'].unique():
                    if category_checks[b_name]:
                        full_b_df = books_df[books_df['書名'] == b_name]
                        selected_ids.extend(full_b_df["id"].tolist())
                    elif edited_return_dfs[b_name] is not None:
                        edited_df = edited_return_dfs[b_name]
                        checked_rows = edited_df[edited_df["勾選歸還"] == True]
                        selected_ids.extend(checked_rows["id"].tolist())
                
                if selected_ids:
                    selected_ids = list(set(selected_ids)) 
                    id_list_str = ','.join(map(str, selected_ids))
                    
                    c = conn.cursor()
                    c.execute(f"SELECT book_name, COUNT(id) FROM books WHERE id IN ({id_list_str}) GROUP BY book_name")
                    return_details = c.fetchall()
                    
                    c.execute(f"UPDATE books SET status='歸還中' WHERE id IN ({id_list_str})")
                    now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                    
                    for b_name, qty in return_details:
                        c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
                                  (now_time, st.session_state.login_id, "申請歸還", f"申請 {st.session_state.title} 歸還 {b_name} {qty} 本"))
                    conn.commit()
                    
                    if 'l2_partial_return_memory' in st.session_state: 
                        del st.session_state['l2_partial_return_memory']
                        
                    st.session_state['sys_toast'] = f"✅ 已送出 {len(selected_ids)} 本歸還申請！等待幹部審核。"
                    st.rerun()
                else:
                    st.warning("⚠️ 您尚未勾選任何需要歸還的準則！")
        else:
            st.success("✨ 您名下目前沒有需要歸還的準則！")

    # ======== 🟢 系統管理員專屬暗門 ========
    elif menu == "⚙️ 系統管理" and st.session_state.role == 'L1' and str(st.session_state.squadron).strip() == '大隊部':
        # 🚀 升級 Tooltip
        st.header("👑 系統管理員模式", help="全域人事卡片化管理：點開【中隊】，再點擊【職務/班隊標籤】，即可查看與修改所有人員的專屬卡片。")
        
        # ======== 🚀 新增：全域手動配發帳號中心 ========
        with st.expander("➕ 新增人員 / 班隊帳號 (管理員直配)", expanded=False):
            st.markdown("#### 📝 直接配發新帳號")
            col1, col2, col3 = st.columns(3)
            with col1:
                add_role = st.selectbox("身分", ["L1 (幹部)", "L2 (訓員)"], key="add_role")
                add_sq = st.selectbox("所屬中隊", ["大隊部", "學員一中隊", "學員二中隊", "學生一中隊", "學生二中隊", "聯合中隊①", "聯合中隊②"], key="add_sq")
            with col2:
                add_title = st.text_input("職務 / 班隊全銜", placeholder="例如：中隊長 或 煙幕班115-1期", key="add_title")
                add_id = st.text_input("登入帳號", key="add_id")
            with col3:
                add_pw = st.text_input("登入密碼", key="add_pw")
                add_status = st.selectbox("初始狀態", ["啟用", "待審核", "結訓凍結"], key="add_status")
                
            if st.button("🚀 立即建立帳號", type="primary"):
                if add_title and add_id and add_pw:
                    c = conn.cursor()
                    c.execute("SELECT COUNT(*) FROM users WHERE login_id=%s", (add_id,))
                    if c.fetchone()[0] > 0:
                        st.error("❌ 此帳號已被使用！請更換帳號名稱。")
                    else:
                        r_val = "L1" if "L1" in add_role else "L2"
                        c.execute("INSERT INTO users (login_id, password, role, squadron, title, status) VALUES (%s,%s,%s,%s,%s,%s)",
                                  (add_id, add_pw, r_val, add_sq, add_title, add_status))
                        conn.commit()
                        st.session_state['sys_toast'] = f"✅ 成功建立 {r_val} 帳號：{add_title}！"
                        st.rerun()
                else:
                    st.warning("⚠️ 請填寫完整資料 (職務/帳號/密碼不可為空)！")
        
        st.markdown("---")
        
        # ======== 🚀 現有帳號管理 (加入 L1/L2 調整功能) ========
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
                                with st.container(border=True):
                                    st.markdown(f"**👤 {row['title']}** ({row['role']})  \n🆔 帳號: `{row['login_id']}`  \n🔑 密碼: `{row['password']}`  \n{'🟢' if row['status']=='啟用' else '🔴'} 狀態: `{row['status']}`")
                                    
                                    with st.expander("✏️ 編輯詳細資料與權限"):
                                        col_edit1, col_edit2 = st.columns(2)
                                        with col_edit1:
                                            new_login = st.text_input("帳號", value=row['login_id'], key=f"l1_id_{uid}")
                                            new_pwd = st.text_input("密碼", value=row['password'], key=f"l1_pw_{uid}")
                                            
                                            role_opts = ["L1", "L2"]
                                            r_idx = role_opts.index(row['role']) if row['role'] in role_opts else 0
                                            new_role = st.selectbox("身分權限", role_opts, index=r_idx, key=f"l1_ro_{uid}")
                                            
                                        with col_edit2:
                                            new_sq = st.text_input("中隊", value=row['squadron'], key=f"l1_sq_{uid}")
                                            new_ti = st.text_input("職務/班隊", value=row['title'], key=f"l1_ti_{uid}")
                                            
                                            status_opts = ["啟用", "待審核", "結訓凍結", "停權"]
                                            idx = status_opts.index(row['status']) if row['status'] in status_opts else 0
                                            new_st = st.selectbox("狀態", status_opts, index=idx, key=f"l1_st_{uid}")
                                        
                                        col_save, col_del = st.columns(2)
                                        with col_save:
                                            if st.button("💾 強制儲存", key=f"l1_s_{uid}", type="primary", use_container_width=True):
                                                try:
                                                    c = conn.cursor()
                                                    c.execute("""UPDATE users SET login_id=%s, password=%s, role=%s, squadron=%s, title=%s, status=%s WHERE id=%s""", 
                                                                (new_login, new_pwd, new_role, new_sq, new_ti, new_st, uid))
                                                    conn.commit()
                                                    st.session_state['sys_toast'] = "✅ 更新成功！"
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"❌ 儲存失敗：{e}")
                                        
                                        with col_del:
                                            if st.button("🗑️ 刪除帳號", key=f"l1_d_{uid}", use_container_width=True):
                                                try:
                                                    c = conn.cursor()
                                                    c.execute("DELETE FROM users WHERE id=%s", (uid,))
                                                    conn.commit()
                                                    st.session_state['sys_toast'] = "🗑️ 帳號已徹底刪除！"
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"❌ 刪除失敗：{e}")
        # 🚀 升級 Tooltip
        st.subheader("📥 準則資料庫擴充與同步", help="當您更新了 GitHub 上的 `準則資料庫.csv` 後，點擊此按鈕即可將【新增加的書目或數量】匯入系統，不會影響現有的借閱紀錄。")
        if st.button("🔄 從最新 CSV 同步新增準則", type="primary", use_container_width=True):
            if CSV_FILE and os.path.exists(CSV_FILE):
                try:
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
                            if '數量' in row and pd.notna(row['數量']): qty = int(row['數量'])
                            elif '化訓準則館' in row and pd.notna(row['化訓準則館']): qty = int(row['化訓準則館'])
                                
                            for i in range(1, qty + 1):
                                serial = f"{book_title}-{i:03d}"
                                c.execute("SELECT id FROM books WHERE serial_number=%s", (serial,))
                                if not c.fetchone():
                                    c.execute("INSERT INTO books (book_name, serial_number, owner_id, status) VALUES (%s, %s, %s, %s)", (book_title, serial, '在庫', '在庫'))
                                    insert_count += 1
                                else: skip_count += 1
                    conn.commit()
                    st.success(f"✅ 同步完成！成功新增了 {insert_count} 本，略過了 {skip_count} 本。")
                    now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                    log_action("SYSTEM_L1", "CSV 擴充同步", f"管理員執行同步，新增了 {insert_count} 本準則")
                except Exception as e:
                    conn.rollback()
                    st.error(f"❌ 同步失敗，請檢查 CSV 格式。詳細原因：{e}")
            else:
                st.error("❌ 系統找不到 CSV 檔案！請確認 GitHub 上的檔案名稱。")

    # ======== 🟢 幹部 (L1) 共用業務與審核區 ========
    elif st.session_state.role == 'L1' and menu in ["👥 帳號管理", "📤 準則借閱審核", "📥 準則歸還審核", "💬 回報專區"]:
        target_sq = st.session_state.get('current_sq', '')
        sq_in_clause = st.session_state.dynamic_sq_in_clause
        
        if menu == "👥 帳號管理":
            st.subheader("👥 人事與帳號管理中心")
            acc_tabs = st.tabs(["📝 新進班隊開通", "👤 結訓日與復權救援"])
            
            with acc_tabs[0]:
                # 🚀 升級 Tooltip
                st.subheader("📝 待審核名單", help="點擊卡片下方的按鈕，即可直接完成開通或刪除。")
                reg_df = pd.read_sql_query(f"SELECT id, squadron as 中隊, title as 班隊, login_id as 帳號, discharge_date as 結訓日 FROM users WHERE status='待審核' AND squadron IN ({sq_in_clause})", conn)
                
                if not reg_df.empty:
                    for _, row in reg_df.iterrows():
                        uid = row['id']
                        with st.container(border=True):
                            st.markdown(f"🎓 **班隊全銜：** `{row['班隊']}`  \n📍 **所屬中隊：** `{row['中隊']}`  \n🆔 **申請帳號：** `{row['帳號']}`  \n📅 **結訓日期：** `{row['結訓日']}`")
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                if st.button("✅ 審核開通", key=f"app_reg_{uid}", type="primary", use_container_width=True):
                                    c = conn.cursor()
                                    c.execute("UPDATE users SET status='啟用' WHERE id=%s", (uid,))
                                    conn.commit()
                                    st.session_state['sys_toast'] = "✅ 已審核開通！"
                                    st.rerun()
                            with col2:
                                if st.button("❌ 否決(刪除)", key=f"rej_reg_{uid}", use_container_width=True):
                                    c = conn.cursor()
                                    c.execute("DELETE FROM users WHERE id=%s", (uid,))
                                    conn.commit()
                                    st.session_state['sys_toast'] = "🗑️ 已刪除此申請！"
                                    st.rerun()
                else:
                    st.success("✨ 目前無待審核的註冊申請。")

            with acc_tabs[1]:
                # 🚀 升級 Tooltip
                st.subheader("👤 結訓日與權限救援中心", help="點開班隊卡片即可修改結訓日，或重置密碼。修改結訓日後，若帳號原為凍結狀態，系統將自動為其解除凍結。")
                
                l2_users = pd.read_sql_query(f"SELECT id, squadron as 中隊, title as 班隊, login_id as 訓員帳號, status as 狀態, discharge_date as 結訓日 FROM users WHERE role='L2' AND status IN ('啟用', '結訓凍結') AND squadron IN ({sq_in_clause}) ORDER BY title", conn)
                
                if not l2_users.empty:
                    for unit_name in l2_users['班隊'].unique():
                        u_df = l2_users[l2_users['班隊'] == unit_name]
                        
                        with st.expander(f"🔽 {unit_name} (共 {len(u_df)} 個帳號)"):
                            for _, row in u_df.iterrows():
                                uid = row['id']
                                with st.container(border=True):
                                    status_emoji = '🟢' if row['狀態'] == '啟用' else '❄️'
                                    st.markdown(f"🆔 **登入帳號：** `{row['訓員帳號']}` ｜ {status_emoji} **狀態：** `{row['狀態']}`")
                                    
                                    def_date = pd.to_datetime(row['結訓日']).date() if pd.notna(row['結訓日']) else datetime.now(timezone(timedelta(hours=8))).date()
                                    new_date = st.date_input("📅 結訓日期 (點擊修改)", value=def_date, key=f"d_{uid}")
                                    
                                    col_s, col_r = st.columns(2)
                                    with col_s:
                                        if st.button("💾 儲存結訓日變更", key=f"s_{uid}", type="primary", use_container_width=True):
                                            c = conn.cursor()
                                            new_status = '啟用' if row['狀態'] == '結訓凍結' else row['狀態']
                                            c.execute("UPDATE users SET discharge_date=%s, status=%s WHERE id=%s", (new_date, new_status, uid))
                                            conn.commit()
                                            st.session_state['sys_toast'] = "✅ 結訓日已更新！(若原為凍結已自動復權)"
                                            st.rerun()
                                    with col_r:
                                        if st.button("🔑 重置密碼為 abc123", key=f"r_{uid}", use_container_width=True):
                                            c = conn.cursor()
                                            c.execute("UPDATE users SET password='abc123' WHERE id=%s", (uid,))
                                            conn.commit()
                                            st.session_state['sys_toast'] = "✅ 密碼已重置為預設！"
                                            st.rerun()
                else:
                    st.success("✨ 目前無可管理的訓員資料。")

        elif menu == "📤 準則借閱審核":
            # 🚀 升級 Tooltip
            st.subheader("📚 借閱準則審核", help="可批次或單獨審核各班隊的借閱申請。審核通過後，庫房準則將鎖定並轉為「保留待領取」狀態。")
            req_df = pd.read_sql_query(f"SELECT br.id as 單號, br.login_id as 帳號, u.title as 班隊, br.book_name as 書名, br.quantity as 申請數量 FROM borrow_requests br JOIN users u ON br.login_id = u.login_id WHERE br.status='待審核' AND u.squadron IN ({sq_in_clause}) ORDER BY u.title, br.book_name, br.id", conn)
            
            if not req_df.empty:
                owned_counts = []
                c = conn.cursor()
                for _, row in req_df.iterrows():
                    c.execute(f"SELECT COUNT(*) FROM books WHERE owner_id='{row['帳號']}' AND book_name='{row['書名']}' AND status IN ('借閱中', '保留待領取', '少領異常')")
                    owned_counts.append(c.fetchone()[0])
                req_df['已持有數'] = owned_counts
                
                unit_actions, book_actions, final_decisions = {}, {}, {}
                
                for unit_name in req_df['班隊'].unique():
                    with st.container(border=True):
                        st.markdown(f"### 【{unit_name}】")
                        unit_actions[unit_name] = st.radio(f"【{unit_name}】批次處理", ["🔽展開", "✅全審核", "❌全踢退"], horizontal=True, key=f"u_req_{unit_name}", label_visibility="collapsed")
                        unit_df = req_df[req_df['班隊'] == unit_name]
                        
                        if unit_actions[unit_name] == "✅全審核":
                            for _, row in unit_df.iterrows(): final_decisions[row['單號']] = row['申請數量']
                        elif unit_actions[unit_name] == "❌全踢退":
                            for _, row in unit_df.iterrows(): final_decisions[row['單號']] = 0
                        else:
                            st.divider()
                            for _, row in unit_df.iterrows():
                                req_id, b_name, req_qty, owned = row['單號'], row['書名'], row['申請數量'], row['已持有數']
                                st.markdown(f"**📘 {b_name}** (申請: **{req_qty}** 本 | 已持有: {owned} 本)")
                                book_actions[req_id] = st.radio(f"處理 {req_id}", ["📋自訂", "✅審核", "❌踢退"], horizontal=True, key=f"b_req_rad_{req_id}", label_visibility="collapsed")
                                
                                if book_actions[req_id] == "✅審核": final_decisions[req_id] = req_qty
                                elif book_actions[req_id] == "❌踢退": final_decisions[req_id] = 0
                                else:
                                    approve_qty = st.number_input(f"設定審核數量", min_value=0, max_value=int(req_qty), value=int(req_qty), key=f"num_{req_id}")
                                    final_decisions[req_id] = approve_qty
                
                st.markdown("---")
                if st.button("💾 送出審核結果", type="primary", use_container_width=True):
                    c = conn.cursor()
                    for _, row in req_df.iterrows():
                        req_id, req_login, req_book, req_qty, req_unit = row['單號'], row['帳號'], row['書名'], row['申請數量'], row['班隊']
                        approve_qty = final_decisions.get(req_id, 0)
                        
                        c.execute(f"SELECT id FROM books WHERE book_name='{req_book}' AND status='在庫' LIMIT {req_qty}")
                        reserved_ids = [b[0] for b in c.fetchall()]
                        approved_ids, rejected_ids = reserved_ids[:approve_qty], reserved_ids[approve_qty:]
                        
                        if approved_ids: c.execute(f"UPDATE books SET status='保留待領取', owner_id='{req_login}' WHERE id IN ({','.join(map(str, approved_ids))})")
                        if rejected_ids: c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id IN ({','.join(map(str, rejected_ids))})")
                            
                        now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                        if approve_qty > 0:
                            c.execute(f"UPDATE borrow_requests SET status='已審核(實發{approve_qty}本)' WHERE id={req_id}")
                            c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "審核借閱", f"審核 {req_book} {approve_qty} 本給 {req_unit}"))
                        else:
                            c.execute(f"UPDATE borrow_requests SET status='已踢退(砍單退件)' WHERE id={req_id}")
                            c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "踢退借閱", f"全數踢退 {req_unit} 的 {req_book} 申請"))
                    conn.commit()
                    st.session_state['sys_toast'] ="✅ 批次審核完成！"
                    st.rerun()
            else:
                st.info("目前無待審核的準則。")

            st.markdown("---")
            st.subheader("🔴 借閱異常警示 (少領退庫)")
            abnormal_df = pd.read_sql_query(f"SELECT b.id, u.title as 班隊, b.book_name as 書名, b.serial_number as 序號 FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='少領異常' AND u.squadron IN ({sq_in_clause}) ORDER BY u.title, b.book_name", conn)
            if not abnormal_df.empty:
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
                                if not abn_checks[u_key]:
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
                            elif edited_abn_dfs.get(u_key) is not None: resolved_ids.extend(edited_abn_dfs[u_key][edited_abn_dfs[u_key]["✅ 結案"] == True]["id"].tolist())
                    if resolved_ids:
                        c = conn.cursor()
                        c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id IN ({','.join(map(str, resolved_ids))})")
                        now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                        c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "異常處理", f"將少領的 {len(resolved_ids)} 本額度釋放回庫房"))
                        conn.commit()
                        st.session_state['sys_toast'] ="✅ 成功結案！已釋放 {len(resolved_ids)} 本準則。"
                        st.rerun()
            else:
                st.success("目前無異常少領通報。")

        elif menu == "📥 準則歸還審核":
            st.subheader("📥 歸還點收與遺失追查")
            ret_tabs = st.tabs(["📥 待點收清單", "🚨 遺失準則"])
            
            with ret_tabs[0]:
                return_df = pd.read_sql_query(f"SELECT b.id, u.title as 班隊, b.book_name as 書名, b.serial_number as 序號, b.owner_id, u.status as 帳號狀態 FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='歸還中' AND u.squadron IN ({sq_in_clause}) ORDER BY u.title, b.book_name", conn)
                
                if not return_df.empty:
                    # 🚀 升級 Tooltip
                    st.subheader("📥 待點收清單", help="**雙層折疊點收**：點開【班隊】👉 點開【準則名稱】👉 處理【個別序號】。\n\n**智慧踢退邏輯**：一般帳號踢退將退回「借閱中」，凍結帳號踢退將自動轉入「遺失待賠」。")
                    
                    unit_actions, book_actions, item_actions = {}, {}, {}
                    
                    for unit_name in return_df['班隊'].unique():
                        unit_df = return_df[return_df['班隊'] == unit_name]
                        u_status = unit_df.iloc[0]['帳號狀態']
                        status_emoji = "❄️(已凍結)" if u_status == '結訓凍結' else "🟢(啟用中)"
                        
                        with st.expander(f"🎓 班隊：【{unit_name}】 ｜ 狀態: {status_emoji} ｜ 待點收: {len(unit_df)} 本"):
                            unit_actions[unit_name] = st.radio(f"【{unit_name}】批次處理", ["🔽 展開個別處理", "✅ 班隊全數點收", "❌ 班隊全數踢退"], horizontal=True, key=f"u_rad_{unit_name}")
                            
                            if unit_actions[unit_name] == "🔽 展開個別處理":
                                st.divider()
                                for b_name in unit_df['書名'].unique():
                                    b_df = unit_df[unit_df['書名'] == b_name]
                                    u_b_key = f"{unit_name}_{b_name}"
                                    
                                    with st.expander(f"📘 {b_name} (共 {len(b_df)} 本)"):
                                        book_actions[u_b_key] = st.radio(f"{b_name} 處理", ["📋 逐本處理", "✅ 此書全點收", "❌ 此書全踢退"], horizontal=True, key=f"b_rad_{u_b_key}")
                                        
                                        if book_actions[u_b_key] == "📋 逐本處理":
                                            st.markdown("---")
                                            for _, row in b_df.iterrows():
                                                c1, c2 = st.columns([5, 5])
                                                c1.markdown(f"🔖 序號: `{row['序號']}`")
                                                item_actions[row['id']] = c2.radio("操作", ["✅ 點收", "❌ 踢退"], horizontal=True, key=f"ret_item_{row['id']}", label_visibility="collapsed")
                                            st.write("")
                                            
                    st.markdown("---")
                    if st.button("💾 送出點收結果", type="primary", use_container_width=True):
                        to_stock_ids, to_borrowed_ids, to_lost_ids = [], [], []
                        
                        for unit_name in return_df['班隊'].unique():
                            unit_df = return_df[return_df['班隊'] == unit_name]
                            u_status = unit_df.iloc[0]['帳號狀態']
                            
                            if unit_actions[unit_name] == "✅ 班隊全數點收":
                                to_stock_ids.extend(unit_df['id'].tolist())
                            elif unit_actions[unit_name] == "❌ 班隊全數踢退":
                                if u_status == '結訓凍結': to_lost_ids.extend(unit_df['id'].tolist())
                                else: to_borrowed_ids.extend(unit_df['id'].tolist())
                            else:
                                for b_name in unit_df['書名'].unique():
                                    b_df = unit_df[unit_df['書名'] == b_name]
                                    u_b_key = f"{unit_name}_{b_name}"
                                    
                                    if book_actions[u_b_key] == "✅ 此書全點收":
                                        to_stock_ids.extend(b_df['id'].tolist())
                                    elif book_actions[u_b_key] == "❌ 此書全踢退":
                                        if u_status == '結訓凍結': to_lost_ids.extend(b_df['id'].tolist())
                                        else: to_borrowed_ids.extend(b_df['id'].tolist())
                                    else:
                                        for _, row in b_df.iterrows():
                                            i_act = item_actions[row['id']]
                                            if i_act == "✅ 點收": to_stock_ids.append(row['id'])
                                            else:
                                                if u_status == '結訓凍結': to_lost_ids.append(row['id'])
                                                else: to_borrowed_ids.append(row['id'])
                                                
                        has_action = False
                        c = conn.cursor()
                        now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                        
                        if to_stock_ids:
                            id_list_str = ','.join(map(str, to_stock_ids))
                            c.execute(f"SELECT u.title, b.book_name, COUNT(b.id) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.id IN ({id_list_str}) GROUP BY u.title, b.book_name")
                            recv_details = c.fetchall()
                            c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id IN ({id_list_str})")
                            for u_name, b_name, qty in recv_details:
                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "歸還點收", f"收訖 {u_name} 歸還 {b_name} {qty} 本"))
                            has_action = True
                            
                        if to_borrowed_ids:
                            id_list_str = ','.join(map(str, to_borrowed_ids))
                            c.execute(f"SELECT u.title, b.book_name, COUNT(b.id) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.id IN ({id_list_str}) GROUP BY u.title, b.book_name")
                            rej_details = c.fetchall()
                            c.execute(f"UPDATE books SET status='借閱中' WHERE id IN ({id_list_str})")
                            for u_name, b_name, qty in rej_details:
                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "歸還踢退", f"未收訖 {u_name} 的 {b_name} {qty} 本，退回借閱狀態"))
                            has_action = True
                            
                        if to_lost_ids:
                            id_list_str = ','.join(map(str, to_lost_ids))
                            c.execute(f"SELECT u.title, b.book_name, COUNT(b.id) FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.id IN ({id_list_str}) GROUP BY u.title, b.book_name")
                            lost_details = c.fetchall()
                            c.execute(f"UPDATE books SET status='遺失待賠' WHERE id IN ({id_list_str})")
                            for u_name, b_name, qty in lost_details:
                                c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "歸還轉遺失", f"未收訖(凍結帳號) {u_name} 的 {b_name} {qty} 本，轉列遺失追查"))
                            has_action = True
                            
                        if has_action:
                            conn.commit()
                            st.session_state['sys_toast'] ="✅ 審核點收完成！"
                            st.rerun()
                else:
                    st.success("目前各班隊皆無待歸還點收之準則！")

            with ret_tabs[1]:
                # 🚀 升級 Tooltip
                st.subheader("🚨 遺失準則 (待賠償/待尋獲)", help="每本遺失準則皆為獨立卡片，尋獲或完成賠償時，點擊右側按鈕即可單獨結案退庫！")
                lost_df = pd.read_sql_query(f"SELECT b.id, u.title as 班隊, b.book_name as 書名, b.serial_number as 序號 FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.status='遺失待賠' AND u.squadron IN ({sq_in_clause}) ORDER BY u.title, b.book_name", conn)
                
                if not lost_df.empty:
                    for _, row in lost_df.iterrows():
                        l_id = row['id']
                        with st.container(border=True):
                            col1, col2 = st.columns([7, 3])
                            with col1:
                                st.markdown(f"🎓 **班隊：** `{row['班隊']}`  \n📘 **書名：** `{row['書名']}`  \n🔖 **序號：** `{row['序號']}`")
                            with col2:
                                st.write("")
                                if st.button("✅ 尋獲/結案", key=f"lost_res_{l_id}", type="primary", use_container_width=True):
                                    c = conn.cursor()
                                    now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                    c.execute(f"UPDATE books SET status='在庫', owner_id='在庫' WHERE id={l_id}")
                                    c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", (now_time, st.session_state.login_id, "遺失結案", f"尋獲或完成賠償，退庫: {row['書名']} ({row['序號']})"))
                                    conn.commit()
                                    st.session_state['sys_toast'] ="✅ 結案成功！已退回庫房。"
                                    st.rerun()
                else:
                    st.success("✨ 準則妥善率 100%！目前中隊無任何遺失待賠之準則！")

        elif menu in ["💬 回報專區", "回報專區"]:
            st.subheader("💬 Line 報表自動生成器")
            line_tabs = st.tabs(["🚚 借還動態彙總", "📦 準則總清點(含遺失)"])
            
            with line_tabs[0]:
                # 🚀 升級 Tooltip
                st.subheader("🚚 借還動態彙總", help="產出今日動態物流清單。點擊黑框右上角「📋」複製。")
                st.markdown(f"📍 **目前產出中隊：** `{target_sq}`")
                
                dyn_mode = st.radio("🎯 回報範圍", ["整個中隊彙總", "只回報特定班隊"], horizontal=True, key="dyn_mode")
                dyn_selected_units = []
                if dyn_mode == "只回報特定班隊":
                    c = conn.cursor()
                    c.execute(f"SELECT DISTINCT title FROM users WHERE squadron IN ({sq_in_clause}) AND role='L2'")
                    avail_units = [row[0] for row in c.fetchall()]
                    dyn_selected_units = st.multiselect("📌 請加入要回報的班隊 (可多選)：", avail_units, key="dyn_units")
                    
                if st.button("🚀 生成借還動態報表", type="primary"):
                    unit_filter = f" AND u.title IN ('{chr(39).join(dyn_selected_units)}')" if dyn_mode == "只回報特定班隊" and dyn_selected_units else ""
                    
                    req_df = pd.read_sql_query(f"SELECT u.title as unit, br.book_name, SUM(br.quantity) as qty FROM borrow_requests br JOIN users u ON br.login_id = u.login_id WHERE u.squadron IN ({sq_in_clause}) AND br.status='待審核'{unit_filter} GROUP BY u.title, br.book_name", conn)
                    res_df = pd.read_sql_query(f"SELECT u.title as unit, b.book_name, COUNT(b.id) as qty FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.squadron IN ({sq_in_clause}) AND b.status='保留待領取'{unit_filter} GROUP BY u.title, b.book_name", conn)
                    ret_df = pd.read_sql_query(f"SELECT u.title as unit, b.book_name, COUNT(b.id) as qty FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.squadron IN ({sq_in_clause}) AND b.status='歸還中'{unit_filter} GROUP BY u.title, b.book_name ORDER BY b.book_name", conn)
                    
                    now = datetime.now(timezone(timedelta(hours=8)))
                    tw_wd = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
                    msg = f"報告，{target_sq}借還書清單\n時間：{now.month}/{now.day}（{tw_wd}）\n\n"
                    
                    all_units = set()
                    if not req_df.empty: all_units.update(req_df['unit'].tolist())
                    if not res_df.empty: all_units.update(res_df['unit'].tolist())
                    if not ret_df.empty: all_units.update(ret_df['unit'].tolist())
                    
                    if not all_units: msg += "今日無待辦物流。\n"
                    else:
                        for unit in sorted(list(all_units)):
                            msg += f"==== 【{unit}】 ====\n【申請借閱】：\n"
                            borrow_items = {}
                            if not req_df.empty:
                                for _, r in req_df[req_df['unit'] == unit].iterrows(): borrow_items[r['book_name']] = borrow_items.get(r['book_name'], 0) + int(r['qty'])
                            if not res_df.empty:
                                for _, r in res_df[res_df['unit'] == unit].iterrows(): borrow_items[r['book_name']] = borrow_items.get(r['book_name'], 0) + int(r['qty'])
                                    
                            if borrow_items:
                                for b_name in sorted(borrow_items.keys()): msg += f"{b_name} * {borrow_items[b_name]}\n"
                            else: msg += "無\n"
                            
                            msg += "\n【申請歸還】：\n"
                            if not ret_df.empty and not ret_df[ret_df['unit'] == unit].empty:
                                for _, r in ret_df[ret_df['unit'] == unit].iterrows(): msg += f"{r['book_name']} * {int(r['qty'])}\n"
                            else: msg += "無\n"
                            msg += "\n"
                    st.code(msg.strip(), language="text")

            with line_tabs[1]:
                # 🚀 升級 Tooltip
                st.subheader("📦 準則總清點(含遺失)", help="產出中隊外散準則之總清單。點擊黑框右上角「📋」複製。")
                st.markdown(f"📍 **目前產出中隊：** `{target_sq}`")
                    
                inv_mode = st.radio("🎯 回報範圍", ["整個中隊彙總", "只回報特定班隊"], horizontal=True, key="inv_mode")
                inv_selected_units = []
                if inv_mode == "只回報特定班隊":
                    c = conn.cursor()
                    c.execute(f"SELECT DISTINCT title FROM users WHERE squadron IN ({sq_in_clause}) AND role='L2'")
                    avail_units = [row[0] for row in c.fetchall()]
                    inv_selected_units = st.multiselect("📌 請加入要回報的班隊 (可多選)：", avail_units, key="inv_units")
                    
                if st.button("🚀 生成準則總清點報表", type="primary"):
                    unit_filter = f" AND u.title IN ('{chr(39).join(inv_selected_units)}')" if inv_mode == "只回報特定班隊" and inv_selected_units else ""
                        
                    inv_df = pd.read_sql_query(f"SELECT u.title as unit, b.book_name, b.status, COUNT(b.id) as qty FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.squadron IN ({sq_in_clause}) AND b.status IN ('借閱中', '歸還中', '遺失待賠', '少領異常') {unit_filter} GROUP BY u.title, b.book_name, b.status", conn)
                    
                    now = datetime.now(timezone(timedelta(hours=8)))
                    tw_wd = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
                    inv_msg = f"報告，{target_sq}準則清點總表\n時間：{now.month}/{now.day}（{tw_wd}）\n\n"
                    
                    if inv_df.empty: inv_msg += "目前無外散之準則。\n"
                    else:
                        inv_df = apply_shadow_sort(inv_df, has_unit=True)
                        for unit in inv_df['unit'].unique():
                            inv_msg += f"==== 【{unit}】 ====\n"
                            for _, r in inv_df[inv_df['unit'] == unit].iterrows():
                                inv_msg += f"📘 {r['book_name']} * {int(r['qty'])} ({r['status']})\n"
                            inv_msg += "\n"
                    
                    st.code(inv_msg.strip(), language="text")

    # ======== 🟢 跨階級共用功能 ========
    elif menu in ["綜合查詢", "🔍 綜合查詢"]:
        # 🚀 升級 Tooltip
        st.header("🔍 綜合查詢", help="可透過「查書名」觀看各班隊持有該準則的數量；或透過「查序號」精準追蹤單本準則的目前流向與狀態。")
        search_type = st.radio("查詢模式", ["查書名", "查序號"], horizontal=True)

        keyword = st.text_input("請輸入關鍵字")
        if st.button("搜尋") and keyword:
            if "書名" in search_type:
                query = "SELECT u.squadron as 中隊, u.title as 班隊, COUNT(b.id) as 數量 FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.book_name LIKE %s GROUP BY u.squadron, u.title"
                res = pd.read_sql_query(query, conn, params=(f"%{keyword}%",))
                st.dataframe(res, use_container_width=True)
            else:
                query = "SELECT u.squadron as 中隊, u.title as 班隊, b.book_name as 書名, b.status as 狀態 FROM books b JOIN users u ON b.owner_id = u.login_id WHERE b.serial_number = %s"
                res = pd.read_sql_query(query, conn, params=(keyword,))
                st.dataframe(res, use_container_width=True)

    elif menu == "📊 準則現況":
        current_view_sq = st.session_state.get('current_sq', st.session_state.squadron)
        # 🚀 升級 Tooltip
        st.header(f"📊 【{current_view_sq}】所屬班隊準則持有現況", help="點擊下方各班隊名稱，即可展開查看該班隊目前持有的所有準則與詳細序號。")
        
        if st.session_state.role == 'L1':
            sq_in_clause = st.session_state.dynamic_sq_in_clause
            unit_query = f"SELECT DISTINCT u.title as unit FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.squadron IN ({sq_in_clause}) AND b.status IN ('借閱中', '保留待領取', '少領異常', '歸還中')"
        else:
            unit_query = f"SELECT DISTINCT u.title as unit FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.login_id = '{st.session_state.login_id}' AND b.status IN ('借閱中', '保留待領取', '少領異常', '歸還中')"
            
        units_df = pd.read_sql_query(unit_query, conn)
        if units_df.empty:
            st.success("✨ 目前無任何班隊持有準則 (皆已歸還或無借閱)。")
        else:
            for unit_name in units_df['unit']:
                with st.expander(f"🏢 班隊：【{unit_name}】"):
                    books_df = pd.read_sql_query(f"SELECT b.book_name, b.status, b.serial_number FROM books b JOIN users u ON b.owner_id = u.login_id WHERE u.title='{unit_name}' AND b.status IN ('借閱中', '保留待領取', '少領異常', '歸還中')", conn)
                    
                    if not books_df.empty:
                        books_df = apply_shadow_sort(books_df)
                        grouped = books_df.groupby(['book_name', 'status'], sort=False)
                        for (b_name, st_val), b_rows in grouped:
                            qty = len(b_rows)
                            st_display = "已審核" if st_val == '保留待領取' else st_val
                            icon = '🔴' if st_val in ['少領異常', '歸還中'] else '🟡' if st_val == '保留待領取' else '🟢'
                            
                            st.markdown(f"**{icon} {b_name}** * {qty} ({st_display})")
                            
                            display_serials = []
                            for _, s_row in b_rows.iterrows():
                                if pd.notna(s_row['serial_number']):
                                    display_serials.append(str(s_row['serial_number']).strip())
                                    
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
        # 🚀 升級 Tooltip
        st.header("🗂️ 系統操作紀錄", help="追蹤全系統的借還、審核、設定異動與異常處理等歷史軌跡。支援關鍵字模糊搜尋 (如輸入：姓名、班隊名稱、或特定動作)。")
        search_keyword = st.text_input("🔍 搜尋紀錄 (可輸入班隊、動作、準則名稱等)", placeholder="例如：借閱、M2A2、第一中隊...")
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
        if search_keyword:
            safe_kw = search_keyword.replace("'", "''")
            log_query += f" WHERE a.details LIKE '%%{safe_kw}%%' OR a.action LIKE '%%{safe_kw}%%' OR u.title LIKE '%%{safe_kw}%%'"
            
        log_query += " ORDER BY a.id DESC LIMIT 300"
        logs_df = pd.read_sql_query(log_query, conn)
        
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

finally:
    release_connection(conn)
