import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 1. 資料庫初始化 (自動修復舊欄位) ---
conn = sqlite3.connect('business_pro_v6.db', check_same_thread=False)
c = conn.cursor()

# 建立基礎表格
c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT UNIQUE, password TEXT, role TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS products 
             (name TEXT UNIQUE, cost REAL, price REAL, big_unit TEXT, small_unit TEXT, 
              ratio INTEGER, alert_level INTEGER, image_data TEXT, description TEXT, created_by TEXT, created_at TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS logs 
             (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, 
              price_at_time REAL, date TEXT, operator TEXT)''')

# --- 💡 關鍵修復：手動補齊可能缺失的欄位 ---
try: c.execute("ALTER TABLE logs ADD COLUMN operator TEXT"); conn.commit()
except: pass
try: c.execute("ALTER TABLE products ADD COLUMN description TEXT"); conn.commit()
except: pass

c.execute("INSERT OR IGNORE INTO users VALUES ('admin', '8888', 'admin')")
conn.commit()

# --- 2. 登入系統 ---
if "user" not in st.session_state:
    st.title("🔒 企業進銷存系統登入")
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

# --- 3. 工具函數 ---
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

# --- 4. 側邊欄 ---
st.sidebar.title(f"👤 {st.session_state['user']}")
if st.session_state["role"] == "admin":
    with st.sidebar.expander("👤 帳號管理"):
        new_u = st.text_input("新增員工帳號")
        new_p = st.text_input("密碼設定", type="password")
        if st.button("建立"):
            c.execute("INSERT OR REPLACE INTO users VALUES (?,?,'staff')", (new_u, new_p))
            conn.commit(); st.success(f"已建立 {new_u}")
    system_lock = st.sidebar.toggle("🔒 盤點鎖定", value=False)
else: system_lock = False

if st.sidebar.button("登出系統"):
    del st.session_state["user"]; st.session_state.pop("role"); st.rerun()

# --- 5. 主選單 ---
menu = ["📊 庫存報表", "📝 進出貨登記", "🍎 商品設定"]
if st.session_state["role"] != "admin": menu.remove("🍎 商品設定")
choice = st.sidebar.selectbox("切換功能", menu)

# --- 功能：進出貨登記 (BUG 修正核心) ---
if choice == "📝 進出貨登記":
    st.subheader("📝 手動進銷貨登記")
    if system_lock: st.error("🛑 系統鎖定中，暫停登記")
    else:
        c.execute("SELECT name, big_unit, small_unit FROM products")
        prods = c.fetchall()
        if not prods: st.warning("⚠️ 請先前往『商品設定』建立商品")
        else:
            # 修正：提取純文字列表，避免 selectbox 報錯
            p_names = [p[0] for p in prods]
            target_p = st.selectbox("品項選擇", options=p_names)
            
            # 抓取該品項單位資訊
            c.execute("SELECT big_unit, small_unit FROM products WHERE name=?", (target_p,))
            units_info = c.fetchone()
            
            with st.form("trade_form"):
                t_type = st.radio("類型", ["進貨", "出貨"], horizontal=True)
                s_qty, _, d_stock, _ = get_stock_and_profit(target_p)
                st.info(f"💡 目前庫存：{d_stock}")
                
                col1, col2 = st.columns(2)
                with col1: t_qty = st.number_input("數量", min_value=1, step=1)
                with col2: t_unit = st.selectbox("單位", options=list(units_info)) # 確保為字串清單
                
                t_price = st.number_input("單價 (TW$)", min_value=0.0)
                # 💡 重要：form 內必須有 submit button 且不能有 if 回調
                submitted = st.form_submit_button("確認提交紀錄")
                
                if submitted:
                    c.execute("SELECT ratio FROM products WHERE name=?", (target_p,))
                    ratio = c.fetchone()[0]
                    tx_small_qty = t_qty * ratio if t_unit == units_info[0] else t_qty
                    
                    if t_type == "出貨" and tx_small_qty > s_qty:
                        st.error("❌ 庫存不足！")
                    else:
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)", 
                                  (target_p, t_type, t_qty, t_unit, t_price, now_str, st.session_state["user"]))
                        conn.commit(); st.success("✅ 登記成功！"); st.balloons()

# --- 其餘功能保持穩定性 ---
elif choice == "📊 庫存報表":
    st.subheader("📦 即時庫存報表")
    c.execute("SELECT name, image_data, description FROM products")
    for n, img, desc in c.fetchall():
        s_qty, profit, d_stock, _ = get_stock_and_profit(n)
        st.write(f"### {n}")
        if img: st.image(f"data:image/jpeg;base64,{img}", width=200)
        st.write(f"庫存：{d_stock}")
        if st.session_state["role"] == "admin": st.write(f"預估利潤：${profit:,.0f}")
        st.divider()

elif choice == "🍎 商品設定":
    st.subheader("🍎 商品維護")
    with st.form("new_p_form"):
        n = st.text_input("商品名")
        b, s, r = st.text_input("大單位", value="箱"), st.text_input("小單位", value="顆"), st.number_input("換算率", min_value=1)
        cost, price = st.number_input("成本"), st.number_input("售價")
        desc = st.text_area("描述")
        cam = st.camera_input("拍照")
        if st.form_submit_button("儲存"):
            img_b = image_to_base64(cam)
            c.execute("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (n, cost, price, b, s, r, 5, img_b, desc, st.session_state["user"], datetime.now().strftime("%Y-%m-%d")))
            conn.commit(); st.success("已更新"); st.rerun()
