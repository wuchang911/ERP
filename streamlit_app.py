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
st.set_page_config(page_title="AI 智慧 ERP", layout="wide", initial_sidebar_state="collapsed")

# 鎖定 API Key
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

# 資料庫連線
conn = sqlite3.connect('erp_pwa_v21.db', check_same_thread=False)
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

# --- 2. 核心計算工具 ---
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
        if row['type'] == '進貨': 
            total_qty += real_q
        else:
            total_qty -= real_q
            profit += (row['qty'] * row['price_at_time']) - (real_q * u_cost)

    boxes = total_qty // ratio if ratio > 0 else 0
    units = total_qty % ratio if ratio > 0 else total_qty
    display = f"{int(boxes)} {big_u} {int(units)} {small_u}"

    return {"qty": total_qty, "display": display, "profit": profit, 
            "is_alert": total_qty <= (alert or 0), "ratio": ratio, 
            "big_u": big_u, "small_u": small_u, "price": price, "cost": cost}

def generate_pdf():
    buf = io.BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    p.setFont("Helvetica", 12)
    p.drawString(50, 800, f"Inventory Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    y = 770
    c.execute("SELECT name FROM products")
    for (n,) in c.fetchall():
        s = get_detailed_stats(n)
        p.drawString(50, y, f"Prod: {n} | Stock: {s['display']} | Profit: ${s['profit']:,.0f}")
        y -= 20
        if y < 50: p.showPage(); y = 800
    p.save(); buf.seek(0); return buf

# --- 3. 登入系統 ---
if "user" not in st.session_state:
    st.title("🔐 AI 智慧 ERP 系統")
    with st.container(border=True):
        u = st.text_input("帳號")
        p = st.text_input("密碼", type="password")
        if st.button("登入系統", use_container_width=True, type="primary"):
            c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
            res = c.fetchone()
            if res:
                st.session_state["user"] = str(res[0])
                st.session_state["role"] = str(res[1])
                st.rerun()
            else: st.error("❌ 帳密錯誤")
    st.stop()

current_user = st.session_state["user"]
current_role = st.session_state["role"]

# --- 4. 導覽 ---
st.sidebar.markdown(f"👤 使用者: **{current_user}**")
menu = ["庫存報表", "交易登記"]
if current_role == "admin":
    menu += ["商品管理", "帳號管理"]
choice = st.sidebar.selectbox("切換功能", menu)

if st.sidebar.button("登出系統"):
    st.session_state.clear(); st.rerun()

# --- 5. 功能模組 ---

if choice == "庫存報表":
    st.subheader("📦 庫存即時狀態")
    
    if current_role == "admin":
        with st.expander("🛠️ 管理員工具", expanded=False):
            col1, col2 = st.columns(2)
            if col1.button("🤖 AI 庫存分析", use_container_width=True):
                with st.spinner("AI 分析中..."):
                    c.execute("SELECT name FROM products")
                    inv = [f"{n}: {get_detailed_stats(n)['display']}" for (n,) in c.fetchall()]
                    if GEMINI_API_KEY:
                        genai.configure(api_key=GEMINI_API_KEY)
                        model = genai.GenerativeModel('gemini-1.5-flash')
                        res = model.generate_content(f"庫存:{str(inv)}。請針對以上庫存給3點繁體中文建議。")
                        st.info(res.text)
                    else: st.warning("未設定 API Key")
            
            st.download_button("📄 匯出 PDF 報表", generate_pdf(), "report.pdf", "application/pdf", use_container_width=True)
            h_df = pd.read_sql_query("SELECT * FROM logs", conn)
            st.download_button("📊 匯出 CSV 明細", h_df.to_csv(index=False).encode('utf-8-sig'), "data.csv", use_container_width=True)

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
                    st.markdown(f"**{name}**")
                    if s["is_alert"]: st.error(f"⚠️ 低庫存: {s['display']}")
                    else: st.success(f"庫存: {s['display']}")
                    st.caption(f"預估利潤: ${s['profit']:,.0f}")
    else:
        st.info("目前尚無商品資料，請先前往商品管理建檔。")

elif choice == "交易登記":
    st.subheader("📝 進出貨登記")
    c.execute("SELECT name, barcode FROM products")
    prods = c.fetchall()
    names = [p[0] for p in prods]
    
    if not names:
        st.warning("請先建立商品資料")
    else:
        scan = st.text_input("🔍 搜尋品項或掃描條碼")
        matched = next((n for n, b in prods if scan and (scan.lower() in n.lower() or scan == b)), None)
        target = st.selectbox("選定商品", names, index=names.index(matched) if matched else 0)
        
        if target:
            s = get_detailed_stats(target)
            st.metric("當前庫存", s["display"])
            with st.form("trade_form", clear_on_submit=True):
                t_type = st.radio("交易類型", ["進貨", "出貨"], horizontal=True)
                t_unit = st.selectbox("使用單位", [s["big_u"], s["small_u"]])
                t_qty = st.number_input("數量", min_value=1, value=1)
                t_price = st.number_input("單價", value=s["price"] if t_type=="出貨" else s["cost"])
                
                if st.form_submit_button("✅ 確認提交", use_container_width=True):
                    op_qty = t_qty * s["ratio"] if t_unit == s["big_u"] else t_qty
                    if t_type == "出貨" and op_qty > s["qty"]:
                        st.error(f"庫存不足！現有 {s['qty']} {s['small_u']}")
                    else:
                        c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                                  (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                        conn.commit()
                        st.success(f"{target} {t_type}成功！")
                        st.rerun()

elif choice == "商品管理":
    st.subheader("⚙️ 商品建檔管理")
    c.execute("SELECT name FROM products")
    prods_list = [r[0] for r in c.fetchall()]
    mode = st.selectbox("編輯對象", ["+ 新增商品"] + prods_list)
    
    # 讀取現有資料
    curr = {}
    if mode != "+ 新增商品":
        c.execute("SELECT * FROM products WHERE name=?", (mode,))
        r = c.fetchone()
        keys = ["name", "barcode", "cost", "price", "big_u", "small_u", "ratio", "alert", "img", "desc"]
        curr = dict(zip(keys, r))

    with st.form("p_form"):
        p_name = st.text_input("商品名稱", value=curr.get("name", ""))
        p_barcode = st.text_input("條碼編號", value=curr.get("barcode", ""))
        col1, col2 = st.columns(2)
        p_cost = col1.number_input("大單位進價", value=float(curr.get("cost", 0)))
        p_price = col2.number_input("小單位零售價", value=float(curr.get("price", 0)))
        
        c1, c2, c3 = st.columns(3)
        p_big = c1.text_input("大單位", value=curr.get("big_u", "箱"))
        p_small = c2.text_input("小單位", value=curr.get("small_u", "個"))
        p_ratio = c3.number_input("換算比", min_value=1, value=int(curr.get("ratio", 1)))
        
        p_img = st.file_uploader("商品圖片 (JPG/PNG)", type=['jpg', 'png'])
        
        if st.form_submit_button("💾 儲存商品資訊", use_container_width=True):
            b64 = curr.get("img", "")
            if p_img:
                img = Image.open(p_img).convert("RGB")
                img.thumbnail((300, 300))
                buf = io.BytesIO()
                img.save(buf, format="JPEG")
                b64 = base64.b64encode(buf.getvalue()).decode()
            
            if mode == "+ 新增商品":
                c.execute("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?,?)", 
                          (p_name, p_barcode, p_cost, p_price, p_big, p_small, p_ratio, 5, b64, ""))
            else:
                c.execute("UPDATE products SET name=?, barcode=?, cost=?, price=?, big_unit=?, small_unit=?, ratio=?, image_data=? WHERE name=?", 
                          (p_name, p_barcode, p_cost, p_price, p_big, p_small, p_ratio, b64, mode))
            conn.commit()
            st.success("資料已更新"); st.rerun()

    if mode != "+ 新增商品":
        if st.button("🗑️ 刪除商品", use_container_width=True):
            c.execute("DELETE FROM products WHERE name=?", (mode,))
            conn.commit(); st.rerun()
