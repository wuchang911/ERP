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

# --- 1. 系統初始化 (確保視覺乾淨，移除所有衝突標籤) ---
st.set_page_config(page_title="AI 智慧 ERP 系統", layout="wide")

try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    GEMINI_API_KEY = ""

# 資料庫連線
conn = sqlite3.connect('erp_pro_v10.db', check_same_thread=False)
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

# --- 2. 統計工具函數 ---
def get_detailed_stats(name):
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
        "profit": profit, "is_alert": small_qty <= (alert or 0), "turnover": turnover,
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
        p.drawString(50, y, f"Product: {n} | Stock: {s['display']} | Profit: ${s['profit']:,.0f}")
        y -= 20
    p.save(); buf.seek(0); return buf

# --- 3. 權限控管 (修正登入後無法自動跳轉問題) ---
if "user" not in st.session_state:
    st.title("🔐 企業智慧 ERP 登入")
    with st.container(border=True):
        u = st.text_input("請輸入帳號")
        p = st.text_input("請輸入密碼", type="password")
        if st.button("確認進入系統", use_container_width=True):
            c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
            res = c.fetchone()
            if res:
                st.session_state["user"] = res[0]
                st.session_state["role"] = res[1]
                st.rerun()
            else: st.error("❌ 帳密錯誤，請重新輸入")
    st.stop()

current_user = st.session_state["user"]
current_role = st.session_state["role"]

# --- 4. 側邊導覽 ---
st.sidebar.markdown(f"### 👤 當前用戶: **{current_user}**")
st.sidebar.caption(f"權限層級: {current_role}")

menu = ["📊 營運數據總覽", "📝 進出貨自動登記"]
if current_role == "admin":
    menu += ["🍎 商品檔案中心", "👥 使用者管理"]
choice = st.sidebar.selectbox("模組功能切換", menu)

if st.sidebar.button("🚪 登出系統", use_container_width=True):
    st.session_state.clear(); st.rerun()

# --- 5. 各功能模組 ---

if choice == "📊 營運數據總覽":
    st.subheader("📊 即時營運戰情室")
    
    # 頂部工具箱
    with st.expander("🛠️ 管理員智慧工具箱", expanded=True):
        c1, c2, c3 = st.columns(3)
        if current_role == "admin":
            if c1.button("✨ 執行 AI 數據診斷", use_container_width=True):
                with st.spinner("AI 正在閱讀報表..."):
                    c.execute("SELECT name FROM products")
                    inv = [f"{n}: {get_detailed_stats(n)['display']}" for (n,) in c.fetchall()]
                    genai.configure(api_key=GEMINI_API_KEY)
                    try:
                        # 修正 404 錯誤：使用正確的模型路徑
                        model = genai.GenerativeModel('models/gemini-1.5-flash')
                        res = model.generate_content(f"分析庫存：{str(inv)}。請提供3點關於補貨與利潤的建議（繁體中文）。")
                        st.info(res.text)
                    except: st.error("AI 連線失敗，請檢查 API Key 設定")
            
            c2.download_button("📥 匯出 PDF 報表", generate_pdf_report(), "庫存報表.pdf", "application/pdf", use_container_width=True)
            
            h_df = pd.read_sql_query("SELECT name, type, qty, unit, date, operator FROM logs ORDER BY id DESC", conn)
            h_df.columns = ["品項名稱", "類型", "數量", "單位", "操作日期", "經辦人"]
            c3.download_button("📥 匯出 CSV 明細", h_df.to_csv(index=False).encode('utf-8-sig'), "交易紀錄.csv", "text/csv", use_container_width=True)
        else:
            st.info("👋 你好！戰情室功能將展示數據趨勢，進階診斷需管理員權限。")

    # 銷售趨勢圖
    all_logs = pd.read_sql_query("SELECT date, (qty * price_at_time) as revenue FROM logs WHERE type='出貨'", conn)
    if not all_logs.empty:
        fig = px.line(all_logs, x='date', y='revenue', title="每日銷貨營收趨勢圖")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("目前尚無銷售紀錄，無法繪製趨勢圖。")

elif choice == "📝 進出貨自動登記":
    st.subheader("📝 智慧化進出貨登記")
    c.execute("SELECT name, barcode FROM products")
    prods = c.fetchall()
    
    # 智慧搜尋與條碼連動
    search_input = st.text_input("🔍 搜尋品項名稱或掃描條碼")
    
    # 比對邏輯：先找條碼，再找名稱
    matched_name = None
    for name, code in prods:
        if search_input == code or search_input == name:
            matched_name = name
            break
            
    name_list = [p[0] for p in prods]
    target = st.selectbox("選定操作商品", name_list, index=name_list.index(matched_name) if matched_name else 0)
    
    if target:
        s = get_detailed_stats(target)
        st.success(f"💡 當前庫存剩餘：{s['display']}")
        with st.form("trade_form", clear_on_submit=True):
            t_type = st.radio("作業類型", ["進貨", "出貨"], horizontal=True)
            t_qty = st.number_input("作業數量", min_value=1, value=1)
            t_unit = st.selectbox("單位", [s["big_u"], s["small_u"]])
            t_price = st.number_input("成交單價", value=s["price"] if t_type=="出貨" else s["cost"])
            if st.form_submit_button("✅ 確認提交"):
                tx_q = t_qty * s["ratio"] if t_unit == s["big_u"] else t_qty
                if t_type == "出貨" and tx_q > s["qty"]:
                    st.error("❌ 庫存不足，無法出貨！")
                else:
                    c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                              (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d"), current_user))
                    conn.commit()
                    st.success(f"【{target}】{t_type}登記成功！")
                    st.rerun()

elif choice == "🍎 商品檔案中心":
    st.subheader("🍎 商品檔案與條碼建檔")
    c.execute("SELECT name FROM products")
    existing_names = [r[0] for r in c.fetchall()]
    mode = st.selectbox("編輯對象", ["+ 新增全新商品"] + existing_names)
    
    with st.form("product_form", clear_on_submit=True):
        p_name = st.text_input("商品名稱", value="" if mode.startswith("+") else mode)
        p_barcode = st.text_input("條碼編號 (Barcode)")
        col1, col2 = st.columns(2)
        p_cost = col1.number_input("進貨成本 (大單位)")
        p_price = col2.number_input("零售售價 (小單位)")
        col3, col4, col5 = st.columns(3)
        p_big = col3.text_input("大單位", value="箱")
        p_small = col4.text_input("小單位", value="瓶")
        p_ratio = col5.number_input("換算比例 (1大等於多少小)", min_value=1, value=1)
        p_img = st.file_uploader("商品圖片上傳", type=['jpg', 'png'])
        
        if st.form_submit_button("💾 儲存商品檔案"):
            img_b64 = ""
            if p_img:
                img = Image.open(p_img); img.thumbnail((300, 300))
                buf = io.BytesIO(); img.save(buf, format="JPEG"); img_b64 = base64.b64encode(buf.getvalue()).decode()
            
            if mode.startswith("+"):
                c.execute('''INSERT INTO products (name, barcode, cost, price, big_unit, small_unit, ratio, alert_level, image_data) 
                             VALUES (?,?,?,?,?,?,?,?,?)''', (p_name, p_barcode, p_cost, p_price, p_big, p_small, p_ratio, 5, img_b64))
            else:
                c.execute('''UPDATE products SET barcode=?, cost=?, price=?, big_unit=?, small_unit=?, ratio=?, image_data=? WHERE name=?''',
                          (p_barcode, p_cost, p_price, p_big, p_small, p_ratio, img_b64, mode))
            conn.commit()
            st.success("✅ 商品檔案已儲存成功！")
            st.rerun()

elif choice == "👥 使用者管理":
    st.subheader("👥 系統使用者帳號管理")
    with st.container(border=True):
        nu = st.text_input("新帳號名稱")
        np = st.text_input("初始密碼", type="password")
        nr = st.selectbox("角色權限", ["staff", "admin"])
        if st.button("確認建立新帳號"):
            try:
                c.execute("INSERT INTO users VALUES (?,?,?)", (nu, np, nr))
                conn.commit()
                st.success(f"使用者 {nu} 已建立成功！")
                st.rerun()
            except: st.error("❌ 帳號名稱重複")
    
    st.divider()
    # 表格中文化顯示
    user_df = pd.read_sql_query("SELECT username, role FROM users", conn)
    user_df.columns = ["使用者帳號", "角色權限"]
    st.write("📋 現有帳號清單：")
    st.dataframe(user_df, use_container_width=True)
