import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime
import google.generativeai as genai

# --- 1. 介面與資料庫初始化 ---
st.set_page_config(page_title="AI 智能進銷存系統", layout="wide", page_icon="🚀")

# API Key
GEMINI_API_KEY = "AIzaSyBRV5aqbQluf9YW6p6fUXF9vcazxxjRtnk"

conn = sqlite3.connect('business_v16.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT UNIQUE, password TEXT, role TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS products 
             (name TEXT UNIQUE, cost REAL, price REAL, big_unit TEXT, small_unit TEXT, 
              ratio INTEGER, alert_level INTEGER, image_data TEXT, description TEXT, created_by TEXT, created_at TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS logs 
             (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, 
              price_at_time REAL, date TEXT, operator TEXT)''')
c.execute("INSERT OR IGNORE INTO users VALUES ('admin', '8888', 'admin')")
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
    t_small_qty, t_profit, u_cost = 0, 0, (cost / ratio if ratio > 0 else 0)
    for t, q, u, p_at in logs:
        real_q = q * ratio if u == big_u else q
        if t == '進貨': t_small_qty += real_q
        else:
            t_small_qty -= real_q
            t_profit += (q * p_at) - (real_q * u_cost)
    display_stock = f"{t_small_qty // ratio} {big_u} {t_small_qty % ratio} {small_u}"
    return t_small_qty, t_profit, display_stock, ratio

# --- 💡 核心修復：雙模型自動切換邏輯 ---
def run_ai_analysis(inventory_summary, sales_summary):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        
        # 優先嘗試 1.5-flash，失敗則切換
        model_names = ['gemini-1.5-flash', 'gemini-pro']
        model = None
        
        for m_name in model_names:
            try:
                temp_model = genai.GenerativeModel(m_name)
                # 測試發送
                temp_model.generate_content("ping")
                model = temp_model
                break
            except:
                continue
        
        if not model:
            return "❌ 無法連線至 Google AI 服務。請確認 API Key 是否已在 Google AI Studio 啟用，或該地區是否支援。"

        prompt = f"""
        你是一位專業的進銷存營運分析師。請根據以下數據提供3條具體的經營建議：
        目前的庫存狀況：{inventory_summary}
        最近的銷售明細：{sales_summary}
        請針對「補貨建議」及「獲利分析」進行回覆。請用繁體中文，語氣簡潔專業。
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 診斷異常：{str(e)}"

# --- 3. 登入系統 ---
if "user" not in st.session_state:
    st.title("🔒 企業進銷存系統")
    u = st.text_input("帳號")
    p = st.text_input("密碼", type="password")
    if st.button("確認進入"):
        c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
        res = c.fetchone()
        if res:
            st.session_state["user"], st.session_state["role"] = res, res
            st.rerun()
        else: st.error("❌ 帳密錯誤")
    st.stop()

current_user, current_role = st.session_state["user"], st.session_state["role"]

# --- 4. ➕ 快速操作選單 ---
def quick_action_menu():
    with st.popover("➕ 快速操作"):
        st.subheader("🤖 AI 營運助手")
        if st.button("✨ 執行 AI 數據分析"):
            with st.spinner("AI 正在分析您的店鋪數據..."):
                c.execute("SELECT name FROM products")
                inv_data = [f"{n}: {get_stock_and_profit(n)}" for n in c.fetchall()]
                logs_df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC LIMIT 15", conn)
                report = run_ai_analysis(str(inv_data), logs_df.to_string())
                st.info(report)
        
        st.divider()
        calc = st.text_input("🧮 計算機")
        if calc:
            try: st.success(f"結果: {eval(calc.replace('x', '*').replace('÷', '/'))}")
            except: pass
            
        if current_role == "admin":
            st.divider()
            st.subheader("⚙️ 管理員工具")
            st.session_state.is_locked = st.toggle("🔒 盤點鎖定模式", value=st.session_state.get('is_locked', False))
            h_df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC", conn)
            st.download_button("📥 匯出明細 (CSV)", h_df.to_csv(index=False).encode('utf-8-sig'), "history.csv", "text/csv")

# --- 5. 主選單 ---
st.sidebar.title(f"👤 {current_user}")
if st.sidebar.button("🚪 登出系統"):
    del st.session_state["user"]; st.rerun()

menu = ["📊 庫存報表", "📝 進出貨登記"]
if current_role == "admin": menu.append("🍎 商品維護設定")
choice = st.sidebar.selectbox("切換功能", menu)

# --- 報表 ---
if choice == "📊 庫存報表":
    st.subheader("📦 即時庫存監控")
    quick_action_menu()
    c.execute("SELECT name, image_data, description FROM products")
    prods = c.fetchall()
    if prods:
        all_p, profit_data = 0, []
        cols = st.columns(2 if st.sidebar.checkbox("手機模式", True) else 4)
        for idx, (n, img, desc) in enumerate(prods):
            sq, prof, ds, _ = get_stock_and_profit(n)
            all_p += prof
            profit_data.append({"品項": n, "毛利": prof})
            with cols[idx % len(cols)]:
                if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                st.markdown(f"**{n}**\n庫存：{ds}")
                st.divider()
        if current_role == "admin":
            st.sidebar.metric("總累計毛利", f"${all_p:,.0f}")
            st.bar_chart(pd.DataFrame(profit_data).set_index("品項"))
    
    st.subheader("📜 歷史明細")
    h_df = pd.read_sql_query("SELECT name, type, qty, unit, operator, date FROM logs ORDER BY id DESC LIMIT 50", conn)
    st.dataframe(h_df, use_container_width=True)

# --- 登記 ---
elif choice == "📝 進出貨登記":
    st.subheader("📝 登記進銷貨")
    quick_action_menu()
    if st.session_state.get('is_locked', False): st.error("🛑 系統鎖定中")
    else:
        c.execute("SELECT name FROM products")
        names_list = [r for r in c.fetchall()]
        scan = st.text_input("📷 掃描/搜尋品項")
        idx = names_list.index(scan) if scan in names_list else 0
        target = st.selectbox("品項確認", options=names_list, index=idx)
        if target:
            sq, _, ds, _ = get_stock_and_profit(target)
            st.info(f"當前庫存：{ds}")
            c.execute("SELECT big_unit, small_unit, ratio FROM products WHERE name=?", (target,))
            b_u, s_u, ratio = c.fetchone()
            with st.form("trade"):
                t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
                t_qty = st.number_input("數量", min_value=1)
                t_unit = st.selectbox("單位", [b_u, s_u])
                t_price = st.number_input("成交單價", min_value=0.0)
                if st.form_submit_button("確認提交"):
                    tx_sq = t_qty * ratio if t_unit == b_u else t_qty
                    if t_type == "出貨" and tx_sq > sq: st.error("❌ 庫存不足")
                    else:
                        c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                                  (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                        conn.commit(); st.success("✅ 登記成功"); st.balloons()

# --- 設定 ---
elif choice == "🍎 商品維護設定":
    st.subheader("🍎 商品建檔與維護")
    quick_action_menu()
    c.execute("SELECT name FROM products")
    exists = ["+ 新增商品"] + [r for r in c.fetchall()]
    mode = st.selectbox("編輯對象", exists)
    iv = {"n":"","c":0.0,"p":0.0,"bu":"箱","su":"顆","r":10,"d":"","img":None}
    if mode != "+ 新增商品":
        c.execute("SELECT * FROM products WHERE name=?", (mode,))
        p = c.fetchone()
        if p: iv = {"n":p,"c":p,"p":p,"bu":p,"su":p,"r":p,"img":p,"d":p}

    name = st.text_input("品名 (條碼)", value=iv["n"])
    col1, col2, col3 = st.columns(3)
    with col1: b_u = st.text_input("大單位", value=iv["bu"])
    with col2: s_u = st.text_input("小單位", value=iv["su"])
    with col3: ratio = st.number_input("換算率", min_value=1, value=iv["r"])
    
    cost = st.number_input("整箱成本", value=iv["c"])
    margin = st.slider("毛利率 (%)", 0, 100, 30)
    suggested = (cost/ratio) * (1 + margin/100) if ratio > 0 else 0
    price = st.number_input("單顆售價", value=float(iv["p"] if mode != "+ 新增商品" else suggested))

    with st.form("prod"):
        desc = st.text_area("描述", value=iv["d"])
        cam = st.camera_input("拍照")
        if st.form_submit_button("儲存商品"):
            img_b = image_to_base64(cam) if cam else iv["img"]
            c.execute("INSERT OR REPLACE INTO products (name, cost, price, big_unit, small_unit, ratio, alert_level, image_data, description, created_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (name, cost, price, b_u, s_u, ratio, 5, img_b, desc, current_user))
            conn.commit(); st.success("🎉 已儲存"); st.rerun()
