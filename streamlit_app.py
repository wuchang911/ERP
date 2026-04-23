import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 0. 權限與登入驗證 ---
def check_password():
    if "user_role" not in st.session_state:
        st.title("🔒 企業管理系統登入")
        pwd = st.text_input("請輸入密碼", type="password")
        if st.button("登入"):
            if pwd == "8888":  # 管理員密碼
                st.session_state["user_role"] = "admin"
                st.rerun()
            elif pwd == "1111":  # 員工密碼
                st.session_state["user_role"] = "staff"
                st.rerun()
            else:
                st.error("❌ 密碼錯誤")
        return False
    return True

if not check_password():
    st.stop()

role = st.session_state["user_role"]

# --- 1. 資料庫初始化 ---
conn = sqlite3.connect('business_pro_v5.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS products 
             (name TEXT UNIQUE, cost REAL, price REAL, big_unit TEXT, small_unit TEXT, 
              ratio INTEGER, alert_level INTEGER, image_data TEXT, description TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS logs 
             (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, price_at_time REAL, date TEXT)''')
conn.commit()

# --- 2. 工具函數 ---
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
    total_small_qty, total_profit, small_unit_cost = 0, 0, cost / ratio
    for t, q, u, p_at_time in logs:
        tx_small_qty = q * ratio if u == big_u else q
        if t == '進貨': total_small_qty += tx_small_qty
        else:
            total_small_qty -= tx_small_qty
            total_profit += (q * p_at_time) - (tx_small_qty * small_unit_cost)
    display_stock = f"{total_small_qty // ratio} {big_u} {total_small_qty % ratio} {small_u}"
    return total_small_qty, total_profit, display_stock, ratio

# --- 3. 側邊欄 ---
st.sidebar.title(f"🏢 企業管理 ({'管理員' if role=='admin' else '員工'})")

# --- 只有管理員看得到鎖定開關 ---
system_lock = False
if role == "admin":
    with st.sidebar.expander("🔒 系統權限控制"):
        system_lock = st.toggle("開啟盤點鎖定", value=False)
        if system_lock: st.warning("⚠️ 已封鎖登記功能")
        
    # --- 只有管理員看得到資料清理 ---
    with st.sidebar.expander("🛠️ 資料管理"):
        if st.checkbox("確認清空所有交易紀錄"):
            if st.button("🔥 立即清空"):
                c.execute("DELETE FROM logs"); conn.commit(); st.rerun()
else:
    # 員工登入時，若管理員已開啟鎖定，這裡要自動獲取狀態 (此簡易版使用 Session 模擬)
    if "admin_lock" not in st.session_state: st.session_state["admin_lock"] = False
    system_lock = st.session_state.get("admin_lock", False)

st.sidebar.divider()
if st.sidebar.button("登出系統"):
    del st.session_state["user_role"]; st.rerun()

# 選單權限：員工不能進入「商品設定」
menu_options = ["📊 即時庫存與報表", "📝 進出貨登記"]
if role == "admin":
    menu_options.append("🍎 商品設定")

choice = st.sidebar.selectbox("切換功能", menu_options)

# --- 功能 1：庫存與報表 ---
if choice == "📊 即時庫存與報表":
    st.subheader("📦 精確庫存監控")
    c.execute("SELECT name, image_data, alert_level, description FROM products")
    prods = c.fetchall()
    all_profit = 0
    cols = st.columns(2 if st.sidebar.checkbox("手機模式", True) else 4)
    for idx, (name, img, alert, desc) in enumerate(prods):
        small_qty, profit, display_stock, ratio = get_stock_and_profit(name)
        all_profit += profit
        with cols[idx % len(cols)]:
            if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
            color = "#FF4B4B" if small_qty <= alert else "#00A000"
            st.markdown(f"**{name}**")
            st.markdown(f"庫存：<span style='color:{color};font-weight:bold;'>{display_stock}</span>", unsafe_allow_html=True)
            if desc:
                with st.expander("📝 敘述"): st.write(desc)
    
    # 只有管理員看得到毛利總額
    if role == "admin":
        st.sidebar.metric("總累計毛利", f"${all_profit:,.0f} TW$")

# --- 功能 2：進出貨登記 ---
elif choice == "📝 進出貨登記":
    st.subheader("📝 進銷貨登記")
    if system_lock:
        st.error("🛑 系統盤點鎖定中，目前無法登記。請聯繫管理員。")
    else:
        c.execute("SELECT name, big_unit, small_unit FROM products")
        items = c.fetchall()
        if not items: st.warning("請先設定商品")
        else:
            t_data = st.selectbox("品項", options=items)
            with st.form("trade"):
                t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
                cur_s, _, cur_d, _ = get_stock_and_profit(t_data)
                st.info(f"💡 目前庫存：{cur_d}")
                q, u = st.columns(2)
                with q: t_qty = st.number_input("數量", min_value=1)
                with u: t_unit = st.selectbox("單位", [t_data, t_data])
                t_price = st.number_input("單價", min_value=0.0, value=100.0)
                if st.form_submit_button("提交登記"):
                    c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date) VALUES (?,?,?,?,?,?)", 
                              (t_data, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y/%m/%d")))
                    conn.commit(); st.success("✅ 登記成功"); st.balloons()

# --- 功能 3：商品設定 (僅限管理員) ---
elif choice == "🍎 商品設定" and role == "admin":
    st.subheader("🍎 商品資料維護")
    # ... (此處保留原本的商品設定程式碼) ...
    st.write("管理員您好，您可以在此新增或修改商品參數。")
