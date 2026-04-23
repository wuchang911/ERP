import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime
from streamlit_camera_qr import barcode_scanner # 換成這個套件

# --- 1. 資料庫初始化 ---
conn = sqlite3.connect('business_pro_v6.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT UNIQUE, password TEXT, role TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS products 
             (name TEXT UNIQUE, cost REAL, price REAL, big_unit TEXT, small_unit TEXT, 
              ratio INTEGER, alert_level INTEGER, image_data TEXT, description TEXT, created_by TEXT, created_at TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS logs 
             (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, 
              price_at_time REAL, date TEXT, operator TEXT)''')
c.execute("INSERT OR IGNORE INTO users VALUES ('admin', '8888', 'admin')")
conn.commit()

# --- 2. 登入系統 ---
if "user" not in st.session_state:
    st.title("🔒 企業進銷存系統登入")
    u = st.text_input("帳號")
    p = st.text_input("密碼", type="password")
    if st.button("確認登入"):
        c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
        res = c.fetchone()
        if res:
            st.session_state["user"], st.session_state["role"] = res[0], res[1]
            st.rerun()
        else: st.error("❌ 帳密錯誤")
    st.stop()

current_user = st.session_state["user"]
current_role = st.session_state["role"]

# --- 3. 工具函數 ---
def image_to_base64(image_file):
    if image_file:
        img = Image.open(image_file); img.thumbnail((400, 400))
        buf = io.BytesIO(); img.save(buf, format="JPEG")
        return base64.b64encode(buf.getvalue()).decode()
    return None

def get_stock_and_profit(name):
    c.execute("SELECT big_unit, small_unit, ratio, cost, price FROM products WHERE name=?", (name,))
    p = c.fetchone()
    if not p: return 0, 0, "無資料", 1
    big_u, small_u, ratio, cost, price = p
    c.execute("SELECT type, qty, unit, price_at_time FROM logs WHERE name=?", (name,))
    logs = c.fetchall()
    total_small_qty, total_profit, small_unit_cost = 0, 0, (cost / ratio if ratio > 0 else 0)
    for t, q, u, p_at_time in logs:
        tx_small_qty = q * ratio if u == big_u else q
        if t == '進貨': total_small_qty += tx_small_qty
        else:
            total_small_qty -= tx_small_qty
            total_profit += (q * p_at_time) - (tx_small_qty * small_unit_cost)
    display_stock = f"{total_small_qty // ratio} {big_u} {total_small_qty % ratio} {small_u}"
    return total_small_qty, total_profit, display_stock, ratio

# --- 4. 側邊欄 ---
st.sidebar.title(f"👤 {current_user}")
system_lock = st.sidebar.toggle("🔒 盤點鎖定", value=False) if current_role == "admin" else False
if st.sidebar.button("登出系統"):
    del st.session_state["user"]; st.rerun()

menu = ["📊 庫存報表", "📝 進出貨登記", "🍎 商品設定"]
if current_role != "admin": menu.remove("🍎 商品設定")
choice = st.sidebar.selectbox("切換功能", menu)

# --- 功能：進出貨登記 (支援 QR/條碼掃描) ---
if choice == "📝 進出貨登記":
    st.subheader("📝 登記進銷貨")
    if system_lock: st.error("🛑 系統鎖定中")
    else:
        st.write("📷 掃描商品條碼")
        # 啟動掃描器
        scanned_code = barcode_scanner()
        if scanned_code: st.success(f"已掃描到：{scanned_code}")
        
        c.execute("SELECT name FROM products")
        p_names = [p[0] for p in c.fetchall()]
        
        idx = 0
        if scanned_code in p_names: 
            idx = p_names.index(scanned_code)
        
        target_p = st.selectbox("品項選擇", options=p_names, index=idx)
        
        if target_p:
            c.execute("SELECT big_unit, small_unit FROM products WHERE name=?", (target_p,))
            u_info = c.fetchone()
            s_qty, _, d_stock, _ = get_stock_and_profit(target_p)
            st.info(f"💡 目前庫存：{d_stock}")
            
            with st.form("trade_form"):
                t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
                col1, col2 = st.columns(2)
                with col1: t_qty = st.number_input("數量", min_value=1, step=1)
                with col2: t_unit = st.selectbox("單位", options=list(u_info))
                t_price = st.number_input("單價 (TW$)", min_value=0.0)
                if st.form_submit_button("確認提交"):
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)", 
                              (target_p, t_type, t_qty, t_unit, t_price, now, current_user))
                    conn.commit(); st.success("✅ 登記完成"); st.balloons()

# --- 功能：商品設定 (支援掃描建檔) ---
elif choice == "🍎 商品設定":
    st.subheader("🍎 商品維護")
    st.write("📷 掃描條碼建檔")
    new_code = barcode_scanner()
    if new_code: st.info(f"掃描結果：{new_code}")

    with st.form("new_p_form"):
        n = st.text_input("商品名稱 (條碼編號)", value=new_code if new_code else "")
        b, s, r = st.text_input("大單位", value="箱"), st.text_input("小單位", value="顆"), st.number_input("換算率", min_value=1)
        cost, price = st.number_input("整箱成本"), st.number_input("單顆售價")
        desc = st.text_area("描述")
        cam = st.camera_input("拍照")
        if st.form_submit_button("儲存商品"):
            img_b = image_to_base64(cam)
            now = datetime.now().strftime("%Y-%m-%d")
            c.execute("INSERT OR REPLACE INTO products (name, cost, price, big_unit, small_unit, ratio, alert_level, image_data, description, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (n, cost, price, b, s, r, 5, img_b, desc, current_user, now))
            conn.commit(); st.success("已更新"); st.rerun()

elif choice == "📊 庫存報表":
    st.subheader("📦 即時報表")
    c.execute("SELECT name, image_data, description FROM products")
    for n, img, desc in c.fetchall():
        _, _, d_stock, _ = get_stock_and_profit(n)
        st.write(f"### {n}")
        if img: st.image(f"data:image/jpeg;base64,{img}", width=150)
        st.write(f"即時庫存：{d_stock}")
        st.divider()
