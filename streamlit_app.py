import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 0. 登入密碼驗證功能 ---
def check_password():
    """只有輸入正確密碼才會顯示主程式"""
    def password_entered():
        # 你可以在這裡修改你的密碼，目前設定為 8888
        if st.session_state["password"] == "8888":
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # 清除密碼暫存增加安全性
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # 第一次進入
        st.title("🔒 企業管理系統登入")
        st.text_input("請輸入進入密碼", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        # 密碼輸入錯誤
        st.title("🔒 企業管理系統登入")
        st.text_input("密碼不正確，請重新輸入", type="password", on_change=password_entered, key="password")
        st.error("❌ 密碼錯誤，請聯繫管理員。")
        return False
    else:
        # 密碼正確
        return True

# 執行驗證，若失敗則停止執行後續程式
if not check_password():
    st.stop()

# --- 以下為原本的進銷存邏輯 (密碼通過後才會執行) ---

# --- 1. 資料庫初始化 ---
conn = sqlite3.connect('business_final.db', check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS products 
             (id INTEGER PRIMARY KEY, name TEXT UNIQUE, cost REAL, price REAL, 
              unit TEXT, alert_level INTEGER, image_data TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS logs 
             (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, 
              price_at_time REAL, date TEXT)''')
conn.commit()

# --- 2. 頁面設定 ---
st.set_page_config(page_title="雲端進銷存系統", layout="wide", page_icon="📦")
UNIT_OPTIONS = ["箱", "件", "顆", "包", "袋", "兩", "支", "公斤", "打"]

# --- 3. 工具函數 ---
def image_to_base64(image_file):
    if image_file is not None:
        img = Image.open(image_file)
        img.thumbnail((400, 400)) 
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG")
        return base64.b64encode(buffered.getvalue()).decode()
    return None

def get_current_stock(product_name):
    c.execute("""SELECT 
                 SUM(CASE WHEN type = '進貨' THEN qty ELSE 0 END) - 
                 SUM(CASE WHEN type = '出貨' THEN qty ELSE 0 END) 
                 FROM logs WHERE name = ?""", (product_name,))
    result = c.fetchone()[0]
    return result if result is not None else 0

# --- 4. 側邊導覽欄 ---
st.sidebar.title("🏢 企業管理系統")
st.sidebar.success("✅ 已登入")
menu = ["📊 庫存預警與報表", "📝 進出貨登記", "🍎 商品設定與拍照"]
choice = st.sidebar.selectbox("切換功能", menu)

# --- 功能 1：庫存預警與報表 ---
if choice == "📊 庫存預警與報表":
    st.subheader("📦 即時庫存監控")
    query = """
    SELECT p.name, p.unit, p.alert_level, p.cost, p.price, p.image_data,
           SUM(CASE WHEN l.type = '進貨' THEN l.qty ELSE 0 END) - 
           SUM(CASE WHEN l.type = '出貨' THEN l.qty ELSE 0 END) as stock,
           SUM(CASE WHEN l.type = '出貨' THEN l.qty ELSE 0 END) * (p.price - p.cost) as profit
    FROM products p
    LEFT JOIN logs l ON p.name = l.name
    GROUP BY p.name
    """
    df = pd.read_sql_query(query, conn)

    if df.empty:
        st.info("💡 目前尚無資料，請先前往『商品設定』。")
    else:
        st.metric("總累計毛利", f"${df['profit'].sum():,.0f} TW$")
        cols = st.columns(2 if st.sidebar.checkbox("手機模式", True) else 4)
        for idx, row in df.iterrows():
            with cols[idx % len(cols)]:
                if row['image_data']:
                    st.image(f"data:image/jpeg;base64,{row['image_data']}", use_container_width=True)
                is_low = row['stock'] <= row['alert_level']
                color = "#FF4B4B" if is_low else "#00A000"
                st.markdown(f"**{row['name']}**")
                st.markdown(f"庫存：<span style='color:{color}; font-size:18px; font-weight:bold;'>{row['stock']} {row['unit']}</span>", unsafe_allow_html=True)
                st.divider()

# --- 功能 2：進出貨登記 ---
elif choice == "📝 進出貨登記":
    st.subheader("📝 進銷貨登記")
    c.execute("SELECT name FROM products")
    items = [r[0] for r in c.fetchall()]
    
    if not items:
        st.warning("⚠️ 請先建立商品資料。")
    else:
        with st.form("trade_form"):
            t_type = st.radio("交易類型", ["進貨", "出貨"], horizontal=True)
            t_name = st.selectbox("品項名稱", options=items)
            current_stock = get_current_stock(t_name)
            st.info(f"💡 目前系統庫存：{current_stock}")
            
            col_q, col_u = st.columns(2)
            with col_q: t_qty = st.number_input("數量", min_value=1, step=1)
            with col_u: t_unit = st.selectbox("單位", options=UNIT_OPTIONS)
            
            t_price = st.number_input("單價 (TW$)", min_value=0.0, value=300.0)
            t_date = st.date_input("日期", datetime.now())
            
            if st.form_submit_button("確認提交"):
                if t_type == "出貨" and t_qty > current_stock:
                    st.error(f"❌ 庫存不足！無法出貨。")
                else:
                    c.execute("INSERT INTO logs (name, type, qty, price_at_time, date) VALUES (?,?,?,?,?)",
                              (t_name, t_type, t_qty, t_price, t_date.strftime("%Y/%m/%d")))
                    conn.commit()
                    st.success(f"✅ 登記成功")

# --- 功能 3：商品設定與拍照 ---
elif choice == "🍎 商品設定與拍照":
    st.subheader("⚙️ 商品資料維護")
    c.execute("SELECT name FROM products")
    existing_names = [r[0] for r in c.fetchall()]
    
    with st.form("product_form"):
        name = st.text_input("商品名稱")
        if name in existing_names:
            st.warning(f"⚠️ 『{name}』已存在，儲存將覆蓋舊資料。")
            
        col1, col2 = st.columns(2)
        with col1: cost = st.number_input("預設成本", min_value=0.0)
        with col2: price = st.number_input("預設售價", min_value=0.0)
        
        unit = st.selectbox("預設單位", options=UNIT_OPTIONS)
        alert = st.number_input("預警水位", min_value=0, value=5)
        cam_image = st.camera_input("拍照")
        
        if st.form_submit_button("儲存商品"):
            if not name:
                st.error("❌ 請輸入名稱")
            else:
                img_b64 = image_to_base64(cam_image)
                c.execute("INSERT OR REPLACE INTO products VALUES (NULL,?,?,?,?,?,?)", 
                          (name, cost, price, unit, alert, img_b64))
                conn.commit()
                st.success(f"🎉 '{name}' 已存檔！")

if st.sidebar.button("登出系統"):
    del st.session_state["password_correct"]
    st.rerun()
