import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 1. 資料庫初始化 (v11) ---
conn = sqlite3.connect('business_v11.db', check_same_thread=False)
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

# --- 2. 登入邏輯 ---
if "user" not in st.session_state:
    st.title("🔒 企業進銷存系統")
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

current_user, current_role = st.session_state["user"], st.session_state["role"]

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
    t_small_qty, t_profit, u_cost = 0, 0, (cost / ratio if ratio > 0 else 0)
    for t, q, u, p_at in logs:
        real_q = q * ratio if u == big_u else q
        if t == '進貨': t_small_qty += real_q
        else:
            t_small_qty -= real_q
            t_profit += (q * p_at) - (real_q * u_cost)
    return t_small_qty, t_profit, f"{t_small_qty // ratio} {big_u} {t_small_qty % ratio} {small_u}", ratio

# --- 4. 側邊欄 ---
st.sidebar.title(f"👤 {current_user}")
if current_role == "admin":
    with st.sidebar.expander("⚙️ 管理員工具"):
        new_u = st.text_input("新增帳號")
        new_p = st.text_input("密碼", type="password")
        if st.button("建立"):
            c.execute("INSERT OR REPLACE INTO users VALUES (?,?,'staff')", (new_u, new_p))
            conn.commit(); st.success("成功")
        system_lock = st.sidebar.toggle("🔒 盤點鎖定", value=False)
else: system_lock = False

if st.sidebar.button("🚪 登出"):
    del st.session_state["user"]; st.rerun()

menu = ["📊 報表與分析", "📝 登記", "🍎 設定"]
if current_role != "admin": menu.remove("🍎 設定")
choice = st.sidebar.selectbox("切換功能", menu)

# --- 功能 1：報表與分析 ---
if choice == "📊 報表與分析":
    st.subheader("📦 即時庫存報表")
    c.execute("SELECT name, image_data FROM products")
    prods = c.fetchall()
    if prods:
        all_p = 0
        profit_data = []
        cols = st.columns(2 if st.sidebar.checkbox("手機模式", True) else 4)
        for idx, (n, img) in enumerate(prods):
            sq, prof, ds, _ = get_stock_and_profit(n)
            all_p += prof
            profit_data.append({"品項": n, "毛利": prof})
            with cols[idx % len(cols)]:
                if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                st.markdown(f"**{n}**\n庫存：{ds}")
                st.divider()
        if current_role == "admin":
            st.sidebar.metric("總累計毛利", f"${all_p:,.0f}")
            st.subheader("📈 銷售獲利圖表")
            st.bar_chart(pd.DataFrame(profit_data).set_index("品項"))

# --- 功能 2：登記 (優化 iPhone 原生掃描指引) ---
elif choice == "📝 登記":
    st.subheader("📝 登記進銷貨")
    if system_lock: st.error("🛑 系統鎖定中")
    else:
        st.info("💡 iPhone 掃描指南：\n1. 點擊下方框框\n2. 點擊鍵盤上方的 [相機圖示] 或 長按框框選擇 [掃描條碼]")
        scan_input = st.text_input("📷 點此掃描或輸入條碼", key="barcode_scan")
        
        c.execute("SELECT name FROM products")
        names = [r[0] for r in c.fetchall()]
        idx = names.index(scan_input) if scan_input in names else 0
        target = st.selectbox("確認選擇品項", names, index=idx)
        
        if target:
            _, _, ds, _ = get_stock_and_profit(target)
            st.write(f"💡 目前庫存：{ds}")
            c.execute("SELECT big_unit, small_unit FROM products WHERE name=?", (target,))
            units = c.fetchone()
            with st.form("trade"):
                t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
                col1, col2 = st.columns(2)
                with col1: t_qty = st.number_input("數量", min_value=1)
                with col2: t_unit = st.selectbox("單位", units)
                t_price = st.number_input("成交單價")
                if st.form_submit_button("確認提交"):
                    c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                              (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                    conn.commit(); st.success("✅ 登記成功"); st.balloons()

# --- 功能 3：設定 ---
elif choice == "🍎 設定":
    st.subheader("🍎 商品維護與建檔")
    c.execute("SELECT name FROM products")
    exists = ["+ 新增"] + [r[0] for r in c.fetchall()]
    mode = st.selectbox("選擇商品", exists)
    
    iv = {"n":"","c":0.0,"p":0.0,"bu":"箱","su":"顆","r":10,"d":"","img":None}
    if mode != "+ 新增":
        c.execute("SELECT * FROM products WHERE name=?", (mode,))
        p = c.fetchone()
        if p: iv = {"n":p[0],"c":p[1],"p":p[2],"bu":p[3],"su":p[4],"r":p[5],"img":p[7],"d":p[8]}

    n = st.text_input("商品名稱 (可掃描條碼)", value=iv["n"])
    col1, col2 = st.columns(2)
    with col1: cost = st.number_input("整箱進貨成本", value=iv["c"])
    with col2: ratio = st.number_input("換算率", min_value=1, value=iv["r"])
    
    suggested = (cost/ratio) * 1.3 if ratio > 0 else 0
    price = st.number_input("建議單顆售價", value=float(iv["p"] if mode != "+ 新增" else suggested))

    with st.form("prod"):
        b_u, s_u = st.text_input("大單位", value=iv["bu"]), st.text_input("小單位", value=iv["su"])
        desc = st.text_area("描述", value=iv["d"])
        cam = st.camera_input("拍照")
        if st.form_submit_button("儲存商品"):
            img_b = image_to_base64(cam) if cam else iv["img"]
            c.execute("INSERT OR REPLACE INTO products (name, cost, price, big_unit, small_unit, ratio, alert_level, image_data, description, created_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (n, cost, price, b_u, s_u, ratio, 5, img_b, desc, current_user))
            conn.commit(); st.success("🎉 已儲存"); st.rerun()
