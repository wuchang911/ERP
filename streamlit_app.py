import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 1. 資料庫初始化與欄位自動修復 ---
conn = sqlite3.connect('business_pro_v8.db', check_same_thread=False)
c = conn.cursor()

# 建立所有必要表格
c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT UNIQUE, password TEXT, role TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS products 
             (name TEXT UNIQUE, cost REAL, price REAL, big_unit TEXT, small_unit TEXT, 
              ratio INTEGER, alert_level INTEGER, image_data TEXT, description TEXT, created_by TEXT, created_at TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS logs 
             (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, 
              price_at_time REAL, date TEXT, operator TEXT)''')

# 初始化管理員 (預設 admin / 8888)
c.execute("INSERT OR IGNORE INTO users VALUES ('admin', '8888', 'admin')")
conn.commit()

# --- 2. 登入系統邏輯 ---
def login_screen():
    if "user" not in st.session_state:
        st.title("🔒 企業進銷存管理系統")
        u = st.text_input("帳號")
        p = st.text_input("密碼", type="password")
        if st.button("確認登入"):
            c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
            res = c.fetchone()
            if res:
                st.session_state["user"], st.session_state["role"] = res[0], res[1]
                st.rerun()
            else: st.error("❌ 帳號或密碼錯誤")
        st.stop()

login_screen()
current_user = st.session_state["user"]
current_role = st.session_state["role"]

# --- 3. 工具函數 (照片、庫存與毛利計算) ---
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
    total_small_qty, total_profit, small_unit_cost = 0, 0, (cost / ratio if ratio > 0 else 0)
    
    for t, q, u, p_at_time in logs:
        tx_small_qty = q * ratio if u == big_u else q
        if t == '進貨': total_small_qty += tx_small_qty
        else:
            total_small_qty -= tx_small_qty
            total_profit += (q * p_at_time) - (tx_small_qty * small_unit_cost)
    
    display_stock = f"{total_small_qty // ratio} {big_u} {total_small_qty % ratio} {small_u}"
    return total_small_qty, total_profit, display_stock, ratio

# --- 4. 側邊欄：管理功能與計算機 ---
st.sidebar.title(f"👤 {current_user} ({'管理員' if current_role=='admin' else '員工'})")

# 🧮 簡易計算機
calc_exp = st.sidebar.text_input("🧮 簡易計算機 (如: 500*12)")
if calc_exp:
    try:
        res = eval(calc_exp.replace('x', '*').replace('÷', '/'), {"__builtins__": None}, {})
        st.sidebar.success(f"結果: {res}")
    except: st.sidebar.caption("支援 + - * /")

# 🔒 系統控制與帳號管理 (僅限管理員)
system_lock = False
if current_role == "admin":
    with st.sidebar.expander("⚙️ 管理員工具"):
        # 帳號管理
        st.write("👤 帳號管理")
        new_u = st.text_input("新增帳號")
        new_p = st.text_input("密碼", type="password")
        if st.button("更新/建立員工帳號"):
            c.execute("INSERT OR REPLACE INTO users VALUES (?,?,'staff')", (new_u, new_p))
            conn.commit(); st.success(f"帳號 {new_u} 已就緒")
        
        st.divider()
        # 盤點鎖定
        system_lock = st.toggle("🔒 盤點鎖定模式", value=False)
        if system_lock: st.warning("系統盤點鎖定中")
        
        # 清除功能
        if st.checkbox("🔥 清空交易歷史紀錄"):
            if st.button("確認執行清空"):
                c.execute("DELETE FROM logs"); conn.commit(); st.rerun()

st.sidebar.divider()
if st.sidebar.button("🚪 登出系統"):
    del st.session_state["user"]; st.rerun()

# --- 5. 主功能切換 ---
menu = ["📊 庫存監控與報表", "📝 進出貨登記"]
if current_role == "admin": menu.append("🍎 商品設定維護")
choice = st.sidebar.selectbox("切換功能", menu)

# --- 功能 1：庫存報表與追溯 ---
if choice == "📊 庫存監控與報表":
    st.subheader("📦 即時庫存監控")
    c.execute("SELECT name, image_data, description, created_by FROM products")
    prods = c.fetchall()
    
    if not prods: st.info("💡 目前尚無商品資料，請先前往『商品設定』。")
    else:
        all_profit = 0
        cols = st.columns(2 if st.sidebar.checkbox("手機模式", True) else 4)
        for idx, (n, img, desc, creator) in enumerate(prods):
            s_qty, profit, d_stock, _ = get_stock_and_profit(n)
            all_profit += profit
            with cols[idx % len(cols)]:
                if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                st.markdown(f"**{n}**")
                st.markdown(f"庫存：**{d_stock}**")
                if desc: 
                    with st.expander("📝 詳細敘述"): st.write(desc)
                st.caption(f"建檔人: {creator}")
                st.divider()
        
        if current_role == "admin":
            st.sidebar.metric("總預估毛利", f"${all_profit:,.0f} TW$")

    st.subheader("📜 歷史交易追溯")
    history_df = pd.read_sql_query("SELECT name as 品項, type as 類型, qty as 數量, unit as 單位, price_at_time as 單價, operator as 操作員, date as 時間 FROM logs ORDER BY id DESC", conn)
    st.dataframe(history_df, use_container_width=True)
    
    # 匯出功能
    csv = history_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 匯出歷史明細 (CSV)", data=csv, file_name=f"ERP_History_{datetime.now().strftime('%Y%m%d')}.csv", mime='text/csv')

# --- 功能 2：進出貨登記 (支援掃描) ---
elif choice == "📝 進出貨登記":
    st.subheader("📝 登記進銷貨")
    if system_lock: st.error("🛑 系統盤點鎖定中，目前僅供查看。")
    else:
        st.info("💡 iPhone 使用者點擊下方輸入框後，可使用鍵盤內建的『掃描條碼』功能。")
        scan_code = st.text_input("📷 掃描條碼或手動搜尋", placeholder="點擊此處進行掃描...")
        
        c.execute("SELECT name, big_unit, small_unit FROM products")
        p_data = c.fetchall()
        p_names = [p[0] for p in p_data]
        
        idx = p_names.index(scan_code) if scan_code in p_names else 0
        target = st.selectbox("確認品項", options=p_names, index=idx)
        
        if target:
            u_info = [p for p in p_data if p[0] == target][0]
            s_qty, _, d_stock, _ = get_stock_and_profit(target)
            st.info(f"💡 目前庫存：{d_stock}")
            
            with st.form("trade_form"):
                t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
                colq, colu = st.columns(2)
                with colq: t_qty = st.number_input("數量", min_value=1, step=1)
                with colu: t_unit = st.selectbox("單位", options=[u_info[1], u_info[2]])
                
                t_price = st.number_input("此筆交易單價 (TW$)", min_value=0.0)
                t_date = st.date_input("日期", datetime.now())
                
                if st.form_submit_button("確認提交紀錄"):
                    c.execute("SELECT ratio FROM products WHERE name=?", (target,))
                    ratio = c.fetchone()[0]
                    tx_small_qty = t_qty * ratio if t_unit == u_info[1] else t_qty
                    
                    if t_type == "出貨" and tx_small_qty > s_qty:
                        st.error(f"❌ 庫存不足！現有 {s_qty}，需求 {tx_small_qty}")
                    else:
                        now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)", 
                                  (target, t_type, t_qty, t_unit, t_price, now_time, current_user))
                        conn.commit(); st.success("✅ 登記成功！"); st.balloons()

# --- 功能 3：商品設定 (含自動定價與編輯) ---
elif choice == "🍎 商品設定維護":
    st.subheader("🍎 商品建檔與智慧定價")
    c.execute("SELECT name FROM products")
    existing_list = ["+ 新增商品"] + [r[0] for r in c.fetchall()]
    mode = st.selectbox("選擇操作對象", existing_list)
    
    iv = {"n": "", "cost": 0.0, "price": 0.0, "bu": "箱", "su": "顆", "r": 10, "a": 5, "desc": "", "img": None}
    if mode != "+ 新增商品":
        c.execute("SELECT * FROM products WHERE name=?", (mode,))
        p = c.fetchone()
        if p: iv = {"n": p[0], "cost": p[1], "price": p[2], "bu": p[3], "su": p[4], "r": p[5], "a": p[6], "img": p[7], "desc": p[8]}

    # 即時重複提醒邏輯
    name = st.text_input("商品名稱 (條碼)", value=iv["n"])
    if mode == "+ 新增商品" and name in existing_list:
        st.warning(f"⚠️ 注意：『{name}』已存在，儲存將覆蓋舊資料。")

    col_u1, col_u2, col_r = st.columns(3)
    with col_u1: b_u = st.text_input("大單位", value=iv["bu"])
    with col_u2: s_u = st.text_input("最小單位", value=iv["su"])
    with col_r: ratio = st.number_input(f"換算率 (1{b_u}=?{s_u})", min_value=1, value=iv["r"])

    col_c, col_p = st.columns(2)
    with col_c: cost = st.number_input(f"整{b_u}進貨總成本 ($)", min_value=0.0, value=iv["cost"])
    u_cost = cost/ratio if ratio>0 else 0
    st.caption(f"💡 單{s_u}成本約 ${u_cost:.2f}")

    with col_p:
        margin = st.slider("預設利潤率 (%)", 0, 100, 30)
        suggested = u_cost * (1 + margin/100)
        price = st.number_input(f"單一{s_u}銷售售價 ($)", value=float(suggested if mode=="+ 新增商品" else iv["price"]))

    with st.form("prod_form"):
        alert = st.number_input("預警水位 (以小單位計)", value=iv["a"])
        description = st.text_area("詳細敘述 (規格、產地等)", value=iv["desc"])
        cam = st.camera_input("商品拍照")
        
        if st.form_submit_button("儲存資料同步至雲端"):
            if not name: st.error("❌ 請輸入名稱")
            else:
                final_img = image_to_base64(cam) if cam else iv["img"]
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                c.execute("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (name, cost, price, b_u, s_u, ratio, alert, final_img, description, current_user, now_str))
                conn.commit(); st.success(f"🎉 '{name}' 更新成功！"); st.balloons()
