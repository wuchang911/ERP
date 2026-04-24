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

# --- 1. 系統初始化與資料庫結構 ---
st.set_page_config(page_title="AI 智能進銷存 Pro", layout="wide", page_icon="🚀")

try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    GEMINI_API_KEY = ""

conn = sqlite3.connect('business_pro_v32.db', check_same_thread=False)
c = conn.cursor()

def init_db():
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT UNIQUE, password TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs 
                 (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, 
                  price_at_time REAL, date TEXT, operator TEXT)''')
    
    # 自動補齊所有必要欄位
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
    if not GEMINI_API_KEY: return "⚠️ 未設定 API Key"
    genai.configure(api_key=GEMINI_API_KEY)
    models = ['gemini-3-flash-preview', 'gemini-2.0-flash', 'gemini-1.5-flash']
    prompt = f"分析庫存：{inv_summary}\n最近紀錄：{logs_summary}\n請給出3點專業補貨與營運建議(繁體中文)。"
    for m in models:
        try:
            res = genai.GenerativeModel(m).generate_content(prompt)
            return res.text
        except: continue
    return "❌ AI 無法連線，請檢查網路環境或 API Key。"

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
    with st.container(border=True):
        u = st.text_input("帳號")
        p = st.text_input("密碼", type="password")
        if st.button("確認進入系統", use_container_width=True):
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
menu = ["📊 庫存戰情室", "📝 進出貨登記", "🍎 商品檔案管理", "👥 使用者帳號管理"]
# 權限過濾：非管理員隱藏後兩項
if current_role != "admin":
    menu = ["📊 庫存戰情室", "📝 進出貨登記"]

choice = st.sidebar.selectbox("切換主要功能", menu)
if st.sidebar.button("🚪 登出系統", use_container_width=True):
    for k in list(st.session_state.keys()): del st.session_state[k]
    st.rerun()

# --- 5. 功能模組實作 ---

def toolbox():
    """管理員工具箱排版優化"""
    with st.expander("🛠️ 管理員智慧工具箱", expanded=(choice == "📊 庫存戰情室")):
        c1, c2, c3, c4 = st.columns(4)
        if current_role == "admin":
            if c1.button("✨ 執行 AI 數據診斷", use_container_width=True):
                with st.spinner("AI 分析中..."):
                    c.execute("SELECT name FROM products")
                    inv = [f"{n}: {get_product_stats(n)['display']}" for (n,) in c.fetchall()]
                    logs = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC LIMIT 15", conn)
                    st.info(run_ai_diagnose(str(inv), logs.to_string()))
            c2.download_button("📥 匯出 PDF 報表", generate_pdf(), "Report.pdf", "application/pdf", use_container_width=True)
            h_df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC", conn)
            c3.download_button("📥 匯出 CSV 明細", h_df.to_csv(index=False).encode('utf-8-sig'), "history.csv", use_container_width=True)
            st.session_state.is_locked = c4.toggle("🔒 盤點鎖定模式", value=st.session_state.get('is_locked', False))
        
        calc = st.text_input("🧮 快速計算機 (例如: 1200 * 0.8)")
        if calc:
            try: st.success(f"結果: {eval(calc.replace('x', '*'))}")
            except: pass

if choice == "📊 庫存戰情室":
    st.subheader("📊 即時庫存戰情室")
    toolbox()
    c.execute("SELECT name, image_data, description FROM products")
    prods = c.fetchall()
    if prods:
        cols = st.columns(4)
        for idx, (n, img, desc) in enumerate(prods):
            s = get_product_stats(n)
            with cols[idx % 4]:
                with st.container(border=True):
                    if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                    st.markdown(f"**{n}**")
                    t_rate = s['turnover']
                    st.caption(f"🔥 流動指標: {'高' if t_rate > 1.5 else '低'} ({t_rate:.1f})")
                    if s["is_alert"]: st.error(f"⚠️ 庫存: {s['display']}")
                    else: st.success(f"📦 庫存: {s['display']}")
                    with st.expander("📄 詳細分析"):
                        st.write(f"累計毛利: ${s['profit']:,.0f}")
                        st.progress(min(t_rate/3, 1.0))
                        st.caption(f"描述: {desc if desc else '無備註'}")
    st.divider()
    st.write("📜 最近 10 筆異動紀錄")
    st.dataframe(pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC LIMIT 10", conn), use_container_width=True)

elif choice == "📝 進出貨登記":
    st.subheader("📝 進出貨交易登記")
    if st.session_state.get('is_locked', False): st.error("🛑 系統目前處於盤點鎖定狀態")
    else:
        c.execute("SELECT name FROM products")
        names = [r[0] for r in c.fetchall()]
        scan = st.text_input("🔍 搜尋品項或掃描條碼")
        target = st.selectbox("選定目標商品", names, index=names.index(scan) if scan in names else 0)
        if target:
            s = get_product_stats(target)
            st.info(f"💡 當前庫存：{s['display']}")
            with st.form("trade_form", clear_on_submit=True):
                t_type = st.radio("作業類型", ["進貨", "出貨"], horizontal=True)
                t_qty = st.number_input("作業數量", min_value=1)
                t_unit = st.selectbox("單位選擇", [s["big_u"], s["small_u"]])
                t_price = st.number_input("成交單價", value=s["price"] if t_type=="出貨" else s["cost"])
                if st.form_submit_button("✅ 確認提交"):
                    tx = t_qty * s["ratio"] if t_unit == s["big_u"] else t_qty
                    if t_type == "出貨" and tx > s["qty"]: st.error("❌ 庫存不足")
                    else:
                        c.execute("INSERT INTO logs (name,type,qty,unit,price_at_time,date,operator) VALUES (?,?,?,?,?,?,?)",
                                  (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                        conn.commit(); st.success("✅ 登記成功"); st.balloons()

elif choice == "🍎 商品檔案管理":
    st.subheader("🍎 商品檔案建檔與編輯")
    c.execute("SELECT name FROM products")
    existing = ["+ 新增商品"] + [r[0] for r in c.fetchall()]
    mode = st.selectbox("選擇編輯對象", existing)
    with st.form("p_form", clear_on_submit=True):
        p_name = st.text_input("商品名稱", value="" if mode=="+ 新增商品" else mode)
        c1, c2 = st.columns(2)
        p_cost = c1.number_input("進價 (大單位)", min_value=0.0)
        p_price = c2.number_input("售價 (小單位)", min_value=0.0)
        c3, c4, c5 = st.columns(3)
        p_big, p_small, p_ratio = c3.text_input("大單位名稱"), c4.text_input("小單位名稱"), c5.number_input("換算比", min_value=1)
        p_alert = st.number_input("低庫存預警水位 (小單位)", min_value=0)
        p_desc = st.text_area("商品描述/規格")
        p_img = st.file_uploader("商品圖片上傳", type=['jpg', 'png'])
        if st.form_submit_button("💾 儲存商品資訊"):
            b64 = image_to_base64(p_img)
            if mode == "+ 新增商品":
                c.execute('''INSERT INTO products (name, cost, price, big_unit, small_unit, ratio, alert_level, description, image_data) 
                             VALUES (?,?,?,?,?,?,?,?,?)''', (p_name, p_cost, p_price, p_big, p_small, p_ratio, p_alert, p_desc, b64))
            else:
                if not b64: 
                    c.execute("SELECT image_data FROM products WHERE name=?", (mode,))
                    res = c.fetchone()
                    b64 = res[0] if res else None
                c.execute('''UPDATE products SET cost=?, price=?, big_unit=?, small_unit=?, ratio=?, alert_level=?, description=?, image_data=? WHERE name=?''',
                          (p_cost, p_price, p_big, p_small, p_ratio, p_alert, p_desc, b64, mode))
            conn.commit(); st.success("✅ 檔案已成功儲存"); st.rerun()

elif choice == "👥 使用者帳號管理":
    st.subheader("👥 使用者管理與權限設定")
    with st.container(border=True):
        st.write("➕ 新增系統使用者")
        nu, np = st.text_input("使用者帳號"), st.text_input("初始密碼", type="password")
        nr = st.selectbox("權限角色", ["staff", "admin"])
        if st.button("確認建立帳號"):
            try:
                c.execute("INSERT INTO users VALUES (?,?,?)", (nu, np, nr)); conn.commit(); st.success("帳號已建立"); st.rerun()
            except: st.error("❌ 帳號名稱重複")
    st.divider()
    users = pd.read_sql_query("SELECT username, role FROM users", conn)
    st.write("📋 現有帳號清單")
    for i, r in users.iterrows():
        c1, c2, c3 = st.columns([2,2,1])
        c1.write(f"👤 **{r['username']}**")
        c2.write(f"🔑 權限: `{r['role']}`")
        if r['username'] != 'admin' and c3.button("刪除", key=f"u_{i}"):
            c.execute("DELETE FROM users WHERE username=?", (r['username'],)); conn.commit(); st.rerun()
