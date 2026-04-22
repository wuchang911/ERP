import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 0. 登入密碼驗證功能 (密碼: 8888) ---
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

# --- 1. 資料庫初始化 ---
conn = sqlite3.connect('business_pro_final.db', check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS products 
             (id INTEGER PRIMARY KEY, name TEXT UNIQUE, cost REAL, price REAL, 
              unit TEXT, alert_level INTEGER, image_data TEXT, description TEXT)''')
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
        try:
            img = Image.open(image_file)
            img.thumbnail((400, 400)) 
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG")
            return base64.b64encode(buffered.getvalue()).decode()
        except: return None
    return None

def get_current_stock(product_name):
    c.execute("""SELECT 
                 SUM(CASE WHEN type = '進貨' THEN qty ELSE 0 END) - 
                 SUM(CASE WHEN type = '出貨' THEN qty ELSE 0 END) 
                 FROM logs WHERE name = ?""", (product_name,))
    res = c.fetchone()
    return res[0] if res[0] is not None else 0

# --- 4. 側邊導覽欄 ---
st.sidebar.title("🏢 企業管理系統")

# --- 簡易計算機功能 ---
st.sidebar.subheader("🧮 簡易計算機")
calc_exp = st.sidebar.text_input("輸入算式 (如: 500*1.05)")
if calc_exp:
    try:
        # 清理字元並計算
        clean_exp = calc_exp.replace('x', '*').replace('÷', '/')
        res = eval(clean_exp, {"__builtins__": None}, {})
        st.sidebar.success(f"結果: {res}")
    except:
        st.sidebar.caption("格式錯誤 (支援 + - * /)")

st.sidebar.divider()
if st.sidebar.button("登出系統"):
    del st.session_state["password_correct"]
    st.rerun()

menu = ["📊 庫存預警與報表", "📝 進出貨登記", "🍎 商品設定與拍照"]
choice = st.sidebar.selectbox("切換功能", menu)

# --- 功能 1：庫存預警與報表 (含歷史追溯與匯出) ---
if choice == "📊 庫存預警與報表":
    st.subheader("📦 即時庫存監控")
    query = """
    SELECT p.name, p.unit, p.alert_level, p.cost, p.price, p.image_data, p.description,
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
                st.markdown(f"### {row['name']}")
                st.markdown(f"庫存：<span style='color:{color}; font-size:18px; font-weight:bold;'>{row['stock']} {row['unit']}</span>", unsafe_allow_html=True)
                if row['description']:
                    with st.expander("📝 查看詳細敘述"):
                        st.write(row['description'])
                st.divider()

    st.divider()
    st.subheader("📜 歷史紀錄與數據匯出")
    history_df = pd.read_sql_query("SELECT name as 商品, type as 類型, qty as 數量, price_at_time as 單價, date as 日期 FROM logs ORDER BY id DESC", conn)
    
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        if not df.empty:
            csv_stock = df[['name', 'stock', 'unit', 'cost', 'price', 'profit']].to_csv(index=False).encode('utf-8-sig')
            st.download_button("📊 下載庫存報表", data=csv_stock, file_name="庫存報表.csv", mime='text/csv')
    with col_dl2:
        if not history_df.empty:
            csv_history = history_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📜 下載交易明細", data=csv_history, file_name="交易明細.csv", mime='text/csv')

    if not history_df.empty:
        st.dataframe(history_df.head(50), use_container_width=True)

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
                    st.error(f"❌ 庫存不足！需求({t_qty}) > 供給({current_stock})")
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
    name = st.text_input("1. 輸入商品名稱 (輸入完點擊空白處檢查)")
    is_duplicate = name in existing_names
    if name:
        if is_duplicate: st.warning(f"⚠️ 『{name}』已存在，儲存將覆蓋舊資料。")
        else: st.success(f"✅ 『{name}』是新商品")
    with st.form("product_form"):
        st.write("2. 填寫詳細資料")
        col1, col2 = st.columns(2)
        with col1: cost = st.number_input("預設成本", min_value=0.0)
        with col2: price = st.number_input("預設售價", min_value=0.0)
        col3, col4 = st.columns(2)
        with col3: unit = st.selectbox("預設單位", options=UNIT_OPTIONS)
        with col4: alert = st.number_input("預警水位", min_value=0, value=5)
        description = st.text_area("商品詳細敘述")
        cam_image = st.camera_input("拍照")
        if st.form_submit_button("更新現有商品" if is_duplicate else "儲存新商品"):
            if not name: st.error("❌ 請輸入名稱")
            else:
                img_b64 = image_to_base64(cam_image)
                c.execute("INSERT OR REPLACE INTO products (name, cost, price, unit, alert_level, image_data, description) VALUES (?,?,?,?,?,?,?)", 
                          (name, cost, price, unit, alert, img_b64, description))
                conn.commit()
                st.success(f"🎉 '{name}' 資料已同步！")
                st.balloons()
