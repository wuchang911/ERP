import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime
import google.generativeai as genai

# --- 1. 介面與資料庫初始化 ---
st.set_page_config(page_title="AI 智能進銷存系統", layout="wide", page_icon="🚀")

# 🔒 安全讀取 API Key
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    GEMINI_API_KEY = ""

conn = sqlite3.connect('business_v21.db', check_same_thread=False)
c = conn.cursor()

# 建立基礎結構
c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT UNIQUE, password TEXT, role TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE)''')
c.execute('''CREATE TABLE IF NOT EXISTS logs 
             (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, 
              price_at_time REAL, date TEXT, operator TEXT)''')

# 🛡️ 自動修復資料表結構 (避免 OperationalError)
product_cols = [
    ("cost", "REAL"), ("price", "REAL"), ("big_unit", "TEXT"), 
    ("small_unit", "TEXT"), ("ratio", "INTEGER"), ("alert_level", "INTEGER"), 
    ("image_data", "TEXT"), ("description", "TEXT"), ("created_by", "TEXT"), ("created_at", "TEXT")
]
for col_name, col_type in product_cols:
    try:
        c.execute(f"ALTER TABLE products ADD COLUMN {col_name} {col_type}")
    except: pass # 欄位已存在

# 初始化預設管理員
c.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES ('admin', '8888', 'admin')")
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
    c.execute("SELECT big_unit, small_unit, ratio, cost, price, alert_level FROM products WHERE name=?", (name,))
    p = c.fetchone()
    if not p or p[0] is None: return 0, 0, "無資料", 1, 0
    big_u, small_u, ratio, cost, price, alert = p
    c.execute("SELECT type, qty, unit, price_at_time FROM logs WHERE name=?", (name,))
    logs = c.fetchall()
    t_small_qty, t_profit, u_cost = 0, 0, (cost / ratio if ratio > 0 else 0)
    for t, q, u, p_at in logs:
        real_q = q * ratio if u == big_u else q
        if t == '進貨': t_small_qty += real_q
        else:
            t_small_qty -= real_q
            t_profit += (q * p_at) - (real_q * u_cost)
    display_stock = f"{t_small_qty // ratio} {big_u} {t_small_qty % ratio} {small_u}"
    return t_small_qty, t_profit, display_stock, ratio, (alert if alert else 0)

def run_ai_analysis(inventory_summary, sales_summary):
    if not GEMINI_API_KEY: return "⚠️ 未設定 API Key。"
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        
        # 修正這裡：改用你在 Playground 看到的最新模型名稱
        model = genai.GenerativeModel('gemini-3-flash-preview') 
        
        prompt = f"你是一位專業分析師。庫存：{inventory_summary}\n銷售紀錄：{sales_summary}\n請提供3條關於補貨與毛利的精簡建議。"
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        # 如果 gemini-3 報錯，嘗試改用 gemini-2.0-flash
        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
            return model.generate_content(prompt).text
        except:
            return f"AI 錯誤：{str(e)}。請確認 API Key 與模型名稱。"




# --- 3. 登入系統 ---
if "user" not in st.session_state:
    st.title("🔒 企業進銷存系統")
    u = st.text_input("帳號")
    p = st.text_input("密碼", type="password")
    if st.button("確認進入"):
        c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
        res = c.fetchone()
        if res:
            st.session_state["user"], st.session_state["role"] = res[0], res[1]
            st.rerun()
        else: st.error("❌ 帳密錯誤")
    st.stop()

current_user, current_role = st.session_state["user"], st.session_state["role"]

# --- 4. 快速操作與選單 ---
def quick_action_menu():
    with st.popover("➕ 快速操作"):
        if current_role == "admin":
            if st.button("✨ AI 診斷數據"):
                c.execute("SELECT name FROM products")
                inv_data = [f"{n}: {get_stock_and_profit(n)}" for (n,) in c.fetchall()]
                logs_df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC LIMIT 10", conn)
                st.info(run_ai_analysis(str(inv_data), logs_df.to_string()))
            st.session_state.is_locked = st.toggle("🔒 盤點鎖定", value=st.session_state.get('is_locked', False))
            st.divider()
        calc = st.text_input("🧮 計算機")
        if calc:
            try: st.success(f"結果: {eval(calc.replace('x', '*'))}")
            except: pass

st.sidebar.title(f"👤 {current_user}")
if st.sidebar.button("🚪 登出"):
    for key in list(st.session_state.keys()): del st.session_state[key]
    st.rerun()

menu = ["📊 庫存報表", "📝 進出貨登記"]
if current_role == "admin": menu += ["🍎 商品維護設定", "👥 帳號管理"]
choice = st.sidebar.selectbox("切換功能", menu)

# --- 5. 功能模組 ---
if choice == "📊 庫存報表":
    st.subheader("📦 即時庫存監控")
    quick_action_menu()
    c.execute("SELECT name, image_data, description FROM products")
    prods = c.fetchall()
    if prods:
        cols = st.columns(4)
        for idx, (n, img, desc) in enumerate(prods):
            sq, prof, ds, ratio, alert = get_stock_and_profit(n)
            with cols[idx % 4]:
                if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                st.write(f"**{n}**")
                if sq <= alert: st.error(f"低庫存：{ds}")
                else: st.success(f"庫存：{ds}")
                with st.expander("📄 詳細"):
                    st.caption(f"描述：{desc if desc else '無'}")
                    if current_role == "admin": st.write(f"累計毛利：${prof:,.0f}")
    
    st.subheader("📜 最近紀錄")
    st.dataframe(pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC LIMIT 10", conn), use_container_width=True)

elif choice == "📝 進出貨登記":
    st.subheader("📝 登記進銷貨")
    quick_action_menu()
    if st.session_state.get('is_locked', False): st.error("🛑 盤點鎖定中")
    else:
        c.execute("SELECT name FROM products")
        names = [r[0] for r in c.fetchall()]
        scan = st.text_input("📷 掃描/搜尋品項")
        idx = names.index(scan) if scan in names else 0
        target = st.selectbox("確認品項", names, index=idx)
        if target:
            sq, _, ds, ratio, _ = get_stock_and_profit(target)
            c.execute("SELECT big_unit, small_unit FROM products WHERE name=?", (target,))
            b_u, s_u = c.fetchone()
            st.info(f"庫存：{ds}")
            with st.form("trade"):
                t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
                t_qty = st.number_input("數量", min_value=1)
                t_unit = st.selectbox("單位", [b_u, s_u])
                t_price = st.number_input("成交單價", min_value=0.0)
                if st.form_submit_button("提交"):
                    tx_sq = t_qty * ratio if t_unit == b_u else t_qty
                    if t_type == "出貨" and tx_sq > sq: st.error("❌ 庫存不足")
                    else:
                        c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                                  (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                        conn.commit(); st.success("✅ 登記完成"); st.balloons()

elif choice == "🍎 商品維護設定":
    st.subheader("🍎 商品管理")
    c.execute("SELECT name FROM products")
    existing = ["+ 新增商品"] + [r[0] for r in c.fetchall() if r[0] is not None]
    mode = st.selectbox("選擇商品", existing)
    
    with st.form("product_form"):
        p_name = st.text_input("名稱", value="" if mode=="+ 新增商品" else mode)
        col1, col2 = st.columns(2)
        p_cost = col1.number_input("成本(大)", min_value=0.0)
        p_price = col2.number_input("售價(小)", min_value=0.0)
        col3, col4, col5 = st.columns(3)
        p_big = col3.text_input("大單位", value="箱")
        p_small = col4.text_input("小單位", value="瓶")
        p_ratio = col5.number_input("換算率", min_value=1, value=1)
        p_alert = st.number_input("預警水位(小)", min_value=0, value=5)
        p_desc = st.text_area("備註說明")
        p_img = st.file_uploader("上傳圖片", type=['jpg','png'])
        if st.form_submit_button("💾 儲存"):
            img_b64 = image_to_base64(p_img)
            if mode == "+ 新增商品":
                c.execute('''INSERT INTO products (name, cost, price, big_unit, small_unit, ratio, alert_level, description, image_data) 
                             VALUES (?,?,?,?,?,?,?,?,?)''', (p_name, p_cost, p_price, p_big, p_small, p_ratio, p_alert, p_desc, img_b64))
            else:
                if not img_b64:
                    c.execute("SELECT image_data FROM products WHERE name=?", (mode,))
                    img_b64 = c.fetchone()[0]
                c.execute('''UPDATE products SET cost=?, price=?, big_unit=?, small_unit=?, ratio=?, alert_level=?, description=?, image_data=? WHERE name=?''',
                          (p_cost, p_price, p_big, p_small, p_ratio, p_alert, p_desc, img_b64, mode))
            conn.commit(); st.success("已儲存"); st.rerun()

elif choice == "👥 帳號管理":
    st.subheader("👥 使用者管理")
    with st.expander("➕ 新增帳號"):
        nu, np = st.text_input("帳號"), st.text_input("密碼", type="password")
        nr = st.selectbox("角色", ["staff", "admin"])
        if st.button("建立"):
            try:
                c.execute("INSERT INTO users VALUES (?,?,?)", (nu, np, nr))
                conn.commit(); st.rerun()
            except: st.error("帳號已存在")
    st.divider()
    users = pd.read_sql_query("SELECT username, role FROM users", conn)
    for i, r in users.iterrows():
        col1, col2 = st.columns([3, 1])
        col1.write(f"👤 {r['username']} ({r['role']})")
        if r['username'] != 'admin' and col2.button("刪除", key=f"u_{i}"):
            c.execute("DELETE FROM users WHERE username=?", (r['username'],))
            conn.commit(); st.rerun()



