# database.py
import psycopg2
from psycopg2 import pool, IntegrityError
import psycopg2.extras
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import logging
import streamlit as st
from exceptions import DatabaseConnectionError, DataConflictError

# 設定 Logging，讓伺服器終端機能留下紀錄
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 建立連線池
@st.cache_resource
def init_connection_pool():
    try:
        return psycopg2.pool.ThreadedConnectionPool(1, 10, st.secrets["DATABASE_URL"], connect_timeout=10)
    except Exception as e:
        logger.error(f"連線池初始化失敗: {e}")
        raise DatabaseConnectionError(f"資料庫連線池初始化失敗: {e}")

db_pool = init_connection_pool()

def get_db_connection():
    try:
        conn = db_pool.getconn()
    except psycopg2.pool.PoolError:
        logger.warning("連線池滿載，等待中...")
        raise DatabaseConnectionError("系統滿載中，請稍後再試。")
    
    try:
        with conn.cursor() as c:
            c.execute("SELECT 1")
    except Exception:
        db_pool.putconn(conn, close=True)
        try:
            conn = db_pool.getconn()
        except psycopg2.pool.PoolError:
            raise DatabaseConnectionError("資料庫連線異常，請稍後再試。")
    return conn

def release_connection(conn):
    try:
        if conn:
            conn.rollback() # 洗掉殘留交易，防死鎖
            db_pool.putconn(conn)
    except Exception as e:
        logger.error(f"歸還連線時發生異常: {e}")
        try:
            conn.close()
        except Exception:
            pass

@contextmanager
def get_auto_conn():
    """單純讀取資料用的管理器"""
    conn = get_db_connection()
    try:
        yield conn
    finally:
        release_connection(conn)

def fetch_all_dict(query, params=None):
    """極速資料獲取引擎：直接返回 List[dict]"""
    with get_auto_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
            c.execute(query, params)
            return c.fetchall()

@contextmanager
def db_transaction():
    """
    淨化版的交易管理器：
    1. 移除所有 st.error / st.toast
    2. 只負責 Commit 或 Rollback
    3. 遇到錯誤直接 Raise 給上層 (UI層) 處理
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            yield c
        conn.commit()
    except IntegrityError as e:
        conn.rollback()
        logger.warning(f"資料衝突: {e}")
        raise DataConflictError("資料衝突或已存在於系統中！")
    except Exception as e:
        conn.rollback()
        logger.error(f"資料庫操作失敗: {e}")
        raise e
    finally:
        release_connection(conn)

def write_sys_log(c, action, details, user_id):
    """純淨版的日誌寫入 (不再依賴 st.session_state)"""
    now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO action_logs (timestamp, user_id, action, details) VALUES (%s, %s, %s, %s)", 
              (now_time, user_id, str(action), str(details)))
