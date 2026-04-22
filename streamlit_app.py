# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 0. 頁面基本設定 (必須在最上方) ---
st.set_page_config(page_title="專業進銷存管理系統", layout="wide")

# --- 1. 登入密碼檢查邏輯 ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if st.session_state["password_correct"]:
        return True

    st.title("🔐 系統安全登入")
    pwd = st.text_input("請輸入管理員密碼", type="password")
    if st.button("登入"):
        if pwd == "888888":  # <--- 在這裡修改你的專屬密碼
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("😕 密碼錯誤，請重試")
    return False

# --- 只有登入成功才執行以下內容 ---
if check_password():
    # --- 2. 資料庫初始化 ---
    conn = sqlite3.connect('erp_v10_final.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('PRAGMA encoding = "UTF-8"')
    c.execute('''CREATE TABLE IF NOT EXISTS products 
                 (name TEXT PRIMARY KEY, cost REAL, price REAL, unit TEXT, 
                  alert_level INTEGER, image_data TEXT, last_updated TEXT, description TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, type TEXT, 
                  qty INTEGER, price REAL, date TEXT)''')
    conn.commit()

    # 工具函式
    def image_to_base64(image_file):
        if image_file is not None:
            try:
                img = Image.open(image_file).convert("RGB")
                img.thumbnail((400, 400)) 
                buffered = io.BytesIO()
                img.save(buffered, format="JPEG", quality=85)
                return base64.b64encode(buffered.getvalue()).decode('utf-8')
            except: return None
        return None

    # CSS 樣式
    st.markdown("""<style>
        body { font-family: "PingFang TC", sans-serif; } 
        .stock-highlight { font-size: 22px; font-weight: bold; }
        .desc-label { color: #555; font-size: 14px; background: #f0f2f6; padding: 8px; border-radius: 5px; margin: 5px 0; }
    </style>""", unsafe_allow_html=True)

    # 側邊欄
    st.sidebar.header("⚙️ 系統設定")
    currency_map = {"TWD (TW$)": "TW$", "USD (US$)": "US$", "HKD (HK$)": "HK$", "CNY (¥)": "¥"}
    curr_key = st.sidebar.selectbox("貨幣單位", list(currency_map.keys()))
    symbol = currency_map[curr_key]
    if st.sidebar.button("登出系統"):
        st.session_state["password_correct"] = False
        st.rerun()

    menu = ["📊 庫存預警", "📝 進出登記", "📜 歷史追溯", "🍎 商品管理"]
    choice = st.sidebar.selectbox("功能選單", menu)

    # --- A. 庫存預警 ---
    if choice == "📊 庫存預警":
        st.subheader(f"即時庫存狀況 ({curr_key})")
        df_p = pd.read_sql_query("SELECT * FROM products", conn)
        df_l = pd.read_sql_query("SELECT * FROM logs", conn)
        
        if df_p.empty:
            st.info("請先前往「商品管理」新增商品。")
        else:
            total_all_profit = 0
            display_list = []
            for _, p in df_p.iterrows():
                item_logs = df_l[df_l['name'] == p['name']]
                in_qty = item_logs[item_logs['type'] == '進貨']['qty'].sum()
                out_qty = item_logs[item_logs['type'] == '出貨']['qty'].sum()
                # 實際獲利 = (銷售總額) - (售出數量 * 成本)
                sales_val = (item_logs[item_logs['type'] == '出貨']['qty'] * item_logs[item_logs['type'] == '出貨']['price']).sum()
                cost_val = out_qty * p['cost']
                profit = sales_val - cost_val
                total_all_profit += profit
                display_list.append({**p, "stock": in_qty - out_qty, "profit": profit})

            st.metric("總累計毛利", f"{symbol} {total_all_profit:,.0f}")
            cols = st.columns(3)
            for idx, item in enumerate(display_list):
                with cols[idx % 3]:
                    if item['image_data']: st.image(f"data:image/jpeg;base64,{item['image_data']}", use_container_width=True)
                    st.markdown(f"### {item['name']}")
                    color = "red" if item['stock'] <= item['alert_level'] else "#1E88E5"
                    st.markdown(f"庫存：<span class='stock-highlight' style='color:{color};'>{int(item['stock'])}</span> {item['unit']}", unsafe_allow_html=True)
                    if item['description']: st.markdown(f"<div class='desc-label'>📖 {item['description']}</div>", unsafe_allow_html=True)
                    st.write(f"定價：{symbol} {item['price']:,.0f} | 獲利：{symbol} {item['profit']:,.0f}")
                    st.write("---")

    # --- B. 進出登記 ---
    elif choice == "📝 進出登記":
        st.subheader("📝 進銷貨登記")
        prods = pd.read_sql_query("SELECT * FROM products", conn)
        if prods.empty: st.warning("請先設定商品資料")
        else:
            with st.form("log_form", clear_on_submit=True):
                t_type = st.radio("交易類型", ["進貨", "出貨"], horizontal=True)
                t_name = st.selectbox("品項名稱", prods['name'])
                row = prods[prods['name'] == t_name].iloc[0]
                def_price = float(row['cost'] if t_type == "進貨" else row['price'])
                
                c1, c2 = st.columns(2)
                with c1: t_qty = st.number_input(f"數量 ({row['unit']})", min_value=1, step=1)
                with c2: t_prc = st.number_input(f"單價 ({symbol})", value=def_price)
                t_date = st.date_input("日期", datetime.now())
                if st.form_submit_button("確認提交紀錄"):
                    c.execute("INSERT INTO logs (name, type, qty, price, date) VALUES (?,?,?,?,?)",
                              (t_name, t_type, t_qty, t_prc, t_date.strftime("%Y-%m-%d")))
                    conn.commit()
                    st.success(f"登記成功！")
                    st.rerun()

    # --- C. 歷史追溯 ---
    elif choice == "📜 歷史追溯":
        st.subheader("📜 交易紀錄管理")
        df_h = pd.read_sql_query("SELECT id, date as 日期, name as 品項, type as 類型, qty as 數量, price as 單價 FROM logs ORDER BY date DESC, id DESC", conn)
        if not df_h.empty:
            df_h['總額'] = df_h['數量'] * df_h['單價']
            st.dataframe(df_h.drop(columns=['id']), use_container_width=True)
            st.write("---")
            log_id = st.selectbox("選擇紀錄 ID 以刪除", df_h['id'].tolist())
            if st.button("確認刪除該筆紀錄"):
                c.execute("DELETE FROM logs WHERE id = ?", (log_id,))
                conn.commit()
                st.rerun()
        else: st.info("尚無紀錄")

    # --- D. 商品管理 ---
    elif choice == "🍎 商品管理":
        st.subheader("🍎 商品資料維護")
        with st.form("add_p", clear_on_submit=True):
            n = st.text_input("商品名稱")
            desc = st.text_area("詳細內容備註")
            c1, c2 = st.columns(2); unit = c1.selectbox("單位", ["個", "件", "台", "公斤", "箱", "瓶"]); alrt = c2.number_input("預警水位", min_value=0, value=5)
            c3, c4 = st.columns(2); cst = c3.number_input(f"成本 ({symbol})", min_value=0.0); prc = c4.number_input(f"定價 ({symbol})", min_value=0.0)
            img = st.camera_input("📷 商品拍照")
            if st.form_submit_button("儲存商品"):
                if n:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    c.execute("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?)", (n, cst, prc, unit, alrt, image_to_base64(img), now, desc))
                    conn.commit()
                    st.success("商品已儲存"); st.rerun()
        
        st.write("---")
        del_list = pd.read_sql_query("SELECT name FROM products", conn)
        if not del_list.empty:
            target = st.selectbox("選擇要刪除的商品", del_list['name'])
            if st.button(f"永久刪除 {target}"):
                c.execute("DELETE FROM products WHERE name = ?", (target,))
                conn.commit(); st.rerun()

