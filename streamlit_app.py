import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 資料庫初始化 ---
conn = sqlite3.connect('business_pro.db', check_same_thread=False)
c = conn.cursor()

# 建立表格：商品表(含照片、預警、成本)、進銷紀錄表
c.execute('''CREATE TABLE IF NOT EXISTS products 
             (id INTEGER PRIMARY KEY, name TEXT UNIQUE, cost REAL, price REAL, 
              alert_level INTEGER, image_data TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS logs 
             (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, date TEXT)''')
conn.commit()

# --- 頁面設定 ---
st.set_page_config(page_title="雲端進銷存Pro", layout="wide", page_icon="📦")

# 自定義 CSS 讓介面在 iPhone 上更清楚
st.markdown("""<style> .stMetric { background-color: #f0f2f6; padding: 10px; border-radius: 10px; } </style>""", unsafe_allow_html=True)

# --- 工具函數：照片處理 ---
def image_to_base64(image_file):
    if image_file is not None:
        img = Image.open(image_file)
        img.thumbnail((400, 400)) # 壓縮尺寸避免資料庫過大
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG")
        return base64.b64encode(buffered.getvalue()).decode()
    return None

# --- 側邊導覽欄 ---
st.sidebar.title("🏢 企業管理系統")
menu = ["📊 庫存預警與報表", "📝 進出貨登記", "🍎 商品設定與拍照"]
choice = st.sidebar.selectbox("切換功能", menu)

# --- 功能 1：庫存預警與報表 ---
if choice == "📊 庫存預警與報表":
    st.subheader("📦 即時庫存監控")
    
    query = """
    SELECT p.name, p.alert_level, p.cost, p.price, p.image_data,
           SUM(CASE WHEN l.type = '進貨' THEN l.qty ELSE 0 END) - 
           SUM(CASE WHEN l.type = '出貨' THEN l.qty ELSE 0 END) as stock,
           SUM(CASE WHEN l.type = '出貨' THEN l.qty ELSE 0 END) * (p.price - p.cost) as profit
    FROM products p
    LEFT JOIN logs l ON p.name = l.name
    GROUP BY p.name
    """
    df = pd.read_sql_query(query, conn)

    if df.empty:
        st.info("目前還沒有資料，請先前往『商品設定』新增品項。")
    else:
        # 顯示頂部指標
        total_p = df['profit'].sum()
        st.metric("總累計毛利 (已售商品)", f"${total_p:,.0f}")

        # 顯示網格化庫存
        cols = st.columns(min(len(df), 4))
        for idx, row in df.iterrows():
            with cols[idx % 4]:
                if row['image_data']:
                    st.image(f"data:image/jpeg;base64,{row['image_data']}", use_container_width=True)
                else:
                    st.write("🖼️ 無圖片")
                
                # 庫存預警顏色判斷
                is_low = row['stock'] <= row['alert_level']
                stock_color = "red" if is_low else "black"
                
                st.markdown(f"**{row['name']}**")
                st.markdown(f"庫存：<span style='color:{stock_color}; font-weight:bold;'>{row['stock']}</span>", unsafe_allow_html=True)
                if is_low: st.caption("⚠️ 補貨警告")
                st.write(f"預估獲利: ${row['profit']:,.0f}")
                st.divider()

# --- 功能 2：進出貨登記 ---
elif choice == "📝 進出貨登記":
    st.subheader("📝 每日帳目登記")
    
    # 正確抓取商品清單供下拉選單使用
    c.execute("SELECT name FROM products")
    items = [r for r in c.fetchall()]
    
    if not items:
        st.warning("請先到『商品設定』建立商品資料。")
    else:
        with st.form("trade_form"):
            t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
            t_name = st.selectbox("選擇商品", items)
            t_qty = st.number_input("數量", min_value=1, step=1)
            t_date = st.date_input("日期", datetime.now())
            
            if st.form_submit_button("提交紀錄"):
                c.execute("INSERT INTO logs (name, type, qty, date) VALUES (?,?,?,?)",
                          (t_name, t_type, t_qty, t_date.strftime("%Y-%m-%d")))
                conn.commit()
                st.success(f"已登記：{t_name} {t_type} {t_qty} 件")

# --- 功能 3：商品設定與拍照 ---
elif choice == "🍎 商品設定與拍照":
    st.subheader("⚙️ 商品資料維護")
    
    with st.form("product_form"):
        name = st.text_input("商品名稱 (例如：iPhone 15)")
        col1, col2, col3 = st.columns(3)
        with col1: cost = st.number_input("成本 ($)", min_value=0.0)
        with col2: price = st.number_input("售價 ($)", min_value=0.0)
        with col3: alert = st.number_input("預警水位", min_value=0, value=5)
        
        st.write("📸 商品照片 (手機開啟可直接拍照)")
        cam_image = st.camera_input("拍照")
        
        if st.form_submit_button("儲存商品"):
            img_b64 = image_to_base64(cam_image)
            # 使用 REPLACE 確保重複名稱時會更新舊資料
            c.execute("""INSERT OR REPLACE INTO products 
                         (name, cost, price, alert_level, image_data) 
                         VALUES (?,?,?,?,?)""", (name, cost, price, alert, img_b64))
            conn.commit()
            st.success(f"商品 '{name}' 已更新！")
