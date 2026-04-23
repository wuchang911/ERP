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

# 建立表格：使用者、商品(含建檔人)、日誌(含操作人)
c.execute('''CREATE TABLE IF NOT EXISTS users 
             (username TEXT UNIQUE, password TEXT, role TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS products 
             (name TEXT UNIQUE, cost REAL, price REAL, big_unit TEXT, small_unit TEXT, 
              ratio INTEGER, alert_level INTEGER, image_data TEXT, description TEXT, created_by TEXT, created_at TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS logs 
             (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, 
              price_at_time REAL, date TEXT, operator TEXT)''')

# 預設管理員帳號：admin / 8888 (如果不存在則建立)
c.execute("INSERT OR IGNORE INTO users VALUES ('admin', '8888', 'admin')")
conn.commit()

# --- 2. 登入系統 ---
def login():
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
        return False
    return True

if not login():
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
    total_small_qty, total_profit, small_unit_cost = 0, 0, cost / ratio
    for t, q, u, p_at_time in logs:
        tx_small_qty = q * ratio if u == big_u else q
        if t == '進貨': total_small_qty += tx_small_qty
        else:
            total_small_qty -= tx_small_qty
            total_profit += (q * p_at_time) - (tx_small_qty * small_unit_cost)
    display_stock = f"{total_small_qty // ratio} {big_u} {total_small_qty % ratio} {small_u}"
    return total_small_qty, total_profit, display_stock, ratio

# --- 4. 側邊欄與管理員功能 ---
st.sidebar.title(f"👤 {current_user} ({'管理員' if current_role=='admin' else '員工'})")

if current_role == "admin":
    with st.sidebar.expander("👤 帳號管理面板"):
        new_u = st.text_input("新增帳號")
        new_p = st.text_input("設定密碼", type="password")
        new_r = st.selectbox("權限等級", ["staff", "admin"])
        if st.button("建立/更新帳號"):
            c.execute("INSERT OR REPLACE INTO users VALUES (?,?,?)", (new_u, new_p, new_r))
            conn.commit(); st.success(f"帳號 {new_u} 已更新")
        
        st.write("---")
        del_u = st.selectbox("刪除帳號", [r[0] for r in c.execute("SELECT username FROM users WHERE username != 'admin'").fetchall()])
        if st.button("確認刪除"):
            c.execute("DELETE FROM users WHERE username=?", (del_u,))
            conn.commit(); st.rerun()

    system_lock = st.sidebar.toggle("🔒 盤點鎖定", value=False)
else:
    system_lock = False # 員工無法切換，預設依賴伺服器狀態（此處簡化處理）

if st.sidebar.button("登出系統"):
    del st.session_state["user"]; del st.session_state["role"]; st.rerun()

# --- 5. 主選單 ---
menu = ["📊 庫存與追溯", "📝 進出貨登記", "🍎 商品維護"]
if current_role != "admin": menu.remove("🍎 商品維護")
choice = st.selectbox("功能導覽", menu)

# --- 功能 1：庫存與報表 ---
if choice == "📊 庫存與追溯":
    st.subheader("📦 即時庫存監控")
    c.execute("SELECT name, image_data, description, created_by, created_at FROM products")
    prods = c.fetchall()
    
    cols = st.columns(2 if st.sidebar.checkbox("手機模式", True) else 4)
    for idx, (name, img, desc, creator, ctime) in enumerate(prods):
        small_qty, profit, display_stock, ratio = get_stock_and_profit(name)
        with cols[idx % len(cols)]:
            if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
            st.markdown(f"**{name}**")
            st.markdown(f"庫存：**{display_stock}**")
            st.caption(f"建檔人: {creator} ({ctime})")
            if desc:
                with st.expander("📝 描述"): st.write(desc)
            st.divider()

    st.subheader("📜 歷史交易追溯 (含操作人)")
    history_df = pd.read_sql_query("SELECT name as 品項, type as 類型, qty as 數量, unit as 單位, price_at_time as 單價, date as 日期, operator as 操作員 FROM logs ORDER BY id DESC", conn)
    st.dataframe(history_df, use_container_width=True)

# --- 功能 2：進出貨登記 ---
elif choice == "📝 進出貨登記":
    if system_lock: st.error("🛑 盤點鎖定中")
    else:
        c.execute("SELECT name, big_unit, small_unit FROM products")
        items = c.fetchall()
        t_data = st.selectbox("選擇商品", items, format_func=lambda x: x[0])
        with st.form("trade"):
            t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
            t_qty = st.number_input("數量", min_value=1)
            t_unit = st.selectbox("單位", [t_data[1], t_data[2]])
            t_price = st.number_input("單價", min_value=0.0)
            if st.form_submit_button("確認提交"):
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)", 
                          (t_data[0], t_type, t_qty, t_unit, t_price, now_str, current_user))
                conn.commit(); st.success(f"登記成功！操作人：{current_user}"); st.balloons()

# --- 功能 3：商品維護 ---
elif choice == "🍎 商品維護":
    st.subheader("🍎 商品建檔與修改")
    c.execute("SELECT name FROM products")
    p_names = ["+ 新增"] + [r[0] for r in c.fetchall()]
    mode = st.selectbox("選擇商品", p_names)
    
    with st.form("prod_form"):
        name = st.text_input("商品名稱", value="" if mode=="+ 新增" else mode)
        col1, col2 = st.columns(2)
        with col1: b_u = st.text_input("大單位", value="箱")
        with col2: s_u = st.text_input("小單位", value="顆")
        ratio = st.number_input("換算率", min_value=1, value=10)
        cost = st.number_input("進貨成本", min_value=0.0)
        price = st.number_input("銷售單價", min_value=0.0)
        desc = st.text_area("詳細敘述")
        img = st.camera_input("照片")
        if st.form_submit_button("儲存資料"):
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            img_b64 = image_to_base64(img)
            c.execute("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (name, cost, price, b_u, s_u, ratio, 5, img_b64, desc, current_user, now_str))
            conn.commit(); st.success("儲存成功！"); st.rerun()
