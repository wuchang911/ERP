import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 1. 介面與資料庫初始化 ---
st.set_page_config(page_title="專業進銷存系統", layout="wide", page_icon="📦")

conn = sqlite3.connect('business_v15.db', check_same_thread=False)
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

# --- 2. 工具函數 (照片、庫存、毛利) ---
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

# --- 3. 登入系統 ---
if "user" not in st.session_state:
    st.title("🔒 企業進銷存登入")
    u = st.text_input("帳號")
    p = st.text_input("密碼", type="password")
    if st.button("登入系統"):
        c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
        res = c.fetchone()
        if res:
            st.session_state["user"], st.session_state["role"] = res[0], res[1]
            st.rerun()
        else: st.error("帳密錯誤")
    st.stop()

current_user, current_role = st.session_state["user"], st.session_state["role"]

# --- 4. ➕ 快速操作選單 (Popover) ---
def quick_action_menu():
    with st.popover("➕ 快速操作"):
        calc = st.text_input("🧮 計算機 (如: 500*1.05)")
        if calc:
            try: st.success(f"結果: {eval(calc.replace('x', '*').replace('÷', '/'))}")
            except: pass
        st.divider()
        if current_role == "admin":
            st.subheader("⚙️ 管理工具")
            st.session_state.is_locked = st.toggle("🔒 盤點鎖定開關", value=st.session_state.get('is_locked', False))
            h_df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC", conn)
            st.download_button("📥 匯出明細 (CSV)", h_df.to_csv(index=False).encode('utf-8-sig'), "history.csv", "text/csv")
            with st.expander("👤 帳號管理"):
                new_u = st.text_input("新增帳號")
                new_p = st.text_input("密碼", type="password")
                if st.button("建立員工"):
                    c.execute("INSERT OR REPLACE INTO users VALUES (?,?,'staff')", (new_u, new_p))
                    conn.commit(); st.success(f"已建立 {new_u}")
            if st.checkbox("🔥 清除紀錄"):
                if st.button("執行清空歷史"):
                    c.execute("DELETE FROM logs"); conn.commit(); st.rerun()

# --- 5. 主選單功能 ---
st.sidebar.title(f"👤 {current_user}")
if st.sidebar.button("🚪 登出"):
    del st.session_state["user"]; st.rerun()

menu = ["📊 報表與分析", "📝 進出貨登記"]
if current_role == "admin": menu.append("🍎 商品維護設定")
choice = st.sidebar.selectbox("切換功能", menu)

# --- 功能 1：報表與追溯 ---
if choice == "📊 報表與分析":
    st.subheader("📦 即時庫存監控")
    quick_action_menu()
    c.execute("SELECT name, image_data, description, created_by FROM products")
    prods = c.fetchall()
    if prods:
        all_p, profit_data = 0, []
        cols = st.columns(2 if st.sidebar.checkbox("手機模式", True) else 4)
        for idx, (n, img, desc, creator) in enumerate(prods):
            sq, prof, ds, _ = get_stock_and_profit(n)
            all_p += prof
            profit_data.append({"品項": n, "毛利": prof})
            with cols[idx % len(cols)]:
                if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                st.markdown(f"**{n}**\n庫存：{ds}")
                if desc: st.caption(f"備註: {desc}")
                st.divider()
        if current_role == "admin":
            st.sidebar.metric("總預估毛利", f"${all_p:,.0f}")
            st.subheader("📈 銷售獲利圖表")
            st.bar_chart(pd.DataFrame(profit_data).set_index("品項"))
    
    st.subheader("📜 最近 50 筆歷史明細")
    h_df = pd.read_sql_query("SELECT name, type, qty, unit, operator, date FROM logs ORDER BY id DESC LIMIT 50", conn)
    st.dataframe(h_df, use_container_width=True)

# --- 功能 2：登記 (含掃描連動與負庫存阻斷) ---
elif choice == "📝 進出貨登記":
    st.subheader("📝 登記進銷貨")
    quick_action_menu()
    if st.session_state.get('is_locked', False):
        st.error("🛑 系統盤點鎖定中")
    else:
        c.execute("SELECT name FROM products")
        names = [r[0] for r in c.fetchall()]
        if not names: st.warning("請先建檔")
        else:
            scan = st.text_input("📷 掃描/搜尋", key="scan")
            idx = names.index(scan) if scan in names else 0
            target = st.selectbox("品項選擇", options=names, index=idx)
            if target:
                sq, _, ds, _ = get_stock_and_profit(target)
                st.info(f"💡 目前庫存：{ds}")
                c.execute("SELECT big_unit, small_unit, ratio FROM products WHERE name=?", (target,))
                b_u, s_u, ratio = c.fetchone()
                with st.form("trade"):
                    t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
                    t_qty = st.number_input("數量", min_value=1, step=1)
                    t_unit = st.selectbox("單位", [b_u, s_u])
                    t_price = st.number_input("單價", min_value=0.0)
                    if st.form_submit_button("確認提交"):
                        tx_sq = t_qty * ratio if t_unit == b_u else t_qty
                        if t_type == "出貨" and tx_sq > sq:
                            st.error(f"❌ 庫存不足！剩餘 {sq}")
                        else:
                            c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                                      (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                            conn.commit(); st.success("✅ 成功"); st.balloons()

# --- 功能 3：設定 (含智慧編輯與定價) ---
elif choice == "🍎 商品維護設定":
    st.subheader("🍎 商品資料維護")
    quick_action_menu()
    c.execute("SELECT name FROM products")
    exists = ["+ 新增商品"] + [r[0] for r in c.fetchall()]
    mode = st.selectbox("編輯對象", exists)
    iv = {"n":"","c":0.0,"p":0.0,"bu":"箱","su":"顆","r":10,"d":"","img":None,"a":5}
    if mode != "+ 新增商品":
        c.execute("SELECT * FROM products WHERE name=?", (mode,))
        p = c.fetchone()
        if p: iv = {"n":p[0],"c":p[1],"p":p[2],"bu":p[3],"su":p[4],"r":p[5],"a":p[6],"img":p[7],"d":p[8]}

    name = st.text_input("名稱/條碼", value=iv["n"])
    if mode == "+ 新增商品" and name in exists: st.warning("⚠️ 此名稱已存在，儲存將覆蓋。")
    
    col1, col2, col3 = st.columns(3)
    with col1: b_u = st.text_input("大單位", value=iv["bu"])
    with col2: s_u = st.text_input("小單位", value=iv["su"])
    with col3: ratio = st.number_input("換算率", min_value=1, value=iv["r"])
    
    col_c, col_p = st.columns(2)
    with col_c: cost = st.number_input("整箱成本", value=iv["c"])
    with col_p:
        margin = st.slider("毛利率 (%)", 0, 100, 30)
        suggested = (cost/ratio) * (1 + margin/100) if ratio > 0 else 0
        price = st.number_input("單顆售價", value=float(iv["p"] if mode != "+ 新增商品" else suggested))

    with st.form("prod"):
        desc = st.text_area("詳細敘述", value=iv["d"])
        alert = st.number_input("預警水位", value=iv["a"])
        cam = st.camera_input("拍照")
        if st.form_submit_button("儲存資料"):
            final_img = image_to_base64(cam) if cam else iv["img"]
            c.execute("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (name, cost, price, b_u, s_u, ratio, alert, final_img, desc, current_user, datetime.now().strftime("%Y-%m-%d")))
            conn.commit(); st.success("🎉 已同步"); st.rerun()
