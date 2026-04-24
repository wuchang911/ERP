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

# --- 1. 系統初始化 (iOS/PWA 優化) ---
st.set_page_config(page_title="AI 智慧 ERP", layout="wide", initial_sidebar_state="collapsed")

# 鎖定 API Key
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

# 資料庫連線 (使用 v2 版本確保結構同步)
conn = sqlite3.connect('erp_master_v2.db', check_same_thread=False)
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
    total_qty, profit = 0, 0
    u_cost = (cost / ratio if ratio > 0 else 0)
    
    for _, row in logs_df.iterrows():
        real_q = row['qty'] * ratio if row['unit'] == big_u else row['qty']
        if '進貨' in row['type'] or '盤點(進貨)' in row['type']: 
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
    p.drawString(50, 800, f"Inventory Report - {datetime.now().strftime('%Y-%m-%d')}")
    y = 770
    c.execute("SELECT name FROM products")
    for (n,) in c.fetchall():
        s = get_detailed_stats(n)
        p.drawString(50, y, f"Prod: {n} | Stock: {s['display']} | Profit: ${s['profit']:,.0f}")
        y -= 20
    p.save(); buf.seek(0); return buf

# --- 3. 登入系統 ---
if "user" not in st.session_state:
    st.title("🔐 AI 智慧 ERP")
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

current_user, current_role = st.session_state["user"], st.session_state["role"]

# --- 4. 導覽選單 ---
st.sidebar.markdown(f"👤 使用者: **{current_user}**")
menu = ["庫存報表", "交易登記", "歷史紀錄"]
if current_role == "admin":
    menu += ["商品管理", "帳號管理"]
choice = st.sidebar.selectbox("切換功能", menu)
if st.sidebar.button("登出系統"):
    st.session_state.clear(); st.rerun()

# --- 5. 各模組邏輯 ---
if choice == "庫存報表":
    st.subheader("📦 庫存狀態")
    if current_role == "admin":
        with st.expander("🛠️ 管理工具"):
            if st.button("🤖 AI 診斷庫存", use_container_width=True):
                with st.spinner("AI 分析中..."):
                    c.execute("SELECT name FROM products")
                    inv = [f"{n}: {get_detailed_stats(n)['display']}" for (n,) in c.fetchall()]
                    if GEMINI_API_KEY:
                        try:
                            genai.configure(api_key=GEMINI_API_KEY)
                            model = genai.GenerativeModel('gemini-1.5-flash')
                            res = model.generate_content(f"庫存:{str(inv)}。請給3點補貨建議(繁中)。")
                            st.info(res.text)
                        except: st.error("AI 連線失敗")
            st.download_button("📄 匯出 PDF 報表", generate_pdf(), "report.pdf", use_container_width=True)

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
                    if s["is_alert"]: st.error(f"⚠️ 預警: {s['display']}")
                    else: st.success(f"庫存: {s['display']}")
                    st.caption(f"預估獲利: ${s['profit']:,.0f}")

elif choice == "交易登記":
    st.subheader("📝 庫存異動")
    c.execute("SELECT name, barcode FROM products")
    prods = c.fetchall()
    scan = st.text_input("🔍 搜尋品項或掃描條碼")
    matched = next((n for n, b in prods if scan and (scan in n or scan == b)), None)
    names = [p[0] for p in prods]
    
    if names:
        target = st.selectbox("選定商品", names, index=names.index(matched) if matched else 0)
        s = get_detailed_stats(target)
        st.info(f"當前庫存：{s['display']}")
        
        tab_list = ["🛒 一般進出貨", "🔒 盤點鎖定"] if current_role == "admin" else ["🛒 一般進出貨"]
        tabs = st.tabs(tab_list)
        
        with tabs[0]:
            with st.form("trade", clear_on_submit=True):
                t_type = st.radio("交易類型", ["進貨", "出貨"], horizontal=True)
                t_unit = st.selectbox("使用單位", [s["big_u"], s["small_u"]])
                t_qty = st.number_input("數量", min_value=1, value=1)
                t_price = st.number_input("成交單價", value=s["price"] if t_type=="出貨" else s["cost"])
                if st.form_submit_button("確認提交", use_container_width=True):
                    op_qty = t_qty * s["ratio"] if t_unit == s["big_u"] else t_qty
                    if t_type == "出貨" and op_qty > s["qty"]:
                        st.error("庫存不足")
                    else:
                        c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                                  (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                        conn.commit(); st.success("登記完成"); st.rerun()
        
        if current_role == "admin":
            with tabs[1]:
                st.warning("盤點將直接校正庫存數量。")
                with st.form("stock_take"):
                    nb = st.number_input(f"現場數量({s['big_u']})", min_value=0, step=1)
                    nu = st.number_input(f"現場餘數({s['small_u']})", min_value=0, step=1)
                    confirm = st.checkbox("確認數據無誤")
                    if st.form_submit_button("🔒 執行盤點校正", use_container_width=True):
                        if confirm:
                            diff = (nb * s["ratio"] + nu) - s["qty"]
                            if diff != 0:
                                adjust_type = f"盤點({'進貨' if diff>0 else '出貨'})"
                                c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                                          (target, adjust_type, abs(diff), s['small_u'], 0, datetime.now().strftime("%Y-%m-%d %H:%M"), f"ADMIN:{current_user}"))
                                conn.commit(); st.success("校正完成"); st.rerun()
                            else: st.info("數量一致，無需校正")
                        else: st.error("請勾選確認方塊")

elif choice == "歷史紀錄":
    st.subheader("📜 交易流水帳")
    logs_df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC LIMIT 100", conn)
    if not logs_df.empty:
        for i, row in logs_df.iterrows():
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.markdown(f"**{row['name']}** ({row['type']})")
                c1.caption(f"{row['date']} | 操作者: {row['operator']}")
                c2.write(f"{row['qty']} {row['unit']}")
                if current_role == "admin":
                    if c3.button("🗑️ 刪除", key=f"dl_{row['id']}", use_container_width=True):
                        c.execute("DELETE FROM logs WHERE id=?", (row['id'],))
                        conn.commit(); st.rerun()
    else: st.info("尚無紀錄")

elif choice == "商品管理":
    st.subheader("⚙️ 商品建檔管理")
    c.execute("SELECT name FROM products")
    existing = ["+ 新增商品"] + [r[0] for r in c.fetchall()]
    mode = st.selectbox("編輯對象", existing)
    
    with st.form("p_form"):
        p_name = st.text_input("商品名稱", value="" if mode=="+ 新增商品" else mode)
        p_barcode = st.text_input("條碼/簡碼")
        col_m1, col_m2 = st.columns(2)
        p_cost = col_m1.number_input("預設進價(大單位)", min_value=0.0)
        p_price = col_m2.number_input("預設售價(小單位)", min_value=0.0)
        c1, c2, c3 = st.columns(3)
        p_big, p_small, p_ratio = c1.text_input("大單位"), c2.text_input("小單位"), c3.number_input("換算比", min_value=1)
        p_img = st.file_uploader("商品圖片", type=['jpg', 'png'])
        if st.form_submit_button("💾 儲存資訊", use_container_width=True):
            b64 = ""
            if p_img:
                img = Image.open(p_img).convert("RGB")
                img.thumbnail((300, 300))
                buf = io.BytesIO(); img.save(buf, format="JPEG"); b64 = base64.b64encode(buf.getvalue()).decode()
            if mode == "+ 新增商品":
                c.execute("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?)", (p_name, p_barcode, p_cost, p_price, p_big, p_small, p_ratio, 5, b64, ""))
            else:
                c.execute("UPDATE products SET barcode=?, cost=?, price=?, big_unit=?, small_unit=?, ratio=?, image_data=? WHERE name=?", (p_barcode, p_cost, p_price, p_big, p_small, p_ratio, b64, mode))
            conn.commit(); st.success("商品資料已更新"); st.rerun()

    if mode != "+ 新增商品" and st.button("🗑️ 刪除此商品", use_container_width=True):
        c.execute("DELETE FROM products WHERE name=?", (mode,))
        conn.commit(); st.rerun()

elif choice == "帳號管理":
    st.subheader("👥 系統帳號管理")
    with st.expander("➕ 新增工作人員"):
        with st.form("add_u"):
            nu, np, nr = st.text_input("帳號名稱"), st.text_input("登入密碼"), st.selectbox("權限", ["staff", "admin"])
            if st.form_submit_button("確認新增"):
                try:
                    c.execute("INSERT INTO users VALUES (?,?,?)", (nu, np, nr))
                    conn.commit(); st.success("新增成功"); st.rerun()
                except: st.error("帳號名稱已存在")
    
    st.divider()
    users = pd.read_sql_query("SELECT username, role FROM users", conn)
    for i, r in users.iterrows():
        col1, col2 = st.columns([3, 1])
        col1.write(f"👤 {r['username']} ({r['role']})")
        if r['username'] != current_user:
            if col2.button("刪除", key=f"du_{i}", use_container_width=True):
                c.execute("DELETE FROM users WHERE username=?", (r['username'],))
                conn.commit(); st.rerun()
        else: col2.caption("登入中")
