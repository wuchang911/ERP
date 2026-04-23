import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 1. 介面與資料庫設定 ---
st.set_page_config(page_title="專業雲端進銷存", layout="wide", page_icon="📦")
conn = sqlite3.connect('business_v14.db', check_same_thread=False)
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

# --- 2. 登入邏輯 ---
if "user" not in st.session_state:
    st.title("🔒 企業進銷存系統")
    u = st.text_input("帳號")
    p = st.text_input("密碼", type="password")
    if st.button("確認進入"):
        c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
        res = c.fetchone()
        if res:
            st.session_state["user"], st.session_state["role"] = res, res
            st.rerun()
        else: st.error("❌ 密碼錯誤")
    st.stop()

current_user, current_role = st.session_state["user"], st.session_state["role"]

# --- 3. 核心功能函數 ---
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
    return t_small_qty, t_profit, f"{t_small_qty // ratio} {big_u} {t_small_qty % ratio} {small_u}", ratio

# --- 4. 💡 修正後的「➕ 快速操作系統」 (確保不跑掉) ---
def quick_action_section():
    with st.popover("➕ 快速操作 (工具/匯出/鎖定)"):
        st.markdown("### 🛠️ 快速工具")
        # 側邊計算機
        calc = st.text_input("🧮 簡易計算", placeholder="如: 1200/12")
        if calc:
            try: st.success(f"結果: {eval(calc.replace('x', '*').replace('÷', '/'))}")
            except: pass
            
        st.divider()
        if current_role == "admin":
            st.subheader("⚙️ 管理員選單")
            # 盤點鎖定
            st.session_state.is_locked = st.toggle("🔒 盤點鎖定開關", value=st.session_state.get('is_locked', False))
            # 匯出報表
            h_df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC", conn)
            st.download_button("📥 匯出明細 (CSV)", h_df.to_csv(index=False).encode('utf-8-sig'), "report.csv", "text/csv")
            # 清除紀錄
            if st.checkbox("🔥 清除交易紀錄"):
                if st.button("確認清空"):
                    c.execute("DELETE FROM logs"); conn.commit(); st.rerun()
        else:
            st.info("員工權限：僅供使用計算機")

# --- 5. 主導覽與分流 ---
st.sidebar.title(f"👤 {current_user}")
if st.sidebar.button("🚪 登出"):
    del st.session_state["user"]; st.rerun()

menu = ["📊 庫存報表", "📝 進出貨登記"]
if current_role == "admin": menu.append("🍎 商品設定")
choice = st.sidebar.selectbox("選單", menu)

# --- 頁面執行 ---
if choice == "📊 庫存報表":
    st.subheader("📦 即時庫存報表")
    quick_action_section() # 放置於頁面頂部
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
                st.divider()
        if current_role == "admin":
            st.sidebar.metric("總預估毛利", f"${all_p:,.0f}")
            st.bar_chart(pd.DataFrame(profit_data).set_index("品項"))

elif choice == "📝 進出貨登記":
    st.subheader("📝 登記進銷貨")
    quick_action_section() # 放置於頁面頂部
    if st.session_state.get('is_locked', False):
        st.error("🛑 系統盤點鎖定中")
    else:
        c.execute("SELECT name FROM products")
        names = [r for r in c.fetchall()]
        if names:
            scan_input = st.text_input("📷 掃描/搜尋", key="scan")
            idx = names.index(scan_input) if scan_input in names else 0
            target = st.selectbox("品項選擇", options=names, index=idx)
            if target:
                sq, _, ds, _ = get_stock_and_profit(target)
                st.info(f"💡 目前庫存：{ds}")
                c.execute("SELECT big_unit, small_unit FROM products WHERE name=?", (target,))
                units = c.fetchone()
                with st.form("trade"):
                    t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
                    t_qty = st.number_input("數量", min_value=1)
                    t_unit = st.selectbox("單位", units)
                    t_price = st.number_input("單價")
                    if st.form_submit_button("確認提交"):
                        c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                                  (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                        conn.commit(); st.success("成功"); st.balloons()

elif choice == "🍎 商品設定":
    st.subheader("🍎 商品維護")
    quick_action_section()
    # ... (商品維護邏輯與之前相同，確保 INSERT OR REPLACE 正常運作) ...
