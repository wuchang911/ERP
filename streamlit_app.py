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

# 🔒 安全讀取 API Key (請確保已在 Streamlit Secrets 設定)
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    GEMINI_API_KEY = ""

conn = sqlite3.connect('business_v17.db', check_same_thread=False)
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

def run_ai_analysis(inventory_summary, sales_summary):
    if not GEMINI_API_KEY:
        return "⚠️ 請先在 Secrets 設定 GEMINI_API_KEY。"
    try:
        # 1. 初始化
        genai.configure(api_key=GEMINI_API_KEY)
        
        # 2. 自動尋找您帳號權限內可用的模型 (核心修正)
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
                # 在 run_ai_analysis 函數中修改這段：
# 優先順序改為 1.5-Flash，通常它的免費額度更穩定
for preferred in ['models/gemini-1.5-flash', 'models/gemini-2.0-flash', 'models/gemini-pro']:
    if preferred in available_models:
        target_model = preferred
        break


        
        if not target_model:
            # 如果找不到預設的，就抓清單第一個可用的
            target_model = available_models[0] if available_models else None

        if not target_model:
            return "❌ 您的 API Key 目前沒有可用模型，請確認 Google AI Studio 權限。"

        # 3. 建立模型並生成
        model = genai.GenerativeModel(target_model)
        
        prompt = f"""
        你是一位專業營運分析師。請根據數據提供3條建議：
        目前的庫存：{inventory_summary}
        最近的銷售：{sales_summary}
        請用繁體中文回覆，語氣簡潔。
        """
        
        response = model.generate_content(prompt)
        return response.text
        
    except Exception as e:
        return f"AI 診斷失敗。這通常是 Google 伺服器同步問題，建議更換新 API Key。\n詳細錯誤：{str(e)}"





# --- 3. 登入系統 ---
if "user_role" not in st.session_state:
    st.title("🔒 企業進銷存登入")
    u = st.text_input("帳號", key="login_u")
    p = st.text_input("密碼", type="password", key="login_p")
    if st.button("登入系統"):
        c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
        res = c.fetchone()
        if res:
            st.session_state["user_name"] = res[0]
            st.session_state["user_role"] = res[1] # 確保存入正確的權限字串
            st.rerun()
        else:
            st.error("❌ 帳密錯誤")
    st.stop()

current_user = st.session_state["user_name"]
current_role = st.session_state["user_role"]

# --- 4. ➕ 快速操作選單 ---
def quick_action_menu():
    with st.popover("➕ 快速操作選單"):
        st.subheader("🤖 AI 營運助手")
        if st.button("✨ 執行 AI 數據診斷"):
            with st.spinner("AI 分析中..."):
                c.execute("SELECT name FROM products")
                inv_data = [f"{n}: {get_stock_and_profit(n)[2]}" for n in c.fetchall()]
                logs_df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC LIMIT 15", conn)
                report = run_ai_analysis(str(inv_data), logs_df.to_string())
                st.info(report)
        st.divider()
        calc = st.text_input("🧮 計算機 (如: 500*12)")
        if calc:
            try: st.success(f"結果: {eval(calc.replace('x', '*').replace('÷', '/'))}")
            except: pass
        if current_role == "admin":
            st.divider()
            st.subheader("⚙️ 管理員工具")
            st.session_state.is_locked = st.toggle("🔒 開啟盤點鎖定", value=st.session_state.get('is_locked', False))
            h_df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC", conn)
            st.download_button("📥 匯出明細 (CSV)", h_df.to_csv(index=False).encode('utf-8-sig'), "history.csv", "text/csv")

# --- 5. 主選單功能分流 ---
st.sidebar.title(f"👤 {current_user}")
if st.sidebar.button("🚪 登出系統"):
    del st.session_state["user_role"]
    st.rerun()

# 核心修正：精確判斷選單項目
menu = ["📊 庫存報表", "📝 進出貨登記"]
if current_role == "admin":
    menu.append("🍎 商品維護設定")

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
    
    st.subheader("📜 最近歷史明細")
    h_df = pd.read_sql_query("SELECT name, type, qty, unit, operator, date FROM logs ORDER BY id DESC LIMIT 50", conn)
    st.dataframe(h_df, use_container_width=True)

# --- 登記 ---
elif choice == "📝 進出貨登記":
    st.subheader("📝 登記進銷貨")
    quick_action_menu()
    if st.session_state.get('is_locked', False):
        st.error("🛑 系統鎖定中")
    else:
        c.execute("SELECT name FROM products")
        names_list = [r[0] for r in c.fetchall()]
        scan = st.text_input("📷 掃描/搜尋品項")
        idx = names_list.index(scan) if scan in names_list else 0
        target = st.selectbox("品項確認", options=names_list, index=idx)
        if target:
            sq, _, ds, _ = get_stock_and_profit(target)
            st.info(f"當前庫存：{ds}")
            c.execute("SELECT big_unit, small_unit FROM products WHERE name=?", (target,))
            units = c.fetchone()
            with st.form("trade"):
                t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
                t_qty = st.number_input("數量", min_value=1)
                t_unit = st.selectbox("單位", list(units))
                t_price = st.number_input("單價", min_value=0.0)
                if st.form_submit_button("確認提交"):
                    # 獲取換算率進行檢查
                    c.execute("SELECT ratio FROM products WHERE name=?", (target,))
                    ratio = c.fetchone()[0]
                    tx_sq = t_qty * ratio if t_unit == units[0] else t_qty
                    if t_type == "出貨" and tx_sq > sq: st.error("❌ 庫存不足")
                    else:
                        c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                                  (target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                        conn.commit(); st.success("✅ 登記成功"); st.balloons()

# --- 設定 ---
elif choice == "🍎 商品維護設定":
    st.subheader("🍎 商品建檔與編輯")
    quick_action_menu()
    c.execute("SELECT name FROM products")
    exists = ["+ 新增商品"] + [r[0] for r in c.fetchall()]
    mode = st.selectbox("編輯對象", exists)
    iv = {"n":"","c":0.0,"p":0.0,"bu":"箱","su":"顆","r":10,"d":"","img":None}
    if mode != "+ 新增商品":
        c.execute("SELECT * FROM products WHERE name=?", (mode,))
        p = c.fetchone()
        if p: iv = {"n":p[0],"c":p[1],"p":p[2],"bu":p[3],"su":p[4],"r":p[5],"img":p[7],"d":p[8]}

    name = st.text_input("品名", value=iv["n"])
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
