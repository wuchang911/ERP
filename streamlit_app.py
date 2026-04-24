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

conn = sqlite3.connect('business_pro_v35.db', check_same_thread=False)
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
    if not GEMINI_API_KEY: return "⚠️ 未設定 API Key"
    genai.configure(api_key=GEMINI_API_KEY)
    # 使用截圖中確認可用的模型名稱
    models = ['gemini-3-flash-preview', 'gemini-2.0-flash', 'gemini-1.5-flash']
    prompt = f"分析庫存：{inv_summary}\n紀錄：{logs_summary}\n請給出3點專業建議(繁體中文)。"
    for m in models:
        try:
            res = genai.GenerativeModel(m).generate_content(prompt)
            return res.text
        except: continue
    return "❌ AI 無法連線，請檢查網路環境。"

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

# --- 3. 登入系統 (核心修正：拆解元組) ---
if "user" not in st.session_state:
    st.title("🔒 企業進銷存登入")
    u = st.text_input("帳號")
    p = st.text_input("密碼", type="password")
    if st.button("確認進入系統", use_container_width=True):
        c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
        res = c.fetchone()
        if res:
            # 修正處：直接儲存字串而非元組
            st.session_state["user"] = res[0]
            st.session_state["role"] = res[1]
            st.rerun()
        else: st.error("❌ 帳密錯誤")
    st.stop()

current_user = st.session_state["user"]
current_role = st.session_state["role"]

# --- 4. 側邊欄與選單 ---
st.sidebar.markdown(f"### 👤 使用者: **{current_user}**")
st.sidebar.markdown(f"權限: `{current_role}`")

menu = ["📊 庫存戰情室", "📝 進出貨登記"]
if current_role == "admin":
    menu += ["🍎 商品檔案管理", "👥 帳號權限管理"]

choice = st.sidebar.selectbox("功能導覽", menu)
if st.sidebar.button("🚪 登出系統", use_container_width=True):
    for k in list(st.session_state.keys()): del st.session_state[k]
    st.rerun()

# --- 5. 功能實作 ---

def admin_toolbox():
    """修正排版：避免重疊，僅限管理員"""
    if current_role == "admin":
        with st.expander("🛠️ 管理員智慧工具箱", expanded=True):
            c1, c2, c3 = st.columns(3)
            if c1.button("✨ AI 診斷", use_container_width=True):
                with st.spinner("AI 分析中..."):
                    c.execute("SELECT name FROM products")
                    inv = [f"{n}: {get_product_stats(n)['display']}" for (n,) in c.fetchall()]
                    logs = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC LIMIT 15", conn)
                    st.info(run_ai_diagnose(str(inv), logs.to_string()))
            
            c2.download_button("📥 匯出 PDF", generate_pdf(), "Report.pdf", use_container_width=True)
            
            h_df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC", conn)
            c3.download_button("📥 匯出 CSV", h_df.to_csv(index=False).encode('utf-8-sig'), "history.csv", use_container_width=True)
            
            st.session_state.is_locked = st.toggle("🔒 盤點鎖定模式", value=st.session_state.get('is_locked', False))
        
        calc = st.text_input("🧮 快速計算機")
        if calc:
            try: st.success(f"結果: {eval(calc.replace('x', '*'))}")
            except: pass

if choice == "📊 庫存戰情室":
    st.subheader("📊 庫存即時戰情")
    admin_toolbox()
    c.execute("SELECT name, image_data, description FROM products")
    prods = c.fetchall()
    if prods:
        cols = st.columns(2 if st.sidebar.checkbox("手機視圖", True) else 4)
        for idx, (n, img, desc) in enumerate(prods):
            s = get_product_stats(n)
            with cols[idx % len(cols)]:
                with st.container(border=True):
                    if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                    st.markdown(f"**{n}**")
                    if s["is_alert"]: st.error(f"⚠️ 庫存: {s['display']}")
                    else: st.success(f"📦 庫存: {s['display']}")
                    with st.expander("📄 詳細分析"):
                        st.write(f"累計毛利: ${s['profit']:,.0f}")
                        st.progress(min(s['turnover']/3, 1.0), text="流動速度")
    st.divider()
    st.write("📜 最近異動紀錄")
    st.dataframe(pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC LIMIT 10", conn), use_container_width=True)

elif choice == "📝 進出貨登記":
    st.subheader("📝 登記進銷交易")
    if st.session_state.get('is_locked', False): st.error("🛑 系統鎖定中")
    else:
        c.execute("SELECT name FROM products")
        names = [r[0] for r in c.fetchall()]
        scan = st.text_input("🔍 搜尋品項或掃描")
        target = st.selectbox("選定商品", names, index=names.index(scan) if scan in names else 0)
        if target:
            s = get_product_stats(target)
            st.info(f"💡 目前庫存：{s['display']}")
            with st.form("trade", clear_on_submit=True):
                t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
                t_qty = st.number_input("數量", min_value=1)
                t_unit = st.selectbox("單位", [s["big_u"], s["small_u"]])
                t_price = st.number_input("成交單價", value=s["price"] if t_type=="出貨" else s["cost"])
                if st.form_submit_button("✅ 確認提交"):
                    tx = t_qty * s["ratio"] if t_unit == s["big_u"] else t_qty
                    if t_type == "出貨" and tx > s["qty"]: st.error("❌ 庫存不足")
                    else:
                        c.execute("INSERT INTO logs (name,type,qty,unit,price_at_time,date,operator) VALUES (?,?,?,?,?,?,?)",
                                  (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                        conn.commit(); st.success("✅ 登記成功"); st.balloons()

elif choice == "🍎 商品檔案管理":
    st.subheader("🍎 商品檔案維護")
    c.execute("SELECT name FROM products")
    existing = ["+ 新增商品"] + [r[0] for r in c.fetchall()]
    mode = st.selectbox("選擇商品", existing)
    with st.form("p_form", clear_on_submit=True):
        p_name = st.text_input("商品名稱", value="" if mode=="+ 新增商品" else mode)
        p_cost = st.number_input("進價(大單位)", min_value=0.0)
        p_price = st.number_input("售價(小單位)", min_value=0.0)
        col1, col2, col3 = st.columns(3)
        p_big, p_small, p_ratio = col1.text_input("大單位"), col2.text_input("小單位"), col3.number_input("換算比", min_value=1)
        p_alert = st.number_input("預警水位", min_value=0)
        p_desc = st.text_area("備註說明")
        p_img = st.file_uploader("上傳圖片", type=['jpg', 'png'])
        if st.form_submit_button("💾 儲存檔案"):
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
            conn.commit(); st.success("儲存成功"); st.rerun()

elif choice == "👥 帳號權限管理":
    st.subheader("👥 帳號管理中心")
    with st.container(border=True):
        nu, np = st.text_input("新增帳號"), st.text_input("設定密碼", type="password")
        nr = st.selectbox("權限", ["staff", "admin"])
        if st.button("確認建立帳號"):
            try:
                c.execute("INSERT INTO users VALUES (?,?,?)", (nu, np, nr)); conn.commit(); st.success("已建立"); st.rerun()
            except: st.error("帳號重複")
    st.divider()
    users = pd.read_sql_query("SELECT username, role FROM users", conn)
    for i, r in users.iterrows():
        c1, c2, c3 = st.columns(3)
        c1.write(f"👤 {r['username']}")
        c2.write(f"🔑 {r['role']}")
        if r['username'] != 'admin' and c3.button("刪除", key=f"u_{i}"):
            c.execute("DELETE FROM users WHERE username=?", (r['username'],)); conn.commit(); st.rerun()
