import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime
import google.generativeai as genai
import plotly.express as px
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# --- 1. 系統初始化 (iOS PWA 優化版) ---
st.set_page_config(page_title="AI 智慧 ERP", layout="wide")

# 鎖定 API Key
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

# 資料庫連線 (建議版本號升級以刷新 PWA 快取)
conn = sqlite3.connect('erp_pwa_v20.db', check_same_thread=False)
c = conn.cursor()

def init_db():
    c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT UNIQUE, password TEXT, role TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS products 
                 (name TEXT UNIQUE, barcode TEXT, cost REAL, price REAL, big_unit TEXT, 
                  small_unit TEXT, ratio INTEGER, alert_level INTEGER, image_data TEXT, description TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs 
                 (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, 
                  price_at_time REAL, date TEXT, operator TEXT)''')
    c.execute("INSERT OR IGNORE INTO users VALUES ('admin', '8888', 'admin')")
    conn.commit()

init_db()

# --- 2. 核心計算工具 (修正 0箱0顆) ---
def get_detailed_stats(name):
    c.execute("SELECT big_unit, small_unit, ratio, cost, price, alert_level FROM products WHERE name=?", (name,))
    p = c.fetchone()
    if not p: return None
    big_u, small_u, ratio, cost, price, alert = p
    
    logs_df = pd.read_sql_query("SELECT type, qty, unit, price_at_time FROM logs WHERE name=?", conn, params=(name,))
    total_qty = 0
    profit = 0
    u_cost = (cost / ratio if ratio > 0 else 0)
    
    for _, row in logs_df.iterrows():
        real_q = row['qty'] * ratio if row['unit'] == big_u else row['qty']
        if row['type'] == '進貨': total_qty += real_q
        else:
            total_qty -= real_q
            profit += (row['qty'] * row['price_at_time']) - (real_q * u_cost)

    # 庫存顯示邏輯修正
    boxes = total_qty // ratio if ratio > 0 else 0
    units = total_qty % ratio if ratio > 0 else total_qty
    display = f"{boxes} {big_u} {units} {small_u}"

    return {"qty": total_qty, "display": display, "profit": profit, 
            "is_alert": total_qty <= (alert or 0), "ratio": ratio, 
            "big_u": big_u, "small_u": small_u, "price": price, "cost": cost}

def generate_pdf():
    buf = io.BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    p.drawString(50, 800, f"Inventory Report - {datetime.now().strftime('%Y-%m-%d')}")
    y = 770
    c.execute("SELECT name FROM products")
    for (n,) in c.fetchall():
        s = get_detailed_stats(n)
        p.drawString(50, y, f"Prod: {n} | Stock: {s['display']} | Profit: ${s['profit']:,.0f}")
        y -= 20
    p.save(); buf.seek(0); return buf

# --- 3. 登入系統 (核心修正：徹底解決元組問題) ---
if "user" not in st.session_state:
    st.title("🔐 系統登入")
    u = st.text_input("帳號")
    p = st.text_input("密碼", type="password")
    if st.button("登入系統", use_container_width=True):
        c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
        res = c.fetchone()
        if res:
            # 修正處：res[0] 是帳號字串，res[1] 是權限字串
            st.session_state["user"] = str(res[0])
            st.session_state["role"] = str(res[1])
            st.rerun()
        else: st.error("❌ 帳密錯誤")
    st.stop()

current_user = st.session_state["user"]
current_role = st.session_state["role"]

# --- 4. 導覽 ---
st.sidebar.markdown(f"使用者: **{current_user}**")
menu = ["庫存報表", "交易登記"]
if current_role == "admin":
    menu += ["商品管理", "帳號管理"]
choice = st.sidebar.selectbox("切換功能", menu)

if st.sidebar.button("登出"):
    st.session_state.clear(); st.rerun()

# --- 5. 功能模組 ---

if choice == "庫存報表":
    st.subheader("庫存即時狀態")
    if current_role == "admin":
        with st.expander("管理員工具箱 (下載後請按完成返回)", expanded=True):
            if st.button("執行 AI 診斷", use_container_width=True):
                with st.spinner("分析中..."):
                    c.execute("SELECT name FROM products")
                    inv = [f"{n}: {get_detailed_stats(n)['display']}" for (n,) in c.fetchall()]
                    genai.configure(api_key=GEMINI_API_KEY)
                    try:
                        model = genai.GenerativeModel('models/gemini-1.5-flash')
                        res = model.generate_content(f"庫存:{str(inv)}。請給3點補貨建議(繁中)。")
                        st.info(res.text)
                    except: st.error("AI 連線失敗")
            
            # 下載按鈕 (PWA 模式提醒)
            st.download_button("匯出 PDF 報表", generate_pdf(), "report.pdf", "application/pdf", use_container_width=True)
            h_df = pd.read_sql_query("SELECT name, type, qty, unit, date FROM logs", conn)
            st.download_button("匯出 CSV 明細", h_df.to_csv(index=False).encode('utf-8-sig'), "data.csv", use_container_width=True)

    # 卡片展示
    c.execute("SELECT name, image_data FROM products")
    items = c.fetchall()
    if items:
        cols = st.columns(2)
        for idx, (name, img) in enumerate(items):
            s = get_detailed_stats(name)
            with cols[idx % 2]:
                with st.container(border=True):
                    if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                    st.write(f"**{name}**")
                    if s["is_alert"]: st.error(f"預警: {s['display']}")
                    else: st.success(f"庫存: {s['display']}")

elif choice == "交易登記":
    st.subheader("進出貨登記")
    c.execute("SELECT name, barcode FROM products")
    prods = c.fetchall()
    scan = st.text_input("搜尋品項或條碼")
    matched = next((n for n, b in prods if scan in [n, str(b)]), None)
    names = [p[0] for p in prods]
    target = st.selectbox("選定商品", names, index=names.index(matched) if matched else 0)
    
    if target:
        s = get_detailed_stats(target)
        st.info(f"當前庫存：{s['display']}")
        with st.form("trade", clear_on_submit=True):
            t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
            t_qty = st.number_input("數量", min_value=1, value=1)
            t_unit = st.selectbox("單位", [s["big_u"], s["small_u"]])
            t_price = st.number_input("單價", value=s["price"] if t_type=="出貨" else s["cost"])
            if st.form_submit_button("確認提交"):
                op_qty = t_qty * s["ratio"] if t_unit == s["big_u"] else t_qty
                if t_type == "出貨" and op_qty > s["qty"]:
                    st.error(f"庫存不足！剩餘 {s['qty']} {s['small_u']}")
                else:
                    c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                              (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d"), current_user))
                    conn.commit(); st.success("登記完成"); st.rerun()

elif choice == "商品管理":
    st.subheader("商品建檔")
    c.execute("SELECT name FROM products")
    existing = ["+ 新增商品"] + [r[0] for r in c.fetchall()]
    mode = st.selectbox("對象", existing)
    with st.form("p_form", clear_on_submit=True):
        p_name = st.text_input("名稱", value="" if mode.startswith("+") else mode)
        p_barcode = st.text_input("條碼")
        p_cost = st.number_input("大單位進價")
        p_price = st.number_input("小單位售價")
        c1, c2, c3 = st.columns(3)
        p_big, p_small, p_ratio = c1.text_input("大單位"), c2.text_input("小單位"), c3.number_input("換算比", min_value=1)
        p_img = st.file_uploader("圖片", type=['jpg', 'png'])
        if st.form_submit_button("儲存"):
            b64 = ""
            if p_img:
                img = Image.open(p_img); img.thumbnail((300, 300))
                buf = io.BytesIO(); img.save(buf, format="JPEG"); b64 = base64.b64encode(buf.getvalue()).decode()
            if mode.startswith("+"):
                c.execute("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?)", (p_name, p_barcode, p_cost, p_price, p_big, p_small, p_ratio, 5, b64, ""))
            else:
                c.execute("UPDATE products SET barcode=?, cost=?, price=?, big_unit=?, small_unit=?, ratio=?, image_data=? WHERE name=?", (p_barcode, p_cost, p_price, p_big, p_small, p_ratio, b64, mode))
            conn.commit(); st.success("儲存成功"); st.rerun()

elif choice == "帳號管理":
    st.subheader("使用者管理")
    nu, np = st.text_input("帳號"), st.text_input("密碼", type="password")
    nr = st.selectbox("權限", ["staff", "admin"])
    if st.button("確認建立"):
        try:
            c.execute("INSERT INTO users VALUES (?,?,?)", (nu, np, nr)); conn.commit(); st.success("成功"); st.rerun()
        except: st.error("重複")
    st.divider()
    df = pd.read_sql_query("SELECT username, role FROM users", conn)
    st.table(df)
