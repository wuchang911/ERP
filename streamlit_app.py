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

# --- 1. 系統初始化 ---
st.set_page_config(page_title="AI 智慧 ERP 系統", layout="wide")

try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    GEMINI_API_KEY = ""

# 使用 v12 版本資料庫
conn = sqlite3.connect('erp_pro_v12.db', check_same_thread=False)
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

# --- 2. 核心計算工具 (修正庫存顯示邏輯) ---
def get_detailed_stats(name):
    c.execute("SELECT big_unit, small_unit, ratio, cost, price, alert_level FROM products WHERE name=?", (name,))
    p = c.fetchone()
    if not p: return None
    big_u, small_u, ratio, cost, price, alert = p
    
    logs_df = pd.read_sql_query("SELECT * FROM logs WHERE name=?", conn, params=(name,))
    total_small_qty, profit = 0, 0
    u_cost = (cost / ratio if ratio > 0 else 0)
    
    for _, row in logs_df.iterrows():
        # 換算為最小單位總數
        real_q = row['qty'] * ratio if row['unit'] == big_u else row['qty']
        if row['type'] == '進貨':
            total_small_qty += real_q
        else:
            total_small_qty -= real_q
            profit += (row['qty'] * row['price_at_time']) - (real_q * u_cost)

    # 修正顯示邏輯：確保即使不滿一箱，也能看到剩餘顆數
    # 範例：99顆 -> 0箱 99顆 (且在登記頁面會提示 99顆)
    if ratio > 0:
        display_stock = f"{total_small_qty // ratio} {big_u} {total_small_qty % ratio} {small_u}"
    else:
        display_stock = f"{total_small_qty} {small_u}"

    return {
        "qty": total_small_qty, 
        "display": display_stock,
        "profit": profit, 
        "is_alert": total_small_qty <= (alert or 0),
        "ratio": ratio, "big_u": big_u, "small_u": small_u, "price": price, "cost": cost
    }

def generate_pdf_report():
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

# --- 3. 權限控管 ---
if "user" not in st.session_state:
    st.title("🔐 企業智慧 ERP 登入")
    u, p = st.text_input("帳號"), st.text_input("密碼", type="password")
    if st.button("確認進入系統", use_container_width=True):
        c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
        res = c.fetchone()
        if res:
            st.session_state["user"], st.session_state["role"] = res, res
            st.rerun()
    st.stop()

current_user, current_role = st.session_state["user"], st.session_state["role"]

# --- 4. 側邊導覽 ---
st.sidebar.markdown(f"### 👤 {current_user}")
menu = ["📊 營運數據總覽", "📝 進出貨自動登記"]
if current_role == "admin":
    menu += ["🍎 商品檔案中心", "👥 使用者管理"]
choice = st.sidebar.selectbox("切換功能", menu)

if st.sidebar.button("🚪 登出系統"):
    st.session_state.clear(); st.rerun()

# --- 5. 功能實作 ---

if choice == "📊 營運數據總覽":
    st.subheader("📊 即時營運戰情室")
    with st.expander("🛠️ 管理員智慧工具箱", expanded=True):
        c1, c2, c3 = st.columns(3)
        if current_role == "admin":
            if c1.button("✨ 執行 AI 數據診斷", use_container_width=True):
                with st.spinner("AI 正在閱讀數據..."):
                    c.execute("SELECT name FROM products")
                    inv = [f"{n}: {get_detailed_stats(n)['display']}" for (n,) in c.fetchall()]
                    genai.configure(api_key=GEMINI_API_KEY)
                    try:
                        model = genai.GenerativeModel('models/gemini-1.5-flash')
                        res = model.generate_content(f"庫存狀況：{str(inv)}。請提供3點建議（繁中）。")
                        st.info(res.text)
                    except: st.error("AI 暫時無法連線")
            
            st.download_button("📥 匯出 PDF 報表", generate_pdf_report(), "庫存報表.pdf", "application/pdf", use_container_width=True)
            
            h_df = pd.read_sql_query("SELECT name, type, qty, unit, date FROM logs", conn)
            h_df.columns = ["品項名稱", "類型", "數量", "單位", "日期"]
            c3.download_button("📥 匯出 CSV 明細", h_df.to_csv(index=False).encode('utf-8-sig'), "交易明細.csv", "text/csv", use_container_width=True)

    # 顯示各商品庫存卡片
    c.execute("SELECT name, image_data FROM products")
    items = c.fetchall()
    if items:
        cols = st.columns(4)
        for idx, (name, img) in enumerate(items):
            s = get_detailed_stats(name)
            with cols[idx % 4]:
                with st.container(border=True):
                    if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                    st.write(f"**{name}**")
                    if s["is_alert"]: st.error(f"⚠️ {s['display']}")
                    else: st.success(f"📦 {s['display']}")

elif choice == "📝 進出貨自動登記":
    st.subheader("📝 智慧化進出貨")
    c.execute("SELECT name, barcode FROM products")
    prods = c.fetchall()
    
    search = st.text_input("🔍 搜尋品項或掃描條碼")
    matched = next((n for n, b in prods if search in [n, b]), None)
    names = [p for p in prods]
    target = st.selectbox("選定商品", names, index=names.index(matched) if matched else 0)
    
    if target:
        s = get_detailed_stats(target)
        # 修正提示：清楚顯示目前剩下的最小單位總數
        st.warning(f"💡 目前庫存總計：{s['display']} (共 {s['qty']} {s['small_u']})")
        
        with st.form("trade", clear_on_submit=True):
            t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
            t_qty = st.number_input("作業數量", min_value=1, value=1)
            t_unit = st.selectbox("使用單位", [s["big_u"], s["small_u"]])
            t_price = st.number_input("成交單價", value=s["price"] if t_type=="出貨" else s["cost"])
            
            if st.form_submit_button("✅ 確認提交"):
                # 計算本次作業的最小單位總量
                op_qty = t_qty * s["ratio"] if t_unit == s["big_u"] else t_qty
                
                if t_type == "出貨" and op_qty > s["qty"]:
                    st.error(f"❌ 庫存不足！目前僅剩 {s['qty']} {s['small_u']}")
                else:
                    c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                              (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d"), current_user))
                    conn.commit()
                    st.success("登記完成！")
                    st.rerun()

elif choice == "🍎 商品檔案中心":
    st.subheader("🍎 商品檔案建檔")
    c.execute("SELECT name FROM products")
    existing = ["+ 新增商品"] + [r for r in c.fetchall()]
    mode = st.selectbox("選擇編輯對象", existing)
    
    with st.form("p_form", clear_on_submit=True):
        p_name = st.text_input("名稱", value="" if mode.startswith("+") else mode)
        p_barcode = st.text_input("條碼 (Barcode)")
        p_cost = st.number_input("進成本 (大單位)")
        p_price = st.number_input("售單價 (小單位)")
        col1, col2, col3 = st.columns(3)
        p_big, p_small, p_ratio = col1.text_input("大單位"), col2.text_input("小單位"), col3.number_input("換算比", min_value=1, value=1)
        p_alert = st.number_input("預警水位 (小單位)", value=5)
        p_img = st.file_uploader("圖片上傳", type=['jpg', 'png'])
        
        if st.form_submit_button("💾 儲存商品"):
            img_b64 = ""
            if p_img:
                img = Image.open(p_img); img.thumbnail((300, 300))
                buf = io.BytesIO(); img.save(buf, format="JPEG"); img_b64 = base64.b64encode(buf.getvalue()).decode()
            
            if mode.startswith("+"):
                c.execute("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?)", (p_name, p_barcode, p_cost, p_price, p_big, p_small, p_ratio, p_alert, img_b64, ""))
            else:
                c.execute("UPDATE products SET barcode=?, cost=?, price=?, big_unit=?, small_unit=?, ratio=?, alert_level=?, image_data=? WHERE name=?", (p_barcode, p_cost, p_price, p_big, p_small, p_ratio, p_alert, img_b64, mode))
            conn.commit(); st.success("儲存成功！"); st.rerun()

elif choice == "👥 使用者管理":
    st.subheader("👥 使用者管理")
    nu, np = st.text_input("帳號名稱"), st.text_input("初始密碼", type="password")
    nr = st.selectbox("角色", ["staff", "admin"])
    if st.button("建立帳號"):
        try:
            c.execute("INSERT INTO users VALUES (?,?,?)", (nu, np, nr)); conn.commit(); st.success("建立成功")
        except: st.error("帳號重複")
    st.divider()
    df = pd.read_sql_query("SELECT username, role FROM users", conn)
    df.columns = ["使用者帳號", "角色權限"]
    st.dataframe(df, use_container_width=True)
