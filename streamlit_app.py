import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime, timedelta
import google.generativeai as genai
import plotly.express as px
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# --- 1. 系統初始化與安全設定 ---
st.set_page_config(page_title="AI 智慧 ERP 系統", layout="wide", page_icon="📈")

try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    GEMINI_API_KEY = ""

# 使用 V6 版本資料庫以支援新功能 (建議重新啟動 App)
conn = sqlite3.connect('erp_pro_v6.db', check_same_thread=False)
c = conn.cursor()

def init_db():
    c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT UNIQUE, password TEXT, role TEXT)')
    # 擴充產品表：增加條碼欄位
    c.execute('''CREATE TABLE IF NOT EXISTS products 
                 (name TEXT UNIQUE, barcode TEXT, cost REAL, price REAL, big_unit TEXT, 
                  small_unit TEXT, ratio INTEGER, alert_level INTEGER, image_data TEXT, description TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs 
                 (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, 
                  price_at_time REAL, date TEXT, operator TEXT)''')
    c.execute("INSERT OR IGNORE INTO users VALUES ('admin', '8888', 'admin')")
    conn.commit()

init_db()

# --- 2. 專業計算工具 ---
def get_detailed_stats(name):
    """計算庫存、利潤、週轉率、銷售趨勢"""
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

    # 週轉率 (30天銷量 / 目前庫存)
    turnover = total_sold / (small_qty + 1)
    
    return {
        "qty": small_qty, "display": f"{small_qty // ratio} {big_u} {small_qty % ratio} {small_u}",
        "profit": profit, "is_alert": small_qty <= (alert or 0), "turnover": turnover,
        "ratio": ratio, "big_u": big_u, "small_u": small_u, "price": price, "cost": cost,
        "logs": logs_df
    }

# --- 3. 登入模組 ---
if "user" not in st.session_state:
    st.title("🛡️ 企業級智慧 ERP 登入")
    with st.container(border=True):
        u = st.text_input("帳號")
        p = st.text_input("密碼", type="password")
        if st.button("確認進入系統", use_container_width=True):
            c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
            res = c.fetchone()
            if res:
                st.session_state["user"], st.session_state["role"] = res[0], res[1]
                st.rerun()
            else: st.error("❌ 帳密錯誤")
    st.stop()

current_user, current_role = st.session_state["user"], st.session_state["role"]

# --- 4. 側邊導覽 ---
st.sidebar.title(f"👤 {current_user}")
st.sidebar.caption(f"權限：{current_role}")
menu = ["📊 營運數據總覽", "📝 進出貨自動登記", "🍎 商品檔案中心", "👥 使用者管理"]
if current_role != "admin": menu = ["📊 營運數據總覽", "📝 進出貨自動登記"]
choice = st.sidebar.selectbox("模組切換", menu)

if st.sidebar.button("🚪 登出"):
    st.session_state.clear(); st.rerun()

# --- 5. 功能實作 ---

if choice == "📊 營運數據總覽":
    st.subheader("📊 企業即時營運戰情室")
    
    # AI 智慧診斷與報表
    with st.expander("🤖 AI 智慧預測與報表工具", expanded=True):
        c1, c2, c3 = st.columns(3)
        if c1.button("✨ 執行 AI 庫存預測分析", use_container_width=True):
            with st.spinner("AI 正在預估未來補貨量..."):
                c.execute("SELECT name FROM products")
                inv_list = [f"{n}: {get_detailed_stats(n)['display']}" for (n,) in c.fetchall()]
                genai.configure(api_key=GEMINI_API_KEY)
                model = genai.GenerativeModel('gemini-1.5-flash')
                res = model.generate_content(f"基於以下庫存：{str(inv_list)}。請針對「下個月補貨量」給出具體建議及原因（繁中）。")
                st.info(res.text)
        
        # 銷售趨勢統計圖
        all_logs = pd.read_sql_query("SELECT date, type, (qty * price_at_time) as revenue FROM logs WHERE type='出貨'", conn)
        if not all_logs.empty:
            fig = px.line(all_logs, x='date', y='revenue', title="每日銷貨營收趨勢")
            st.plotly_chart(fig, use_container_width=True)

elif choice == "📝 進出貨自動登記":
    st.subheader("📝 智慧化進出貨")
    
    # 模擬條碼掃描
    c.execute("SELECT name, barcode FROM products")
    prods = c.fetchall()
    names = [r[0] for r in prods]
    codes = {r[1]: r[0] for r in prods if r[1]}
    
    scan_input = st.text_input("📷 條碼掃描 / 名稱關鍵字搜尋")
    final_target = codes.get(scan_input, scan_input if scan_input in names else None)
    
    target = st.selectbox("確認操作商品", names, index=names.index(final_target) if final_target else 0)
    
    if target:
        s = get_detailed_stats(target)
        st.write(f"💡 目前庫存：`{s['display']}` | 💰 累計利潤：`${s['profit']:,.0f}`")
        with st.form("trade_form", clear_on_submit=True):
            t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
            t_qty = st.number_input("數量", min_value=1)
            t_unit = st.selectbox("單位", [s["big_u"], s["small_u"]])
            t_price = st.number_input("成交單價", value=s["price"] if t_type=="出貨" else s["cost"])
            if st.form_submit_button("✅ 完成登記"):
                c.execute("INSERT INTO logs (name,type,qty,unit,price_at_time,date,operator) VALUES (?,?,?,?,?,?,?)",
                          (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d"), current_user))
                conn.commit(); st.success(f"{target} {t_type}成功！"); st.balloons()

elif choice == "🍎 商品檔案中心":
    st.subheader("🍎 商品檔案與條碼管理")
    c.execute("SELECT name FROM products")
    existing = ["+ 新增商品"] + [r for r in c.fetchall()]
    mode = st.selectbox("編輯對象", existing)
    
    with st.form("p_form"):
        p_name = st.text_input("商品名稱", value="" if mode=="+ 新增商品" else mode)
        p_code = st.text_input("條碼編號 (Barcode)")
        c1, c2 = st.columns(2)
        p_cost = c1.number_input("進成本(大)", min_value=0.0)
        p_price = c2.number_input("售單價(小)", min_value=0.0)
        c3, c4, c5 = st.columns(3)
        p_big, p_small, p_ratio = c3.text_input("大單位"), c4.text_input("小單位"), c5.number_input("換算比", min_value=1)
        p_alert = st.number_input("預警水位(小)", min_value=0)
        p_desc = st.text_area("產品描述")
        p_img = st.file_uploader("商品圖片", type=['jpg', 'png'])
        
        if st.form_submit_button("💾 儲存商品檔案"):
            img_b64 = ""
            if p_img:
                img = Image.open(p_img); img.thumbnail((300, 300))
                buf = io.BytesIO(); img.save(buf, format="JPEG"); img_b64 = base64.b64encode(buf.getvalue()).decode()
            
            if mode == "+ 新增商品":
                c.execute('''INSERT INTO products (name, barcode, cost, price, big_unit, small_unit, ratio, alert_level, image_data, description) 
                             VALUES (?,?,?,?,?,?,?,?,?,?)''', (p_name, p_code, p_cost, p_price, p_big, p_small, p_ratio, p_alert, img_b64, p_desc))
            else:
                c.execute('''UPDATE products SET barcode=?, cost=?, price=?, big_unit=?, small_unit=?, ratio=?, alert_level=?, image_data=?, description=? WHERE name=?''',
                          (p_code, p_cost, p_price, p_big, p_small, p_ratio, p_alert, img_b64, p_desc, mode))
            conn.commit(); st.success("商品檔案更新完成！"); st.rerun()

elif choice == "👥 使用者管理":
    st.subheader("👥 使用者管理")
    nu, np = st.text_input("帳號"), st.text_input("密碼", type="password")
    nr = st.selectbox("角色", ["staff", "admin"])
    if st.button("建立使用者"):
        try:
            c.execute("INSERT INTO users VALUES (?,?,?)", (nu, np, nr)); conn.commit(); st.success("建立成功")
        except: st.error("帳號重複")
    st.divider()
    users = pd.read_sql_query("SELECT username, role FROM users", conn)
    st.dataframe(users, use_container_width=True)
