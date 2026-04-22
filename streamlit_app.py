import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 0. 登入驗證 (密碼: 8888) ---
def check_password():
    if "password_correct" not in st.session_state:
        st.title("🔒 企業管理系統登入")
        pwd = st.text_input("請輸入進入密碼", type="password")
        if st.button("登入"):
            if pwd == "8888":
                st.session_state["password_correct"] = True
                st.rerun()
            else: st.error("❌ 密碼錯誤")
        return False
    return True

if not check_password():
    st.stop()

# --- 1. 資料庫初始化 ---
conn = sqlite3.connect('business_pro_v5.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS products 
             (name TEXT UNIQUE, cost REAL, price REAL, big_unit TEXT, small_unit TEXT, 
              ratio INTEGER, alert_level INTEGER, image_data TEXT, description TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS logs 
             (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, price_at_time REAL, date TEXT)''')
conn.commit()

# --- 2. 工具函數 ---
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
    total_small_qty = 0
    total_profit = 0
    small_unit_cost = cost / ratio
    
    for t, q, u, p_at_time in logs:
        tx_small_qty = q * ratio if u == big_u else q
        if t == '進貨':
            total_small_qty += tx_small_qty
        else:
            total_small_qty -= tx_small_qty
            tx_revenue = q * p_at_time
            total_profit += tx_revenue - (tx_small_qty * small_unit_cost)

    display_stock = f"{total_small_qty // ratio} {big_u} {total_small_qty % ratio} {small_u}"
    return total_small_qty, total_profit, display_stock, ratio

# --- 3. 側邊欄 ---
st.sidebar.title("🏢 企業管理系統")
calc_exp = st.sidebar.text_input("🧮 簡易計算機")
if calc_exp:
    try:
        res = eval(calc_exp.replace('x', '*').replace('÷', '/'), {"__builtins__": None}, {})
        st.sidebar.success(f"結果: {res}")
    except: st.sidebar.caption("格式錯誤")

st.sidebar.divider()
if st.sidebar.button("登出系統"):
    del st.session_state["password_correct"]; st.rerun()

menu = ["📊 即時庫存與報表", "📝 進出貨登記", "🍎 商品設定"]
choice = st.sidebar.selectbox("切換功能", menu)

# --- 功能 1：庫存與報表 ---
if choice == "📊 即時庫存與報表":
    st.subheader("📦 精確庫存監控")
    c.execute("SELECT name, image_data, alert_level, description FROM products")
    prods = c.fetchall()
    
    if not prods:
        st.info("💡 請先前往『商品設定』。")
    else:
        all_profit = 0
        cols = st.columns(2 if st.sidebar.checkbox("手機模式", True) else 4)
        for idx, (name, img, alert, desc) in enumerate(prods):
            small_qty, profit, display_stock, ratio = get_stock_and_profit(name)
            all_profit += profit
            with cols[idx % len(cols)]:
                if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                color = "#FF4B4B" if small_qty <= alert else "#00A000"
                st.markdown(f"**{name}**")
                st.markdown(f"庫存：<span style='color:{color};font-weight:bold;'>{display_stock}</span>", unsafe_allow_html=True)
                if desc:
                    with st.expander("📝 敘述"): st.write(desc)
                st.divider()
        st.sidebar.metric("總累計毛利", f"${all_profit:,.0f} TW$")

        st.subheader("📜 歷史紀錄與匯出")
        history_df = pd.read_sql_query("SELECT name, type, qty, unit, price_at_time, date FROM logs ORDER BY id DESC LIMIT 50", conn)
        st.dataframe(history_df, use_container_width=True)
        csv = history_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下載明細 (CSV)", data=csv, file_name="history.csv", mime='text/csv')

# --- 功能 2：進出貨登記 ---
elif choice == "📝 進出貨登記":
    st.subheader("📝 進銷貨登記")
    c.execute("SELECT name, big_unit, small_unit FROM products")
    items = c.fetchall()
    if not items: st.warning("請先設定商品")
    else:
        t_data = st.selectbox("品項名稱", options=items, format_func=lambda x: x[0])
        with st.form("trade"):
            t_type = st.radio("交易類型", ["進貨", "出貨"], horizontal=True)
            current_s, _, current_d, _ = get_stock_and_profit(t_data[0])
            st.info(f"💡 目前庫存：{current_d}")
            colq, colu = st.columns(2)
            with colq: t_qty = st.number_input("數量", min_value=1, step=1)
            with colu: t_unit = st.selectbox("單位", options=[t_data[1], t_data[2]])
            t_price = st.number_input("此筆交易單價 (TW$)", min_value=0.0, value=100.0)
            t_date = st.date_input("日期", datetime.now())
            if st.form_submit_button("提交"):
                c.execute("SELECT ratio FROM products WHERE name=?", (t_data[0],))
                ratio = c.fetchone()[0]
                tx_small_qty = t_qty * ratio if t_unit == t_data[1] else t_qty
                if t_type == "出貨" and tx_small_qty > current_s:
                    st.error(f"❌ 庫存不足！現有 {current_s}")
                else:
                    c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date) VALUES (?,?,?,?,?,?)", 
                              (t_data[0], t_type, t_qty, t_unit, t_price, t_date.strftime("%Y/%m/%d")))
                    conn.commit(); st.success("✅ 登記完成"); st.balloons()

# --- 功能 3：商品設定 (含自動定價) ---
elif choice == "🍎 商品設定":
    st.subheader("🍎 商品換算與自動定價")
    c.execute("SELECT name FROM products")
    existing = [r[0] for r in c.fetchall()]
    name = st.text_input("商品名稱")
    if name in existing: st.warning("⚠️ 已存在，儲存將覆蓋。")
    
    col_u1, col_u2, col_r = st.columns(3)
    with col_u1: b_u = st.text_input("大單位", value="箱")
    with col_u2: s_u = st.text_input("最小單位", value="顆")
    with col_r: ratio = st.number_input(f"換算率 (一{b_u}有幾{s_u})", min_value=1, value=10)

    col_c, col_p = st.columns(2)
    with col_c: cost = st.number_input(f"整{b_u}進貨總成本 ($)", min_value=0.0)
    unit_cost = cost / ratio if ratio > 0 else 0
    st.caption(f"💡 系統計算：單{s_u}成本為 ${unit_cost:.2f}")

    with col_p:
        margin = st.slider("預設毛利率 (%)", 0, 100, 30)
        suggested_price = unit_cost * (1 + margin/100)
        price = st.number_input(f"單一{s_u}銷售售價 ($)", min_value=0.0, value=float(round(suggested_price, 1)))

    with st.form("prod_init"):
        alert = st.number_input(f"低庫存預警 (以{s_u}計)", min_value=0, value=5)
        desc = st.text_area("詳細敘述")
        img = st.camera_input("拍照")
        if st.form_submit_button("儲存商品"):
            if not name: st.error("❌ 請輸入名稱")
            else:
                c.execute("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?)",
                          (name, cost, price, b_u, s_u, ratio, alert, image_to_base64(img), desc))
                conn.commit(); st.success("🎉 設定成功！")
