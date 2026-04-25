import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from PIL import Image
import io
import base64
from datetime import datetime

# --- 1. 系統初始化 ---
st.set_page_config(page_title="AI 智慧 ERP 雲端版", layout="wide", initial_sidebar_state="collapsed")

# 建立 Google Sheets 連線
conn = st.connection("gsheets", type=GSheetsConnection)

def get_data(worksheet):
    # ttl=0 確保每次讀取都是最新雲端資料，避免登入失敗
    return conn.read(worksheet=worksheet, ttl=0) 

def update_data(df, worksheet):
    conn.update(worksheet=worksheet, data=df)
    st.cache_data.clear() 

# --- 2. 核心計算工具 ---
def get_detailed_stats(name):
    p_df = get_data("products")
    p_rows = p_df[p_df['name'] == name]
    if p_rows.empty: return None
    p = p_rows.iloc[0] # 修正點：必須指定索引
    
    big_u, small_u, ratio, cost, price, alert = p['big_unit'], p['small_unit'], p['ratio'], p['cost'], p['price'], p['alert_level']
    ratio = int(ratio) if ratio > 0 else 1
    
    l_df = get_data("logs")
    # 確保 logs 不為空
    if l_df.empty:
        total_small_qty = 0
    else:
        logs = l_df[l_df['name'] == name]
        total_small_qty = 0
        for _, row in logs.iterrows():
            real_q = row['qty'] * ratio if row['unit'] == big_u else row['qty']
            if '進貨' in str(row['type']) or '盤點' in str(row['type']):
                total_small_qty += real_q
            else:
                total_small_qty -= real_q

    return {
        "qty": total_small_qty,
        "display": f"{int(total_small_qty // ratio)} {big_u} {int(total_small_qty % ratio)} {small_u}",
        "is_low": total_small_qty <= alert,
        "alert_val": alert, "big_u": big_u, "small_u": small_u, "ratio": ratio, "price": price, "cost": cost
    }

# --- 3. 登入系統 ---
if "user" not in st.session_state:
    st.title("🔐 雲端 ERP 登入")
    u_input = st.text_input("帳號")
    p_input = st.text_input("密碼", type="password")
    
    if st.button("登入", use_container_width=True, type="primary"):
        u_df = get_data("users")
        # 修正點：處理空值並轉為字串
        u_df['username'] = u_df['username'].fillna('').astype(str).str.strip()
        u_df['password'] = u_df['password'].fillna('').astype(str).str.strip()
        
        user_match = u_df[(u_df['username'] == str(u_input)) & (u_df['password'] == str(p_input))]
        
        if not user_match.empty:
            st.session_state["user"] = str(user_match.iloc[0]['username'])
            st.session_state["role"] = str(user_match.iloc[0]['role'])
            st.rerun()
        else: 
            st.error("❌ 登入失敗：請檢查帳密或 Google Sheets 分頁名稱是否為 'users'")
    st.stop()

current_user, current_role = st.session_state["user"], st.session_state["role"]

# --- 4. 導覽選單 ---
menu = ["庫存報表", "交易登記", "歷史紀錄"]
if current_role == "admin": menu += ["商品管理"]
choice = st.sidebar.selectbox("功能選單", menu)
if st.sidebar.button("登出系統"): 
    st.session_state.clear()
    st.rerun()

# --- 5. 模組內容 ---
if choice == "庫存報表":
    st.subheader("📦 雲端庫存狀態")
    p_df = get_data("products")
    if p_df.empty: 
        st.info("目前雲端無商品資料")
    else:
        cols = st.columns(2)
        for idx, row in p_df.iterrows():
            s = get_detailed_stats(row['name'])
            with cols[idx % 2]:
                with st.container(border=True):
                    if 'image_data' in row and row['image_data']: 
                        st.image(f"data:image/jpeg;base64,{row['image_data']}", use_container_width=True)
                    st.markdown(f"### {row['name']}")
                    if s["is_low"]: st.error(f"🚨 庫存: {s['display']}")
                    else: st.success(f"✅ 庫存: {s['display']}")

elif choice == "交易登記":
    st.subheader("📝 登記異動")
    p_df = get_data("products")
    if p_df.empty:
        st.warning("請先至商品管理建檔")
    else:
        target = st.selectbox("選定商品", p_df['name'])
        s = get_detailed_stats(target)
        st.info(f"當前庫存：{s['display']}")
        
        with st.form("trade_form"):
            tt = st.radio("類型", ["進貨", "出貨"], horizontal=True)
            tu = st.selectbox("單位", [s["big_u"], s["small_u"]])
            tq = st.number_input("數量", min_value=1, step=1)
            if st.form_submit_button("確認提交", use_container_width=True):
                l_df = get_data("logs")
                new_log = pd.DataFrame([{
                    "id": len(l_df)+1, "name": target, "type": tt, "qty": tq, "unit": tu,
                    "price_at_time": s["price"] if tt=="出貨" else s["cost"],
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "operator": current_user
                }])
                update_data(pd.concat([l_df, new_log], ignore_index=True), "logs")
                st.success("✅ 雲端同步完成")
                st.rerun()

elif choice == "商品管理":
    st.subheader("⚙️ 商品建檔")
    p_df = get_data("products")
    mode = st.selectbox("模式", ["+ 新增"] + list(p_df['name']) if not p_df.empty else ["+ 新增"])
    with st.form("p_form"):
        pn = st.text_input("商品名稱", value="" if mode=="+ 新增" else mode)
        c1, c2, c3 = st.columns(3)
        p_b = c1.text_input("大單位", "箱")
        p_s = c2.text_input("小單位", "罐")
        p_r = c3.number_input("換算比", min_value=1, value=1)
        al = st.number_input("低庫存預警值(小單位計)", 5)
        p_i = st.file_uploader("商品圖片")
        
        if st.form_submit_button("💾 儲存到雲端"):
            b64 = ""
            if p_i:
                img = Image.open(p_i).convert("RGB")
                img.thumbnail((300, 300))
                buf = io.BytesIO()
                img.save(buf, format="JPEG")
                b64 = base64.b64encode(buf.getvalue()).decode()
            
            new_prod = pd.DataFrame([{
                "name": pn, "barcode": "", "cost": 0, "price": 0, "big_unit": p_b, 
                "small_unit": p_s, "ratio": p_r, "alert_level": al, "image_data": b64
            }])
            
            if mode == "+ 新增":
                res_df = pd.concat([p_df, new_prod], ignore_index=True)
            else:
                p_df = p_df[p_df['name'] != mode]
                res_df = pd.concat([p_df, new_prod], ignore_index=True)
            
            update_data(res_df, "products")
            st.success("✅ 雲端存檔成功！")
            st.rerun()

elif choice == "歷史紀錄":
    st.subheader("📜 雲端流水帳")
    l_df = get_data("logs")
    if l_df.empty:
        st.info("尚無交易紀錄")
    else:
        st.dataframe(l_df.sort_values("id", ascending=False), use_container_width=True)
