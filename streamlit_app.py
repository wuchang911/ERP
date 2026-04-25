import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime

# --- 1. 系統初始化 (iOS/PWA 優化) ---
st.set_page_config(page_title="AI 智慧 ERP", layout="wide", initial_sidebar_state="collapsed")

# 資料庫連線 (版本 v8)
conn = sqlite3.connect('erp_master_v8.db', check_same_thread=False)
c = conn.cursor()

def init_db():
    c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT UNIQUE, password TEXT, role TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS products 
                 (name TEXT UNIQUE, barcode TEXT, cost REAL, price REAL, big_unit TEXT, 
                  small_unit TEXT, ratio INTEGER, alert_level INTEGER, image_data TEXT, description TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs 
                 (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, 
                  price_at_time REAL, date TEXT, operator TEXT)''')
    c.execute("INSERT OR IGNORE INTO users VALUES ('admin', '8888', 'admin')")
    conn.commit()

init_db()

# --- 2. 核心計算工具 ---
def get_detailed_stats(name):
    c.execute("SELECT big_unit, small_unit, ratio, cost, price, alert_level FROM products WHERE name=?", (name,))
    p = c.fetchone()
    if not p: return None
    big_u, small_u, ratio, cost, price, alert = p
    ratio = ratio if ratio and ratio > 0 else 1
    alert = alert if alert is not None else 5
    
    logs_df = pd.read_sql_query("SELECT type, qty, unit FROM logs WHERE name=?", conn, params=(name,))
    total_small_qty = 0
    for _, row in logs_df.iterrows():
        real_q = row['qty'] * ratio if row['unit'] == big_u else row['qty']
        if '進貨' in row['type'] or '盤點(進)' in row['type']: 
            total_small_qty += real_q
        else:
            total_small_qty -= real_q

    boxes = total_small_qty // ratio
    units = total_small_qty % ratio
    is_low = total_small_qty <= alert

    return {
        "qty": total_small_qty, 
        "display": f"{int(boxes)} {big_u} {int(units)} {small_u}", 
        "is_low": is_low, "alert_val": alert, 
        "big_u": big_u, "small_u": small_u, "ratio": ratio, "price": price, "cost": cost
    }

# --- 3. 登入系統 ---
if "user" not in st.session_state:
    st.title("🔐 AI 智慧 ERP 系統")
    with st.container(border=True):
        u = st.text_input("帳號")
        p = st.text_input("密碼", type="password")
        if st.button("登入系統", use_container_width=True, type="primary"):
            c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
            res = c.fetchone()
            if res:
                st.session_state["user"], st.session_state["role"] = str(res[0]), str(res[1])
                st.rerun()
            else: st.error("❌ 帳密錯誤")
    st.stop()

current_user, current_role = st.session_state["user"], st.session_state["role"]

# --- 4. 導覽選單 ---
st.sidebar.markdown(f"👤 **{current_user}** ({current_role})")
menu = ["庫存報表", "交易登記", "歷史紀錄"]
if current_role == "admin": menu += ["商品管理", "帳號管理"]
choice = st.sidebar.selectbox("切換功能", menu)
if st.sidebar.button("登出系統"): st.session_state.clear(); st.rerun()

# --- 5. 模組內容 ---
if choice == "庫存報表":
    st.subheader("📦 庫存即時狀態")
    c.execute("SELECT name, image_data FROM products")
    items = c.fetchall()
    
    # 採購建議看板
    purchase_needed = []
    for (name, _) in items:
        s = get_detailed_stats(name)
        if s["is_low"]:
            suggest = (s["alert_val"] * 2) - s["qty"]
            purchase_needed.append({"商品": name, "目前庫存": s["display"], "建議採購量": f"{int(suggest)} {s['small_u']}"})
    
    if purchase_needed:
        with st.expander("🚨 低庫存採購建議清單", expanded=True):
            df_p = pd.DataFrame(purchase_needed)
            st.table(df_p)
            st.download_button("📥 下載採購單 (CSV)", df_p.to_csv(index=False).encode('utf-8-sig'), "purchase.csv", use_container_width=True)

    # 卡片展示區
    cols = st.columns(2)
    for idx, (name, img) in enumerate(items):
        s = get_detailed_stats(name)
        with cols[idx % 2]:
            with st.container(border=True):
                if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                st.markdown(f"### {name}")
                if s["is_low"]:
                    st.error(f"❌ 庫存: {s['display']}")
                    st.caption(f"已低於預警值: {s['alert_val']} {s['small_u']}")
                else:
                    st.success(f"✅ 庫存: {s['display']}")

elif choice == "交易登記":
    st.subheader("📝 庫存登記異動")
    c.execute("SELECT name FROM products")
    prods = [r[0] for r in c.fetchall()]
    if not prods: st.warning("請先建立商品"); st.stop()
    
    target = st.selectbox("選定商品", prods)
    s = get_detailed_stats(target)
    st.info(f"當前庫存：{s['display']}")
    
    t1, t2 = st.tabs(["🛒 一般買賣", "🔒 盤點鎖定"]) if current_role == "admin" else (st.tabs(["🛒 一般買賣"])[0], None)
    
    with t1:
        with st.form("trade_f", clear_on_submit=True):
            tt = st.radio("類型", ["進貨", "出貨"], horizontal=True)
            tu = st.selectbox("單位", [s["big_u"], s["small_u"]])
            tq = st.number_input("數量", min_value=1, step=1)
            tp = st.number_input("單價", value=s["price"] if tt=="出貨" else s["cost"])
            if st.form_submit_button("確認提交", use_container_width=True):
                req_small = tq * s["ratio"] if tu == s["big_u"] else tq
                if tt == "出貨" and req_small > s["qty"]:
                    st.error("庫存不足！")
                else:
                    c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                              (target, tt, tq, tu, tp, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                    conn.commit(); st.success("登記完成"); st.rerun()

    if t2 and current_role == "admin":
        with t2:
            with st.form("stock_f"):
                nb, nu = st.number_input(f"現場 {s['big_u']}", 0), st.number_input(f"現場 {s['small_u']}", 0)
                if st.form_submit_button("執行盤點校正", use_container_width=True):
                    diff = (nb * s["ratio"] + nu) - s["qty"]
                    if diff != 0:
                        adj = "盤點(進)" if diff > 0 else "盤點(出)"
                        c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                                  (target, adj, abs(diff), s['small_u'], 0, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                        conn.commit(); st.success("庫存已鎖定校正"); st.rerun()

elif choice == "歷史紀錄":
    st.subheader("📜 歷史卡片明細")
    df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC LIMIT 50", conn)
    for _, row in df.iterrows():
        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            col1.write(f"**{row['name']}** ({row['type']})")
            col1.caption(f"{row['date']} | 經手: {row['operator']}")
            col2.write(f"**{row['qty']}** {row['unit']}")
            if current_role == "admin" and col2.button("🗑️", key=f"d_{row['id']}"):
                c.execute("DELETE FROM logs WHERE id=?", (row['id'],)); conn.commit(); st.rerun()

elif choice == "商品管理":
    st.subheader("⚙️ 商品建檔與預警設定")
    c.execute("SELECT name FROM products")
    existing = ["+ 新增商品"] + [r[0] for r in c.fetchall()]
    mode = st.selectbox("模式", existing)
    
    with st.form("p_form"):
        pn = st.text_input("商品名稱", value="" if mode=="+ 新增商品" else mode)
        c1, c2, c3 = st.columns(3)
        p_b, p_s, p_r = c1.text_input("大單位", "箱"), c2.text_input("小單位", "罐"), c3.number_input("換算比", 1)
        al = st.number_input("低庫存預警值 (小單位)", value=5)
        p_i = st.file_uploader("圖片")
        if st.form_submit_button("💾 儲存資訊", use_container_width=True):
            b64 = ""
            if p_i:
                img = Image.open(p_i).convert("RGB"); img.thumbnail((300, 300))
                buf = io.BytesIO(); img.save(buf, format="JPEG"); b64 = base64.b64encode(buf.getvalue()).decode()
            if mode == "+ 新增商品":
                c.execute("INSERT INTO products (name, big_unit, small_unit, ratio, alert_level, image_data) VALUES (?,?,?,?,?,?)", (pn, p_b, p_s, p_r, al, b64))
            else:
                c.execute("UPDATE products SET big_unit=?, small_unit=?, ratio=?, alert_level=?, image_data=? WHERE name=?", (p_b, p_s, p_r, al, b64, mode))
            conn.commit(); st.success("✅ 已儲存"); st.rerun()

elif choice == "帳號管理":
    st.subheader("👥 帳號控管")
    with st.form("u_f"):
        nu, np, nr = st.text_input("帳號"), st.text_input("密碼"), st.selectbox("權限", ["staff", "admin"])
        if st.form_submit_button("新增"):
            try: c.execute("INSERT INTO users VALUES (?,?,?)", (nu, np, nr)); conn.commit(); st.success("成功"); st.rerun()
            except: st.error("帳號已存在")
