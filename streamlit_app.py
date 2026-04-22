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
            else:
                st.error("❌ 密碼錯誤")
        return False
    return True

if not check_password():
    st.stop()

# --- 1. 資料庫初始化 (使用 v5 版本確保欄位正確) ---
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
    """核心邏輯：統一換算為最小單位計算庫存與毛利"""
    c.execute("SELECT big_unit, small_unit, ratio, cost, price FROM products WHERE name=?", (name,))
    p = c.fetchone()
    if not p: return 0, 0, "無資料", 1
    big_u, small_u, ratio, cost, price = p
    
    c.execute("SELECT type, qty, unit, price_at_time FROM logs WHERE name=?", (name,))
    logs = c.fetchall()
    total_small_qty = 0
    total_profit = 0
    
    # 計算公式：
    # 最小單位成本 = 大單位進貨成本 / 換算率
    # 最小單位售價 = 商品設定的單一售價
    small_unit_cost = cost / ratio
    
    for t, q, u, p_at_time in logs:
        # 轉換此筆交易為最小單位數量
        tx_small_qty = q * ratio if u == big_u else q
        
        if t == '進貨':
            total_small_qty += tx_small_qty
        else:
            total_small_qty -= tx_small_qty
            # 毛利 = 該次銷售總額 - (最小單位成本 * 銷售最小單位數量)
            tx_revenue = q * p_at_time
            total_profit += tx_revenue - (tx_small_qty * small_unit_cost)

    display_stock = f"{total_small_qty // ratio} {big_u} {total_small_qty % ratio} {small_u}"
    return total_small_qty, total_profit, display_stock, ratio

# --- 3. 側邊欄與計算機 ---
st.sidebar.title("🏢 企業管理系統")
calc_exp = st.sidebar.text_input("🧮 簡易計算機 (如: 500*12)")
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
    st.subheader("📦 精確庫存監控 (支援單位換算)")
    c.execute("SELECT name, image_data, alert_level, description, small_unit FROM products")
    prods = c.fetchall()
    
    if not prods:
        st.info("💡 請先前往『商品設定』建立品項與換算率。")
    else:
        all_profit = 0
        cols = st.columns(2 if st.sidebar.checkbox("手機模式", True) else 4)
        
        for idx, (name, img, alert, desc, s_u) in enumerate(prods):
            small_qty, profit, display_stock, ratio = get_stock_and_profit(name)
            all_profit += profit
            with cols[idx % len(cols)]:
                if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                color = "#FF4B4B" if small_qty <= alert else "#00A000"
                st.markdown(f"**{name}**")
                st.markdown(f"庫存：<span style='color:{color};font-weight:bold;font-size:18px;'>{display_stock}</span>", unsafe_allow_html=True)
                if desc:
                    with st.expander("📝 敘述"): st.write(desc)
                st.divider()
        
        st.sidebar.metric("總累計毛利", f"${all_profit:,.0f} TW$")

        # 歷史追溯
        st.subheader("📜 歷史交易紀錄")
        history_df = pd.read_sql_query("SELECT name as 商品, type as 類型, qty as 數量, unit as 單位, price_at_time as 交易單價, date as 日期 FROM logs ORDER BY id DESC LIMIT 50", conn)
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
        item_names = [i for i in items]
        with st.form("trade"):
            t_data = st.selectbox("選擇品項", options=item_names, format_func=lambda x: x)
            t_type = st.radio("交易類型", ["進貨", "出貨"], horizontal=True)
            
            # 即時顯示目前庫存
            s_qty, _, d_stock, _ = get_stock_and_profit(t_data)
            st.info(f"💡 目前庫存：{d_stock}")
            
            colq, colu = st.columns(2)
            with colq: t_qty = st.number_input("數量", min_value=1, step=1)
            with colu: t_unit = st.selectbox("單位", options=[t_data, t_data])
            
            t_price = st.number_input("此筆交易單價 (TW$)", min_value=0.0, value=100.0)
            t_date = st.date_input("日期", datetime.now())
            
            if st.form_submit_button("提交紀錄"):
                # 檢查負庫存 (換算後比較)
                c.execute("SELECT ratio FROM products WHERE name=?", (t_data,))
                ratio = c.fetchone()
                tx_small_qty = t_qty * ratio if t_unit == t_data else t_qty
                
                if t_type == "出貨" and tx_small_qty > s_qty:
                    st.error(f"❌ 庫存不足！需求 {tx_small_qty} 大於現有 {s_qty}")
                else:
                    c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date) VALUES (?,?,?,?,?,?)", 
                              (t_data, t_type, t_qty, t_unit, t_price, t_date.strftime("%Y/%m/%d")))
                    conn.commit()
                    st.success("✅ 登記完成"); st.balloons()

# --- 功能 3：商品設定 (定義換算) ---
elif choice == "🍎 商品設定":
    st.subheader("🍎 商品換算與預警設定")
    c.execute("SELECT name FROM products")
    existing = [r for r in c.fetchall()]
    
    name = st.text_input("商品名稱 (如: 蘋果)")
    if name in existing: st.warning("⚠️ 此商品已存在，儲存將覆蓋舊設定。")
    
    with st.form("prod_init"):
        col1, col2 = st.columns(2)
        with col1: b_u = st.text_input("大單位 (如: 箱)", value="箱")
        with col2: s_u = st.text_input("最小單位 (如: 顆)", value="顆")
        
        ratio = st.number_input(f"換算率 (一{b_u}等於多少{s_u}?)", min_value=1, value=10)
        cost = st.number_input(f"整{b_u}進貨總成本 ($)", min_value=0.0)
        price = st.number_input(f"單一{s_u}銷售售價 ($)", min_value=0.0)
        alert = st.number_input(f"低庫存預警 (以{s_u}計)", min_value=0, value=5)
        desc = st.text_area("詳細敘述")
        img = st.camera_input("拍照")
        
        if st.form_submit_button("儲存商品"):
            if not name: st.error("❌ 請輸入名稱")
            else:
                c.execute("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?)",
                          (name, cost, price, b_u, s_u, ratio, alert, image_to_base64(img), desc))
                conn.commit(); st.success(f"🎉 {name} 設定成功！")
