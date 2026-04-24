import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime
import google.generativeai as genai
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# --- 1. 系統初始化 ---
st.set_page_config(page_title="AI 智能進銷存 Pro", layout="wide", page_icon="🚀")

try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    GEMINI_API_KEY = ""

# 使用 v3.1 確保資料庫結構最新
conn = sqlite3.connect('business_pro_v31.db', check_same_thread=False)
c = conn.cursor()

def init_db():
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT UNIQUE, password TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs 
                 (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, 
                  price_at_time REAL, date TEXT, operator TEXT)''')
    
    cols = [("cost", "REAL"), ("price", "REAL"), ("big_unit", "TEXT"), 
            ("small_unit", "TEXT"), ("ratio", "INTEGER"), ("alert_level", "INTEGER"), 
            ("image_data", "TEXT"), ("description", "TEXT")]
    for col, dtype in cols:
        try: c.execute(f"ALTER TABLE products ADD COLUMN {col} {dtype}")
        except: pass
    c.execute("INSERT OR IGNORE INTO users VALUES ('admin', '8888', 'admin')")
    conn.commit()

init_db()

# --- 2. 工具函數 ---
def image_to_base64(image_file):
    if image_file:
        try:
            img = Image.open(image_file); img.thumbnail((300, 300))
            buf = io.BytesIO(); img.save(buf, format="JPEG", quality=80)
            return base64.b64encode(buf.getvalue()).decode()
        except: return None
    return None

def get_product_stats(name):
    c.execute("SELECT big_unit, small_unit, ratio, cost, price, alert_level FROM products WHERE name=?", (name,))
    p = c.fetchone()
    if not p: return None
    big_u, small_u, ratio, cost, price, alert = p
    logs_df = pd.read_sql_query("SELECT * FROM logs WHERE name=?", conn, params=(name,))
    small_qty, profit, total_sold = 0, 0, 0
    u_cost = (cost / ratio if ratio > 0 else 0)
    for _, row in logs_df.iterrows():
        real_q = row['qty'] * ratio if row['unit'] == big_u else row['qty']
        if row['type'] == '進貨': small_qty += real_q
        else:
            small_qty -= real_q
            profit += (row['qty'] * row['price_at_time']) - (real_q * u_cost)
            total_sold += real_q
    turnover = total_sold / (small_qty + 1)
    return {
        "qty": small_qty, "display": f"{small_qty // ratio} {big_u} {small_qty % ratio} {small_u}",
        "profit": profit, "is_alert": small_qty <= (alert if alert else 0), "turnover": turnover,
        "ratio": ratio, "big_u": big_u, "small_u": small_u, "price": price, "cost": cost
    }

def run_ai_diagnose(inv_summary, logs_summary):
    if not GEMINI_API_KEY: return "⚠️ API Key 缺失"
    genai.configure(api_key=GEMINI_API_KEY)
    models = ['gemini-3-flash-preview', 'gemini-2.0-flash', 'gemini-1.5-flash']
    prompt = f"分析庫存：{inv_summary}\n紀錄：{logs_summary}\n請給出3點專業建議(繁體中文)。"
    for m in models:
        try:
            res = genai.GenerativeModel(m).generate_content(prompt)
            return res.text
        except: continue
    return "❌ AI 無法連線，請檢查網路或 API Key。"

def generate_pdf():
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, 800, f"Stock Report - {datetime.now().strftime('%Y-%m-%d')}")
    p.setFont("Helvetica", 10); y = 770
    c.execute("SELECT name FROM products")
    for (name,) in c.fetchall():
        s = get_product_stats(name)
        p.drawString(50, y, f"Product: {name} | Stock: {s['display']} | Profit: ${s['profit']:,.0f}")
        y -= 20
        if y < 50: p.showPage(); y = 800
    p.save(); buffer.seek(0); return buffer

# --- 3. 登入系統 ---
if "user" not in st.session_state:
    st.title("🚀 AI 智能進銷存 Pro")
    u, p = st.text_input("帳號"), st.text_input("密碼", type="password")
    if st.button("確認進入"):
        c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
        res = c.fetchone()
        if res:
            st.session_state["user"], st.session_state["role"] = res, res
            st.rerun()
        else: st.error("❌ 帳密錯誤")
    st.stop()

current_user, current_role = st.session_state["user"], st.session_state["role"]

# --- 4. 側邊欄 ---
st.sidebar.title(f"👤 {current_user}")
menu = ["📊 庫存戰情室", "📝 進出貨登記"]
if current_role == "admin": menu += ["🍎 商品檔案管理", "👥 使用者管理"]
choice = st.sidebar.selectbox("切換功能", menu)
if st.sidebar.button("🚪 登出系統"):
    for k in list(st.session_state.keys()): del st.session_state[k]
    st.rerun()

# --- 5. 功能模組 ---
def header_actions():
    """頂部快速操作欄，讓功能不再隱藏"""
    with st.expander("🛠️ 管理員/快速工具箱", expanded=(choice == "📊 庫存戰情室")):
        col1, col2, col3, col4 = st.columns(4)
        if current_role == "admin":
            if col1.button("✨ AI 智慧診斷"):
                with st.spinner("AI 分析中..."):
                    c.execute("SELECT name FROM products")
                    inv = [f"{n}: {get_product_stats(n)['display']}" for (n,) in c.fetchall()]
                    logs = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC LIMIT 15", conn)
                    st.info(run_ai_diagnose(str(inv), logs.to_string()))
            
            col2.download_button("📥 匯出 PDF", generate_pdf(), "Report.pdf", "application/pdf")
            
            h_df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC", conn)
            col3.download_button("📥 匯出 CSV", h_df.to_csv(index=False).encode('utf-8-sig'), "history.csv")
            
            st.session_state.is_locked = col4.toggle("🔒 鎖定模式", value=st.session_state.get('is_locked', False))
        
        calc = st.text_input("🧮 計算機 (如: 50*1.05)")
        if calc:
            try: st.success(f"結果: {eval(calc.replace('x', '*'))}")
            except: pass

if choice == "📊 庫存戰情室":
    st.subheader("📊 庫存戰情室")
    header_actions()
    c.execute("SELECT name, image_data, description FROM products")
    prods = c.fetchall()
    if prods:
        cols = st.columns(4)
        for idx, (n, img, desc) in enumerate(prods):
            s = get_product_stats(n)
            with cols[idx % 4]:
                st.container(border=True)
                if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                st.markdown(f"**{n}**")
                t_label = "🔥 高週轉" if s['turnover'] > 1.5 else "🧊 低週轉"
                st.caption(f"指標：{t_label}")
                if s["is_alert"]: st.error(f"⚠️ 庫存: {s['display']}")
                else: st.success(f"📦 庫存: {s['display']}")
                with st.expander("📄 分析"):
                    st.write(f"累計毛利: ${s['profit']:,.0f}")
                    st.progress(min(s['turnover']/3, 1.0), text="流動速度")
                    st.caption(f"描述: {desc if desc else '無'}")
    st.divider()
    st.dataframe(pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC LIMIT 10", conn), use_container_width=True)

elif choice == "📝 進出貨登記":
    st.subheader("📝 進出貨登記")
    if st.session_state.get('is_locked', False): st.error("🛑 盤點鎖定中")
    else:
        c.execute("SELECT name FROM products")
        names = [r[0] for r in c.fetchall()]
        scan = st.text_input("🔍 搜尋品項或掃描條碼")
        target = st.selectbox("選定商品", names, index=names.index(scan) if scan in names else 0)
        if target:
            s = get_product_stats(target)
            st.info(f"💡 目前庫存：{s['display']}")
            with st.form("trade", clear_on_submit=True):
                t_type = st.radio("作業", ["進貨", "出貨"], horizontal=True)
                t_qty = st.number_input("數量", min_value=1)
                t_unit = st.selectbox("單位", [s["big_u"], s["small_u"]])
                t_price = st.number_input("單價", value=s["price"] if t_type=="出貨" else s["cost"])
                if st.form_submit_button("✅ 確認登記"):
                    tx = t_qty * s["ratio"] if t_unit == s["big_u"] else t_qty
                    if t_type == "出貨" and tx > s["qty"]: st.error("❌ 庫存不足")
                    else:
                        c.execute("INSERT INTO logs (name,type,qty,unit,price_at_time,date,operator) VALUES (?,?,?,?,?,?,?)",
                                  (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                        conn.commit(); st.success("✅ 登記成功"); st.balloons()

elif choice == "🍎 商品檔案管理":
    st.subheader("🍎 商品管理")
    c.execute("SELECT name FROM products")
    existing = ["+ 新增商品"] + [r[0] for r in c.fetchall()]
    mode = st.selectbox("選擇商品", existing)
    with st.form("p_form"):
        p_name = st.text_input("名稱", value="" if mode=="+ 新增商品" else mode)
        p_cost, p_price = st.number_input("進價(大)"), st.number_input("售價(小)")
        col3, col4, col5 = st.columns(3)
        p_big, p_small, p_ratio = col3.text_input("大單位"), col4.text_input("小單位"), col5.number_input("換算比", min_value=1)
        p_alert = st.number_input("安全水位(小)", min_value=0)
        p_desc = st.text_area("說明")
        p_img = st.file_uploader("照片", type=['jpg', 'png'])
        if st.form_submit_button("💾 儲存"):
            b64 = image_to_base64(p_img)
            if mode == "+ 新增商品":
                c.execute('''INSERT INTO products (name, cost, price, big_unit, small_unit, ratio, alert_level, description, image_data) 
                             VALUES (?,?,?,?,?,?,?,?,?)''', (p_name, p_cost, p_price, p_big, p_small, p_ratio, p_alert, p_desc, b64))
            else:
                if not b64: c.execute("SELECT image_data FROM products WHERE name=?", (mode,)); b64 = c.fetchone()[0]
                c.execute('''UPDATE products SET cost=?, price=?, big_unit=?, small_unit=?, ratio=?, alert_level=?, description=?, image_data=? WHERE name=?''',
                          (p_cost, p_price, p_big, p_small, p_ratio, p_alert, p_desc, b64, mode))
            conn.commit(); st.success("儲存成功"); st.rerun()

elif choice == "👥 使用者管理":
    st.subheader("👥 使用者管理")
    nu, np = st.text_input("新帳號"), st.text_input("新密碼", type="password")
    nr = st.selectbox("權限", ["staff", "admin"])
    if st.button("確認建立使用者"):
        try:
            c.execute("INSERT INTO users VALUES (?,?,?)", (nu, np, nr)); conn.commit(); st.rerun()
        except: st.error("帳號重複")
    st.divider()
    users = pd.read_sql_query("SELECT username, role FROM users", conn)
    for i, r in users.iterrows():
        c1, c2, c3 = st.columns(3)
        c1.write(f"👤 {r['username']}")
        c2.write(f"🔑 {r['role']}")
        if r['username'] != 'admin' and c3.button("刪除", key=f"u_{i}"):
            c.execute("DELETE FROM users WHERE username=?", (r['username'],)); conn.commit(); st.rerun()
