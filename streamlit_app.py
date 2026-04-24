import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime
import google.generativeai as genai

# --- 1. 系統初始化 ---
st.set_page_config(page_title="AI 智慧 ERP", layout="wide", initial_sidebar_state="collapsed")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

# 資料庫連線 (建議升級版本號以刷新)
conn = sqlite3.connect('erp_master_v3.db', check_same_thread=False)
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
    logs_df = pd.read_sql_query("SELECT type, qty, unit, price_at_time FROM logs WHERE name=?", conn, params=(name,))
    total_qty, profit = 0, 0
    u_cost = (cost / ratio if ratio > 0 else 0)
    
    for _, row in logs_df.iterrows():
        real_q = row['qty'] * ratio if row['unit'] == big_u else row['qty']
        if '進貨' in row['type'] or '盤點' in row['type'] and '進' in row['type']: 
            total_qty += real_q
        else:
            total_qty -= real_q
            profit += (row['qty'] * row['price_at_time']) - (real_q * u_cost)

    boxes = total_qty // ratio if ratio > 0 else 0
    units = total_qty % ratio if ratio > 0 else total_qty
    return {"qty": total_qty, "display": f"{int(boxes)} {big_u} {int(units)} {small_u}", 
            "profit": profit, "is_alert": total_qty <= (alert or 0), "ratio": ratio, 
            "big_u": big_u, "small_u": small_u, "price": price, "cost": cost}

# --- 3. 登入系統 (格式強化版) ---
if "user" not in st.session_state:
    st.title("🔐 AI 智慧 ERP")
    with st.container(border=True):
        u = st.text_input("帳號")
        p = st.text_input("密碼", type="password")
        if st.button("登入系統", use_container_width=True, type="primary"):
            c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
            res = c.fetchone()
            if res:
                st.session_state["user"] = str(res[0])
                st.session_state["role"] = str(res[1])
                st.rerun()
            else: st.error("❌ 帳密錯誤")
    st.stop()

current_user, current_role = st.session_state["user"], st.session_state["role"]

# --- 4. 導覽與選單 ---
st.sidebar.markdown(f"👤 **{current_user}** ({current_role})")
menu = ["庫存報表", "交易登記", "歷史紀錄"]
if current_role == "admin": menu += ["商品管理", "帳號管理"]
choice = st.sidebar.selectbox("切換功能", menu)
if st.sidebar.button("登出"): st.session_state.clear(); st.rerun()

# --- 5. 功能模組 ---
if choice == "庫存報表":
    st.subheader("📦 庫存即時狀態")
    c.execute("SELECT name, image_data FROM products")
    items = c.fetchall()
    if items:
        cols = st.columns(2)
        for idx, (name, img) in enumerate(items):
            s = get_detailed_stats(name)
            with cols[idx % 2]:
                with st.container(border=True):
                    if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
                    st.write(f"**{name}**")
                    if s["is_alert"]: st.error(f"⚠️ {s['display']}")
                    else: st.success(f"庫存: {s['display']}")
    else: st.info("目前無商品，請管理員建檔")

elif choice == "交易登記":
    st.subheader("📝 登記異動")
    c.execute("SELECT name FROM products")
    prods = [r[0] for r in c.fetchall()]
    if prods:
        target = st.selectbox("選定商品", prods)
        s = get_detailed_stats(target)
        st.info(f"現庫存：{s['display']}")
        tabs = st.tabs(["🛒 一般買賣", "🔒 盤點校正"]) if current_role == "admin" else st.tabs(["🛒 一般買賣"])
        with tabs[0]:
            with st.form("tr", clear_on_submit=True):
                tt, tu = st.radio("類型", ["進貨", "出貨"], 0, horizontal=True), st.selectbox("單位", [s["big_u"], s["small_u"]])
                tq, tp = st.number_input("數量", 1), st.number_input("單價", value=s["price"] if tt=="出貨" else s["cost"])
                if st.form_submit_button("確認提交", use_container_width=True):
                    c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                              (target, tt, tq, tu, tp, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                    conn.commit(); st.success("完成"); st.rerun()
        if current_role == "admin":
            with tabs[1]:
                with st.form("st"):
                    nb, nu = st.number_input(f"現場{s['big_u']}", 0), st.number_input(f"現場{s['small_u']}", 0)
                    if st.form_submit_button("🔒 盤點鎖定", use_container_width=True):
                        diff = (nb * s["ratio"] + nu) - s["qty"]
                        if diff != 0:
                            c.execute("INSERT INTO logs (name, type, qty, unit, price_at_time, date, operator) VALUES (?,?,?,?,?,?,?)",
                                      (target, f"盤點校正({'進' if diff>0 else '出'})", abs(diff), s['small_u'], 0, datetime.now().strftime("%Y-%m-%d %H:%M"), current_user))
                            conn.commit(); st.success("已校正"); st.rerun()

elif choice == "歷史紀錄":
    st.subheader("📜 歷史卡片明細")
    logs_df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC LIMIT 50", conn)
    for i, row in logs_df.iterrows():
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"**{row['name']}** | {row['type']}\n\n`{row['date']}` 操作: {row['operator']}")
            c2.write(f"**{row['qty']}** {row['unit']}")
            if current_role == "admin" and c2.button("🗑️", key=f"d_{row['id']}"):
                c.execute("DELETE FROM logs WHERE id=?", (row['id'],)); conn.commit(); st.rerun()

elif choice == "商品管理":
    st.subheader("⚙️ 商品建檔")
    c.execute("SELECT name FROM products")
    names = ["+ 新增"] + [r[0] for r in c.fetchall()]
    mode = st.selectbox("模式", names)
    with st.form("pf"):
        pn = st.text_input("名稱", value="" if mode=="+ 新增" else mode)
        pb, pc, pp = st.text_input("條碼"), st.number_input("成本"), st.number_input("售價")
        c1, c2, c3 = st.columns(3)
        p_b, p_s, p_r = c1.text_input("大單位"), c2.text_input("小單位"), c3.number_input("換算比", 1)
        p_i = st.file_uploader("圖片")
        if st.form_submit_button("儲存"):
            b64 = ""
            if p_i:
                img = Image.open(p_i).convert("RGB"); img.thumbnail((300, 300))
                buf = io.BytesIO(); img.save(buf, format="JPEG"); b64 = base64.b64encode(buf.getvalue()).decode()
            if mode == "+ 新增": c.execute("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?)", (pn, pb, pc, pp, p_b, p_s, p_r, 5, b64, ""))
            else: c.execute("UPDATE products SET barcode=?, cost=?, price=?, big_unit=?, small_unit=?, ratio=?, image_data=? WHERE name=?", (pb, pc, pp, p_b, p_s, p_r, b64, mode))
            conn.commit(); st.success("成功"); st.rerun()

elif choice == "帳號管理":
    st.subheader("👥 帳號控管")
    with st.form("au"):
        nu, np, nr = st.text_input("帳號"), st.text_input("密碼"), st.selectbox("角色", ["staff", "admin"])
        if st.form_submit_button("新增使用者"):
            try: c.execute("INSERT INTO users VALUES (?,?,?)", (nu, np, nr)); conn.commit(); st.success("成功"); st.rerun()
            except: st.error("重複")
    st.write("目前帳號")
    udf = pd.read_sql_query("SELECT username, role FROM users", conn)
    st.table(udf)
