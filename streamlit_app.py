import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime
import google.generativeai as genai

# --- 1. 初始化與安全設定 ---
st.set_page_config(page_title="AI 智能進銷存系統 Pro", layout="wide", page_icon="🚀")

try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    GEMINI_API_KEY = ""

# 資料庫連線與自動修復
conn = sqlite3.connect('business_v21.db', check_same_thread=False)
c = conn.cursor()

def init_db():
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT UNIQUE, password TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs 
                 (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, 
                  price_at_time REAL, date TEXT, operator TEXT)''')
    
    # 欄位自動補齊
    cols = [("cost", "REAL"), ("price", "REAL"), ("big_unit", "TEXT"), 
            ("small_unit", "TEXT"), ("ratio", "INTEGER"), ("alert_level", "INTEGER"), 
            ("image_data", "TEXT"), ("description", "TEXT")]
    for col, dtype in cols:
        try: c.execute(f"ALTER TABLE products ADD COLUMN {col} {dtype}")
        except: pass
    
    c.execute("INSERT OR IGNORE INTO users VALUES ('admin', '8888', 'admin')")
    conn.commit()

init_db()

# --- 2. 核心邏輯工具 ---
def image_to_base64(image_file):
    if image_file:
        try:
            img = Image.open(image_file); img.thumbnail((300, 300))
            buf = io.BytesIO(); img.save(buf, format="JPEG", quality=80)
            return base64.b64encode(buf.getvalue()).decode()
        except: return None
    return None

def get_product_stats(name):
    """取得庫存、利潤、預警狀態"""
    c.execute("SELECT big_unit, small_unit, ratio, cost, price, alert_level FROM products WHERE name=?", (name,))
    p = c.fetchone()
    if not p: return None
    
    big_u, small_u, ratio, cost, price, alert = p
    c.execute("SELECT type, qty, unit, price_at_time FROM logs WHERE name=?", (name,))
    logs = c.fetchall()
    
    small_qty, profit, unit_cost = 0, 0, (cost / ratio if ratio > 0 else 0)
    for t, q, u, p_at in logs:
        real_q = q * ratio if u == big_u else q
        if t == '進貨': small_qty += real_q
        else:
            small_qty -= real_q
            profit += (q * p_at) - (real_q * unit_cost)
            
    return {
        "qty": small_qty,
        "display": f"{small_qty // ratio} {big_u} {small_qty % ratio} {small_u}",
        "profit": profit,
        "is_alert": small_qty <= (alert if alert else 0),
        "ratio": ratio, "big_u": big_u, "small_u": small_u
    }

def run_ai_diagnose(inv_summary, logs_summary):
    if not GEMINI_API_KEY: return "⚠️ 未偵測到 API Key"
    genai.configure(api_key=GEMINI_API_KEY)
    
    # 模型自動相容機制：Gemini 3 -> 2.0 -> 1.5
    models = ['gemini-3-flash-preview', 'gemini-2.0-flash', 'gemini-1.5-flash']
    prompt = f"身為專業電商分析師，分析以下庫存：{inv_summary} 與最近紀錄：{logs_summary}。請給出3點關於補貨與利潤優化的繁體中文建議。"
    
    for m_name in models:
        try:
            model = genai.GenerativeModel(m_name)
            response = model.generate_content(prompt)
            return response.text
        except: continue
    return "❌ 所有 AI 模型目前皆無法連線，請檢查網路或 API Key 權限。"

# --- 3. 權限與登入 ---
if "user" not in st.session_state:
    st.title("🚀 AI 智能進銷存系統")
    col_login, _ = st.columns([1, 2])
    with col_login:
        u = st.text_input("帳號")
        p = st.text_input("密碼", type="password")
        if st.button("登入系統", use_container_width=True):
            c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
            res = c.fetchone()
            if res:
                st.session_state["user"], st.session_state["role"] = res, res
                st.rerun()
            else: st.error("❌ 帳密錯誤")
    st.stop()

current_user, current_role = st.session_state["user"], st.session_state["role"]

# --- 4. 側邊欄與導覽 ---
st.sidebar.title(f"👤 {current_user}")
st.sidebar.caption(f"權限等級: {current_role}")

menu = ["📊 庫存戰情室", "📝 進出貨快速登記"]
if current_role == "admin":
    menu += ["🍎 商品檔案維護", "👥 系統帳號管理"]

choice = st.sidebar.selectbox("切換功能模組", menu)
if st.sidebar.button("🚪 登出系統", use_container_width=True):
    for key in list(st.session_state.keys()): del st.session_state[key]
    st.rerun()

# --- 5. 功能實作 ---

if choice == "📊 庫存戰情室":
    st.subheader("📊 即時庫存戰情室")
    
    # 管理員 AI 工具
    if current_role == "admin":
        with st.expander("🤖 AI 智慧營運診斷", expanded=False):
            if st.button("✨ 開始全盤數據分析"):
                with st.spinner("AI 正在分析數據..."):
                    c.execute("SELECT name FROM products")
                    inv_data = [f"{n}: {get_product_stats(n)['display']}" for (n,) in c.fetchall()]
                    logs_df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC LIMIT 15", conn)
                    st.info(run_ai_diagnose(str(inv_data), logs_df.to_string()))

    # 庫存卡片展示
    c.execute("SELECT name, image_data, description, price FROM products")
    prods = c.fetchall()
    if prods:
        cols = st.columns(4)
        for idx, (n, img, desc, price) in enumerate(prods):
            stats = get_product_stats(n)
            with cols[idx % 4]:
                st.container(border=True)
                if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                st.markdown(f"**{n}**")
                if stats["is_alert"]:
                    st.error(f"⚠️ 低庫存: {stats['display']}")
                else:
                    st.success(f"📦 庫存: {stats['display']}")
                st.caption(f"售價: ${price:.0f} | {desc if desc else ''}")

elif choice == "📝 進出貨快速登記":
    st.subheader("📝 進出貨快速登記")
    c.execute("SELECT name FROM products")
    names = [r[0] for r in c.fetchall()]
    
    scan = st.text_input("🔍 掃描條碼或輸入品項名稱")
    idx = names.index(scan) if scan in names else 0
    target = st.selectbox("選定商品", names, index=idx)
    
    if target:
        stats = get_product_stats(target)
        st.info(f"💡 當前剩餘：{stats['display']}")
        with st.form("trade_form", clear_on_submit=True):
            t_type = st.radio("作業類型", ["進貨", "出貨"], horizontal=True)
            t_qty = st.number_input("作業數量", min_value=1, step=1)
            t_unit = st.selectbox("使用單位", [stats["big_u"], stats["small_u"]])
            t_price = st.number_input("本次成交單價", value=0.0)
            
            if st.form_submit_button("✅ 點擊確認登記"):
                tx_q = t_qty * stats["ratio"] if t_unit == stats["big_u"] else t_qty
                if t_type == "出貨" and tx_q > stats["qty"]:
                    st.error("❌ 庫存不足，無法出貨！")
                else:
                    c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                              (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                    conn.commit()
                    st.success(f"已完成 {target} 的{t_type}登記")
                    st.balloons()

elif choice == "🍎 商品檔案維護":
    st.subheader("🍎 商品檔案建檔")
    c.execute("SELECT name FROM products")
    existing = ["+ 新增全新商品"] + [r[0] for r in c.fetchall()]
    mode = st.selectbox("選擇編輯對象", existing)
    
    with st.form("product_editor"):
        p_name = st.text_input("商品名稱", value="" if mode.startswith("+") else mode)
        col1, col2 = st.columns(2)
        p_cost = col1.number_input("進貨成本 (大單位)", min_value=0.0)
        p_price = col2.number_input("零售單價 (小單位)", min_value=0.0)
        
        col3, col4, col5 = st.columns(3)
        p_big = col3.text_input("大單位", value="箱")
        p_small = col4.text_input("小單位", value="瓶")
        p_ratio = col5.number_input("換算比 (1大=?小)", min_value=1, value=1)
        
        p_alert = st.number_input("安全庫存水位 (小單位)", min_value=0, value=10)
        p_desc = st.text_area("規格/描述")
        p_img = st.file_uploader("商品照片上傳", type=['jpg', 'png'])
        
        if st.form_submit_button("💾 儲存商品檔案"):
            img_b64 = image_to_base64(p_img)
            if mode.startswith("+"):
                c.execute('''INSERT INTO products (name, cost, price, big_unit, small_unit, ratio, alert_level, description, image_data) 
                             VALUES (?,?,?,?,?,?,?,?,?)''', (p_name, p_cost, p_price, p_big, p_small, p_ratio, p_alert, p_desc, img_b64))
            else:
                if not img_b64:
                    c.execute("SELECT image_data FROM products WHERE name=?", (mode,))
                    img_b64 = c.fetchone()[0]
                c.execute('''UPDATE products SET cost=?, price=?, big_unit=?, small_unit=?, ratio=?, alert_level=?, description=?, image_data=? WHERE name=?''',
                          (p_cost, p_price, p_big, p_small, p_ratio, p_alert, p_desc, img_b64, mode))
            conn.commit()
            st.success("檔案已更新！")
            st.rerun()

elif choice == "👥 系統帳號管理":
    st.subheader("👥 系統權限管理")
    # 此部分保留您之前的帳號增減邏輯... (略)




