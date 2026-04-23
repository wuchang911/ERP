import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 1. 資料庫初始化 (維持 v12 結構) ---
conn = sqlite3.connect('business_v12.db', check_same_thread=False)
c = conn.cursor()
# ... (省略表格建立代碼，與 v12 相同) ...

# --- 2. 登入系統 ---
if "user" not in st.session_state:
    st.title("🔒 企業進銷存系統")
    u = st.text_input("帳號")
    p = st.text_input("密碼", type="password")
    if st.button("確認登入"):
        c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
        res = c.fetchone()
        if res:
            st.session_state["user"], st.session_state["role"] = res, res
            st.rerun()
    st.stop()

current_user, current_role = st.session_state["user"], st.session_state["role"]

# --- 3. 核心選單與功能分流 ---
st.sidebar.title(f"👤 {current_user}")
menu = ["📊 報表與分析", "📝 進出貨登記", "🍎 商品設定"]
if current_role != "admin": menu.remove("🍎 商品設定")
choice = st.sidebar.selectbox("切換功能", menu)

# --- 💡 關鍵：模擬圖片中的「加號多功能選單」 ---
# 我們將此選單放在每個頁面的頂部或登記頁
def multi_function_menu():
    with st.popover("➕ 更多工具"):
        st.markdown("### 🛠️ 快速操作")
        col_m1, col_m2 = st.columns(2)
        with col_c1:
            if st.button("📷 開啟相機"):
                st.session_state.show_cam = True
        with col_c2:
            st.button("🧮 計算機") # 這裡可以連動顯示計算機彈窗
            
        st.write("---")
        # 模擬圖片中的「上傳圖片/檔案」
        up_img = st.file_uploader("🖼️ 上傳/更換商品圖片", type=['png', 'jpg', 'jpeg'])
        up_file = st.file_uploader("📎 匯入 Excel 檔案", type=['xlsx', 'csv'])

# --- 功能：進出貨登記 (加入模擬圖片的彈出選單) ---
if choice == "📝 進出貨登記":
    st.subheader("📝 登記進銷貨")
    
    # 呼叫彈出選單
    multi_function_menu()
    
    c.execute("SELECT name FROM products")
    names_list = [r[0] for r in c.fetchall()]
    
    if not names_list:
        st.warning("⚠️ 請管理員先建檔。")
    else:
        # 原生的掃描輸入框
        scan_input = st.text_input("📷 點此掃描條碼 (或使用下方選單)", key="barcode_scan")
        
        default_idx = 0
        if scan_input in names_list:
            default_idx = names_list.index(scan_input)
            
        target = st.selectbox("品項名稱", options=names_list, index=default_idx)
        
        if target:
            # 抓取庫存與單位顯示
            # ... (其餘登記邏輯與 v12 相同) ...
            with st.form("trade_form"):
                # 數量的輸入...
                st.form_submit_button("確認提交紀錄")

# --- 功能：商品設定 ---
elif choice == "🍎 商品設定":
    st.subheader("🍎 商品建檔與維護")
    
    # 在這裡也可以放一個多功能選單來上傳圖片
    multi_function_menu()
    
    # ... (其餘商品維護邏輯與 v12 相同) ...
