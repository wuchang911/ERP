import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 1. 資料庫初始化 ---
conn = sqlite3.connect('business_final.db', check_same_thread=False)
c = conn.cursor()

# 建立表格：商品表(含單位)、進銷紀錄表(含單價)
c.execute('''CREATE TABLE IF NOT EXISTS products 
             (id INTEGER PRIMARY KEY, name TEXT UNIQUE, cost REAL, price REAL, 
              unit TEXT, alert_level INTEGER, image_data TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS logs 
             (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, 
              price_at_time REAL, date TEXT)''')
conn.commit()

# --- 2. 頁面設定 ---
st.set_page_config(page_title="專業進銷存系統", layout="wide", page_icon="📦")

# 自定義 CSS 讓介面在 iPhone 上更美觀
st.markdown("""
    <style>
    .stMetric { background-color: #f0f2f6; padding: 15px; border-radius: 10px; box-shadow: 2px 2px 5px rgba(0,0,0,0.1); }
    [data-testid="stMetricValue"] { color: #1f77b4; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 工具函數 ---
def image_to_base64(image_file):
    if image_file is not None:
        img = Image.open(image_file)
        img.thumbnail((400, 400)) 
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG")
        return base64.b64encode(buffered.getvalue()).decode()
    return None

# --- 4. 側邊導覽欄 ---
st.sidebar.title("🏢 企業管理系統")
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
        st.info("💡 尚未有商品資料，請先前往『商品設定』。")
    else:
        # 顯示獲利指標
        st.metric("總累計毛利 (已售商品)", f"${df['profit'].sum():,.0f} TW$")

        # 網格化顯示
        cols = st.columns(min(len(df), 4))
        for idx, row in df.iterrows():
            with cols[idx % 4]:
                if row['image_data']:
                    st.image(f"data:image/jpeg;base64,{row['image_data']}", use_container_width=True)
                else:
                    st.write("🖼️ 無圖片")
                
                is_low = row['stock'] <= row['alert_level']
                color = "red" if is_low else "#00a000"
                
                st.markdown(f"### {row['name']}")
                st.markdown(f"庫存：<span style='color:{color}; font-size:20px; font-weight:bold;'>{row['stock']} {row['unit']}</span>", unsafe_allow_html=True)
                if is_low: st.warning("⚠️ 庫存不足")
                st.write(f"單價: ${row['price']:.0f} / 預估獲利: ${row['profit']:,.0f}")
                st.divider()

# --- 功能 2：進出貨登記 ---
elif choice == "📝 進出貨登記":
    st.subheader("📝 進銷貨登記")
    
    # 抓取商品名稱清單
    c.execute("SELECT name FROM products")
    items = [r[0] for r in c.fetchall()] # 確保是純文字列表
    
    if not items:
        st.warning("⚠️ 請先前往『商品設定』建立商品資料。")
    else:
        with st.form("trade_form"):
            t_type = st.radio("交易類型", ["進貨", "出貨"], horizontal=True)
            t_name = st.selectbox("品項名稱", options=items)
            
            col_q, col_u = st.columns([3, 1])
            with col_q:
                t_qty = st.number_input("數量", min_value=1, step=1)
            with col_u:
                # 這裡就是你要求的單位下拉選單
                t_unit = st.selectbox("單位", options=["箱", "件", "支", "公斤", "打"])
            
            t_price = st.number_input("交易單價 (TW$)", min_value=0.0, value=300.0, step=10.0)
            t_date = st.date_input("日期", datetime.now())
            
            if st.form_submit_button("確認提交紀錄"):
                c.execute("INSERT INTO logs (name, type, qty, price_at_time, date) VALUES (?,?,?,?,?)",
                          (t_name, t_type, t_qty, t_price, t_date.strftime("%Y/%m/%d")))
                conn.commit()
                st.success(f"✅ 已成功登記：{t_name} {t_type} {t_qty} {t_unit}")

# --- 功能 3：商品設定與拍照 ---
elif choice == "🍎 商品設定與拍照":
    st.subheader("⚙️ 商品資料維護")
    
    with st.form("product_form"):
        name = st.text_input("商品名稱")
        col1, col2, col3 = st.columns(3)
        with col1: cost = st.number_input("預設成本 ($)", min_value=0.0)
        with col2: price = st.number_input("預設售價 ($)", min_value=0.0)
        with col3: unit = st.selectbox("預設單位", options=["箱", "件", "支", "公斤", "打"])
        
        alert = st.number_input("低庫存預警值", min_value=0, value=5)
        
        st.write("📸 商品照片 (手機開啟可直接拍照)")
        cam_image = st.camera_input("拍照")
        
        if st.form_submit_button("儲存商品"):
            img_b64 = image_to_base64(cam_image)
            c.execute("""INSERT OR REPLACE INTO products 
                         (name, cost, price, unit, alert_level, image_data) 
                         VALUES (?,?,?,?,?,?)""", (name, cost, price, unit, alert, img_b64))
            conn.commit()
            st.success(f"🎉 商品 '{name}' 設定已更新！")

