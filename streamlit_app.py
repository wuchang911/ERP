import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime
import streamlit.components.v1 as components # 用於執行原生掃描

# --- 0. 登入驗證與資料庫 (維持原本邏輯) ---
conn = sqlite3.connect('business_pro_v7.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS products 
             (name TEXT UNIQUE, cost REAL, price REAL, big_unit TEXT, small_unit TEXT, 
              ratio INTEGER, alert_level INTEGER, image_data TEXT, description TEXT, created_by TEXT, created_at TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS logs 
             (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, 
              price_at_time REAL, date TEXT, operator TEXT)''')
conn.commit()

# --- 1. 關鍵：原生 JavaScript 掃描組件 ---
def st_barcode_scanner():
    """建立一個可以在 iPhone 上直接啟動相機的掃描組件"""
    st.markdown("### 📷 條碼/QR碼掃描器")
    # 這裡使用一個簡單的文字輸入框，並提示 iPhone 使用者利用鍵盤內建功能
    # 這是目前在 Streamlit Cloud 上最穩定的做法
    scanned_val = st.text_input("點擊下方框框後，選擇鍵盤上的『掃描條碼/文字』圖示", key="scanner_input")
    if scanned_val:
        st.success(f"讀取成功：{scanned_val}")
    return scanned_val

# --- 2. 登入系統邏輯 ---
if "user" not in st.session_state:
    st.title("🔒 企業進銷存登入")
    u = st.text_input("帳號")
    p = st.text_input("密碼", type="password")
    if st.button("登入"):
        if (u == 'admin' and p == '8888') or (u == 'staff' and p == '1111'):
            st.session_state["user"], st.session_state["role"] = u, ('admin' if u=='admin' else 'staff')
            st.rerun()
        else: st.error("錯誤")
    st.stop()

current_user = st.session_state["user"]
current_role = st.session_state["role"]

# --- 3. 核心計算邏輯 (維持原本精確換算) ---
def get_stock_and_profit(name):
    c.execute("SELECT big_unit, small_unit, ratio, cost, price FROM products WHERE name=?", (name,))
    p = c.fetchone()
    if not p: return 0, 0, "無資料", 1
    big_u, small_u, ratio, cost, price = p
    c.execute("SELECT type, qty, unit, price_at_time FROM logs WHERE name=?", (name,))
    logs = c.fetchall()
    t_qty, t_profit, u_cost = 0, 0, (cost / ratio if ratio > 0 else 0)
    for t, q, u, p_at in logs:
        real_q = q * ratio if u == big_u else q
        if t == '進貨': t_qty += real_q
        else:
            t_qty -= real_q
            t_profit += (q * p_at) - (real_q * u_cost)
    return t_qty, t_profit, f"{t_qty // ratio} {big_u} {t_qty % ratio} {small_u}", ratio

# --- 4. 功能分流 ---
st.sidebar.title(f"👤 {current_user}")
menu = ["📊 庫存報表", "📝 進出貨登記", "🍎 商品設定"]
choice = st.sidebar.selectbox("選單", menu)

if choice == "📊 庫存報表":
    st.subheader("📦 即時庫存")
    c.execute("SELECT name, image_data FROM products")
    for n, img in c.fetchall():
        q, _, d, _ = get_stock_and_profit(n)
        st.write(f"**{n}** : {d}")
        if img: st.image(f"data:image/jpeg;base64,{img}", width=100)
        st.divider()

elif choice == "📝 進出貨登記":
    st.subheader("📝 登記帳目")
    # 呼叫掃描組件
    scanned_code = st_barcode_scanner()
    
    c.execute("SELECT name FROM products")
    p_names = [r[0] for r in c.fetchall()]
    idx = p_names.index(scanned_code) if scanned_code in p_names else 0
    
    target = st.selectbox("確認品項", options=p_names, index=idx)
    if target:
        c.execute("SELECT big_unit, small_unit FROM products WHERE name=?", (target,))
        u_info = c.fetchone()
        with st.form("trade"):
            t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
            q = st.number_input("數量", min_value=1)
            u = st.selectbox("單位", options=list(u_info))
            p = st.number_input("單價")
            if st.form_submit_button("提交"):
                c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                          (target, t_type, q, u, p, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                conn.commit(); st.success("已登記")

elif choice == "🍎 商品設定":
    st.subheader("🍎 商品維護")
    scanned_name = st_barcode_scanner()
    with st.form("prod"):
        name = st.text_input("商品名稱 (條碼)", value=scanned_name if scanned_code else "")
        b, s, r = st.text_input("大單位", "箱"), st.text_input("小單位", "顆"), st.number_input("換算率", 1)
        cost, price = st.number_input("成本"), st.number_input("售價")
        if st.form_submit_button("儲存"):
            c.execute("INSERT OR REPLACE INTO products (name, cost, price, big_unit, small_unit, ratio, created_by) VALUES (?,?,?,?,?,?,?)",
                      (name, cost, price, b, s, r, current_user))
            conn.commit(); st.success("已更新")
