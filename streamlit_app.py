import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 1. 介面美化 CSS (讓按鈕與字體更適合手機) ---
st.set_page_config(page_title="專業進銷存系統", layout="wide", page_icon="📦")
st.markdown("""
    <style>
    .stMetric { background-color: #f8f9fa; padding: 15px; border-radius: 10px; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
    .stButton>button { width: 100%; border-radius: 8px; }
    div[data-testid="stExpander"] { border: none; box-shadow: none; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 資料庫初始化 ---
conn = sqlite3.connect('business_pro_v13.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT UNIQUE, password TEXT, role TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS products 
             (name TEXT UNIQUE, cost REAL, price REAL, big_unit TEXT, small_unit TEXT, 
              ratio INTEGER, alert_level INTEGER, image_data TEXT, description TEXT, created_by TEXT, created_at TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS logs 
             (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, 
              price_at_time REAL, date TEXT, operator TEXT)''')
c.execute("INSERT OR IGNORE INTO users VALUES ('admin', '8888', 'admin')")
conn.commit()

# --- 3. 工具函數 ---
def image_to_base64(image_file):
    if image_file:
        try:
            img = Image.open(image_file); img.thumbnail((400, 400))
            buf = io.BytesIO(); img.save(buf, format="JPEG")
            return base64.b64encode(buf.getvalue()).decode()
        except: return None
    return None

def get_stock_and_profit(name):
    c.execute("SELECT big_unit, small_unit, ratio, cost, price FROM products WHERE name=?", (name,))
    p = c.fetchone()
    if not p: return 0, 0, "無資料", 1
    big_u, small_u, ratio, cost, price = p
    c.execute("SELECT type, qty, unit, price_at_time FROM logs WHERE name=?", (name,))
    logs = c.fetchall()
    t_small_qty, t_profit, u_cost = 0, 0, (cost / ratio if ratio > 0 else 0)
    for t, q, u, p_at in logs:
        real_q = q * ratio if u == big_u else q
        if t == '進貨': t_small_qty += real_q
        else:
            t_small_qty -= real_q
            t_profit += (q * p_at) - (real_q * u_cost)
    display_stock = f"{t_small_qty // ratio} {big_u} {t_small_qty % ratio} {small_u}"
    return t_small_qty, t_profit, display_stock, ratio

# --- 4. 登入系統 ---
if "user" not in st.session_state:
    st.title("🔒 企業進銷存登入")
    u = st.text_input("帳號")
    p = st.text_input("密碼", type="password")
    if st.button("確認進入系統"):
        c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
        res = c.fetchone()
        if res:
            st.session_state["user"], st.session_state["role"] = res, res
            st.rerun()
        else: st.error("❌ 帳密錯誤")
    st.stop()

current_user, current_role = st.session_state["user"], st.session_state["role"]

# --- 5. 側邊欄 ---
st.sidebar.title(f"👤 {current_user}")
if st.sidebar.button("🚪 登出系統"):
    del st.session_state["user"]; st.rerun()

menu = ["📊 庫存報表與分析", "📝 進出貨登記"]
if current_role == "admin": menu.append("🍎 商品設定維護")
choice = st.sidebar.selectbox("主要功能選單", menu)

# --- 💡 關鍵：Popover 快速選單 (模擬圖片中的➕號功能) ---
def quick_action_menu():
    with st.popover("➕ 快速操作選單"):
        st.write("### 🛠️ 多功能工具")
        # 簡易計算機
        calc = st.text_input("🧮 計算機 (如: 500*12)")
        if calc:
            try: st.success(f"結果: {eval(calc.replace('x', '*').replace('÷', '/'))}")
            except: pass
        
        st.divider()
        # 數據匯出 (僅管理員可見)
        if current_role == "admin":
            st.write("📊 數據匯出")
            h_df = pd.read_sql_query("SELECT * FROM logs", conn)
            st.download_button("📥 下載交易報表 (CSV)", h_df.to_csv(index=False).encode('utf-8-sig'), "report.csv", "text/csv")
        
        # 盤點鎖定開關
        if current_role == "admin":
            st.session_state.is_locked = st.toggle("🔒 開啟盤點鎖定", value=st.session_state.get('is_locked', False))

# --- 功能 1：報表與圖表 ---
if choice == "📊 庫存報表與分析":
    st.subheader("📦 即時庫存報表")
    quick_action_menu()
    c.execute("SELECT name, image_data, description FROM products")
    prods = c.fetchall()
    if prods:
        all_p, profit_data = 0, []
        cols = st.columns(2 if st.sidebar.checkbox("手機模式", True) else 4)
        for idx, (n, img, desc) in enumerate(prods):
            sq, prof, ds, _ = get_stock_and_profit(n)
            all_p += prof
            profit_data.append({"品項": n, "毛利": prof})
            with cols[idx % len(cols)]:
                if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                st.markdown(f"**{n}**\n庫存：{ds}")
                if desc: st.caption(f"備註: {desc}")
                st.divider()
        if current_role == "admin":
            st.sidebar.metric("總累計毛利", f"${all_p:,.0f} TW$")
            st.subheader("📈 銷售獲利分析")
            st.bar_chart(pd.DataFrame(profit_data).set_index("品項"))

# --- 功能 2：登記 (支援原生掃描與連動) ---
elif choice == "📝 進出貨登記":
    st.subheader("📝 登記進銷貨")
    quick_action_menu()
    
    if st.session_state.get('is_locked', False):
        st.error("🛑 系統盤點鎖定中，目前僅供查看。")
    else:
        c.execute("SELECT name FROM products")
        names_list = [r for r in c.fetchall()]
        if not names_list:
            st.warning("⚠️ 請先建檔。")
        else:
            scan_input = st.text_input("📷 點此掃描或搜尋品項", key="barcode_scan")
            default_idx = names_list.index(scan_input) if scan_input in names_list else 0
            target = st.selectbox("請選擇品項", options=names_list, index=default_idx)
            
            if target:
                sq, _, ds, _ = get_stock_and_profit(target)
                st.info(f"💡 目前庫存：{ds}")
                c.execute("SELECT big_unit, small_unit FROM products WHERE name=?", (target,))
                units = c.fetchone()
                
                with st.form("trade"):
                    t_type = st.radio("交易類型", ["進貨", "出貨"], horizontal=True)
                    c1, c2 = st.columns(2)
                    with c1: qty = st.number_input("數量", min_value=1, step=1)
                    with c2: unit = st.selectbox("單位", options=list(units))
                    price = st.number_input("成交單價", min_value=0.0)
                    if st.form_submit_button("確認提交"):
                        # 負庫存檢查
                        c.execute("SELECT ratio FROM products WHERE name=?", (target,))
                        ratio = c.fetchone()
                        tx_qty = qty * ratio if unit == units else qty
                        if t_type == "出貨" and tx_qty > sq:
                            st.error(f"❌ 庫存不足！剩餘 {sq}")
                        else:
                            c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                                      (target, t_type, qty, unit, price, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                            conn.commit(); st.success("✅ 登記成功！"); st.balloons()

# --- 功能 3：商品設定 (含編輯與自動定價) ---
elif choice == "🍎 商品設定維護":
    st.subheader("🍎 商品建檔與維護")
    quick_action_menu()
    c.execute("SELECT name FROM products")
    exists = ["+ 新增商品"] + [r for r in c.fetchall()]
    mode = st.selectbox("選擇操作對象", exists)
    iv = {"n":"","c":0.0,"p":0.0,"bu":"箱","su":"顆","r":10,"d":"","img":None}
    if mode != "+ 新增商品":
        c.execute("SELECT * FROM products WHERE name=?", (mode,))
        p = c.fetchone()
        if p: iv = {"n":p,"c":p,"p":p,"bu":p,"su":p,"r":p,"a":p,"img":p,"d":p}

    n = st.text_input("商品名稱/條碼", value=iv["n"])
    col1, col2 = st.columns(2)
    with col1: cost = st.number_input("整箱成本", value=iv["cost"])
    with col2: ratio = st.number_input("換算率", min_value=1, value=iv["r"])
    margin = st.slider("預設毛利率 (%)", 0, 100, 30)
    suggested = (cost/ratio) * (1 + margin/100) if ratio > 0 else 0
    price = st.number_input("建議售價", value=float(iv["p"] if mode != "+ 新增商品" else suggested))

    with st.form("prod"):
        b_u, s_u = st.text_input("大單位", value=iv["bu"]), st.text_input("小單位", value=iv["su"])
        desc = st.text_area("詳細敘述", value=iv["d"])
        cam = st.camera_input("商品拍照")
        if st.form_submit_button("儲存資料"):
            final_img = image_to_base64(cam) if cam else iv["img"]
            c.execute("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (n, cost, price, b_u, s_u, ratio, 5, final_img, desc, current_user, datetime.now().strftime("%Y-%m-%d")))
            conn.commit(); st.success("🎉 商品資料已同步！"); st.rerun()
