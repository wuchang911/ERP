import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 0. 登入驗證 (密碼: 8888) ---
if "password_correct" not in st.session_state:
    st.title("🔒 企業管理系統登入")
    pwd = st.text_input("請輸入進入密碼", type="password")
    if st.button("登入"):
        if pwd == "8888":
            st.session_state["password_correct"] = True
            st.rerun()
        else: st.error("❌ 密碼錯誤")
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
    total_small_qty, total_profit, small_unit_cost = 0, 0, cost / ratio
    for t, q, u, p_at_time in logs:
        tx_small_qty = q * ratio if u == big_u else q
        if t == '進貨': total_small_qty += tx_small_qty
        else:
            total_small_qty -= tx_small_qty
            total_profit += (q * p_at_time) - (tx_small_qty * small_unit_cost)
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

# --- 新增：資料管理中心 (清除功能) ---
with st.sidebar.expander("🛠️ 資料管理中心"):
    st.warning("以下操作不可逆")
    if st.checkbox("確認要清空所有交易歷史"):
        if st.button("🔥 立即執行清空紀錄"):
            c.execute("DELETE FROM logs")
            conn.commit()
            st.success("紀錄已全數清空"); st.rerun()
    
    st.write("---")
    c.execute("SELECT name FROM products")
    p_to_del = st.selectbox("選擇要刪除的商品", ["請選擇"] + [r[0] for r in c.fetchall()])
    if p_to_del != "請選擇":
        if st.checkbox(f"確認刪除 {p_to_del}"):
            if st.button("🗑️ 刪除該商品及紀錄"):
                c.execute("DELETE FROM products WHERE name=?", (p_to_del,))
                c.execute("DELETE FROM logs WHERE name=?", (p_to_del,))
                conn.commit()
                st.success("商品已刪除"); st.rerun()

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
    if not prods: st.info("💡 目前尚無資料。")
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
        t_data_tuple = st.selectbox("品項名稱", options=items, format_func=lambda x: x[0])
        t_name = t_data_tuple[0]
        with st.form("trade"):
            t_type = st.radio("交易類型", ["進貨", "出貨"], horizontal=True)
            current_s, _, current_d, _ = get_stock_and_profit(t_name)
            st.info(f"💡 目前庫存：{current_d}")
            colq, colu = st.columns(2)
            with colq: t_qty = st.number_input("數量", min_value=1, step=1)
            with colu: t_unit = st.selectbox("單位", options=[t_data_tuple[1], t_data_tuple[2]])
            t_price = st.number_input("此筆交易單價 (TW$)", min_value=0.0, value=100.0)
            t_date = st.date_input("日期", datetime.now())
            if st.form_submit_button("提交"):
                c.execute("SELECT ratio FROM products WHERE name=?", (t_name,))
                ratio = c.fetchone()[0]
                tx_small_qty = t_qty * ratio if t_unit == t_data_tuple[1] else t_qty
                if t_type == "出貨" and tx_small_qty > current_s: st.error(f"❌ 庫存不足！")
                else:
                    c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date) VALUES (?,?,?,?,?,?)", 
                              (t_name, t_type, t_qty, t_unit, t_price, t_date.strftime("%Y/%m/%d")))
                    conn.commit(); st.success("✅ 登記完成"); st.balloons()

# --- 功能 3：商品設定 (編輯模式) ---
elif choice == "🍎 商品設定":
    st.subheader("🍎 商品資料維護 (含自動定價)")
    c.execute("SELECT name FROM products")
    product_names = ["+ 新增商品"] + [r[0] for r in c.fetchall()]
    selected_mode = st.selectbox("選擇操作對象", product_names)
    
    init_val = {"n": "", "c": 0.0, "p": 0.0, "bu": "箱", "su": "顆", "r": 10, "a": 5, "d": "", "i": None}
    if selected_mode != "+ 新增商品":
        c.execute("SELECT * FROM products WHERE name=?", (selected_mode,))
        p = c.fetchone()
        if p: init_val.update({"n": p[0], "c": p[1], "p": p[2], "bu": p[3], "su": p[4], "r": p[5], "a": p[6], "i": p[7], "d": p[8]})

    name = st.text_input("商品名稱", value=init_val["n"])
    col_u1, col_u2, col_r = st.columns(3)
    with col_u1: b_u = st.text_input("大單位", value=init_val["bu"])
    with col_u2: s_u = st.text_input("最小單位", value=init_val["su"])
    with col_r: ratio = st.number_input(f"換算率 (一{b_u}等於幾{s_u})", min_value=1, value=init_val["r"])

    col_c, col_p = st.columns(2)
    with col_c: cost = st.number_input(f"整{b_u}進貨總成本 ($)", min_value=0.0, value=init_val["c"])
    st.caption(f"💡 單{s_u}成本約 ${cost/ratio if ratio>0 else 0:.2f}")

    with col_p:
        margin = st.slider("預設毛利率 (%)", 0, 100, 30)
        suggested = (cost/ratio if ratio>0 else 0) * (1 + margin/100)
        price = st.number_input(f"單一{s_u}銷售售價 ($)", value=float(suggested if selected_mode=="+ 新增商品" else init_val["p"]))

    with st.form("prod_init"):
        alert = st.number_input("低庫存預警 (最小單位計)", value=init_val["a"])
        desc = st.text_area("詳細敘述", value=init_val["d"])
        img = st.camera_input("拍照 (保留原圖請留空)")
        if st.form_submit_button("儲存並更新資料"):
            final_img = image_to_base64(img) if img else init_val["i"]
            c.execute("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?)",
                      (name, cost, price, b_u, s_u, ratio, alert, final_img, desc))
            conn.commit(); st.success("🎉 資料更新成功！"); st.balloons()
