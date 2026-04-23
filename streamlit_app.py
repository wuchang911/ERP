import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 1. 資料庫與權限初始化 ---
conn = sqlite3.connect('business_pro_v6.db', check_same_thread=False)
c = conn.cursor()

# 自動補齊資料庫欄位，避免舊版升級報錯
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
        user_data = c.fetchone()
        if user_data:
            st.session_state["user"] = user_data[0]
            st.session_state["role"] = user_data[1]
            st.rerun()
        else:
            st.error("❌ 帳號或密碼錯誤")
    st.stop()

current_user = st.session_state["user"]
current_role = st.session_state["role"]

# --- 3. 工具函數 ---
def image_to_base64(image_file):
    if image_file:
        try:
            img = Image.open(image_file); img.thumbnail((400, 400))
            buf = io.BytesIO(); img.save(buf, format="JPEG")
            return base64.b64encode(buf.getvalue()).decode()
        except: return None
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
if current_role == "admin":
    with st.sidebar.expander("👤 帳號管理"):
        new_u = st.text_input("新增帳號")
        new_p = st.text_input("設定密碼", type="password")
        if st.button("更新/建立帳號"):
            c.execute("INSERT OR REPLACE INTO users VALUES (?,?,'staff')", (new_u, new_p))
            conn.commit(); st.success(f"{new_u} 已更新")
    system_lock = st.sidebar.toggle("🔒 盤點鎖定", value=False)
else:
    system_lock = False

if st.sidebar.button("登出系統"):
    del st.session_state["user"]; del st.session_state["role"]; st.rerun()

# --- 5. 主功能選單 ---
menu = ["📊 庫存監控", "📝 進出貨登記"]
if current_role == "admin": menu.append("🍎 商品設定")
choice = st.sidebar.selectbox("切換功能", menu)

# --- 功能：進出貨登記 (修復 Bug) ---
if choice == "📝 進出貨登記":
    st.subheader("📝 進銷貨手動登記")
    if system_lock:
        st.error("🛑 系統盤點鎖定中，暫停登記。")
    else:
        c.execute("SELECT name, big_unit, small_unit FROM products")
        items_list = c.fetchall()
        if not items_list:
            st.warning("⚠️ 請管理員先建立商品。")
        else:
            # 修正 1：確保名單是字串列表
            names = [i[0] for i in items_list]
            selected_name = st.selectbox("選擇商品", names)
            
            # 找到該商品的單位
            p_info = [i for i in items_list if i[0] == selected_name][0]
            units = [p_info[1], p_info[2]] # 大單位, 小單位
            
            with st.form("trade_form"):
                t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
                s_qty, _, d_stock, _ = get_stock_and_profit(selected_name)
                st.info(f"💡 目前庫存：{d_stock}")
                
                col1, col2 = st.columns(2)
                with col1: t_qty = st.number_input("數量", min_value=1, step=1)
                with col2: t_unit = st.selectbox("單位", options=units) # 修正 2：確保 options 格式正確
                
                t_price = st.number_input("單價 (TW$)", min_value=0.0)
                t_date = st.date_input("日期", datetime.now())
                
                # 修正 3：必須有 submit 按钮
                submit_button = st.form_submit_button("確認提交紀錄")
                
                if submit_button:
                    c.execute("SELECT ratio FROM products WHERE name=?", (selected_name,))
                    ratio = c.fetchone()[0]
                    tx_small_qty = t_qty * ratio if t_unit == p_info[1] else t_qty
                    
                    if t_type == "出貨" and tx_small_qty > s_qty:
                        st.error(f"❌ 庫存不足！")
                    else:
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)", 
                                  (selected_name, t_type, t_qty, t_unit, t_price, now_str, current_user))
                        conn.commit(); st.success("✅ 登記成功！"); st.balloons()

# --- 其餘功能模組保持原本邏輯 ---
elif choice == "📊 庫存監控":
    st.subheader("📦 即時庫存報表")
    c.execute("SELECT name, image_data, description, created_by FROM products")
    prods = c.fetchall()
    for n, img, desc, creator in prods:
        s_qty, profit, d_stock, _ = get_stock_and_profit(n)
        st.markdown(f"### {n}")
        if img: st.image(f"data:image/jpeg;base64,{img}", width=200)
        st.write(f"庫存：{d_stock}")
        if current_role == "admin": st.write(f"累計利潤：${profit:,.0f}")
        st.divider()

elif choice == "🍎 商品設定":
    st.subheader("🍎 商品維護與定價")
    with st.form("new_p"):
        n = st.text_input("商品名")
        b = st.text_input("大單位", value="箱")
        s = st.text_input("小單位", value="顆")
        r = st.number_input("換算率", min_value=1)
        c_p = st.number_input("進貨成本")
        s_p = st.number_input("單顆售價")
        desc = st.text_area("敘述")
        img = st.camera_input("拍照")
        if st.form_submit_button("儲存"):
            img_b64 = image_to_base64(img)
            now = datetime.now().strftime("%Y-%m-%d")
            c.execute("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (n, c_p, s_p, b, s, r, 5, img_b64, desc, current_user, now))
            conn.commit(); st.success("商品已更新！")
