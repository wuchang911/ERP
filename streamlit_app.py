import streamlit as st
import pandas as pd
import sqlite3
import base64
from PIL import Image
import io
from datetime import datetime
import google.generativeai as genai
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
--- 1. 初始化 (移除導致亂碼的 HTML 設定) ---
st.set_page_config(page_title="ERP 智慧進銷存 Pro", layout="wide")
鎖定 API Key
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
資料庫連線 (建議升級版本號以刷新結構)
conn = sqlite3.connect('erp_v50.db', check_same_thread=False)
c = conn.cursor()
def init_db():
c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT UNIQUE, password TEXT, role TEXT)')
c.execute('CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE, cost REAL, price REAL, big_unit TEXT, small_unit TEXT, ratio INTEGER, alert_level INTEGER, image_data TEXT, description TEXT)')
c.execute('CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, name TEXT, type TEXT, qty INTEGER, unit TEXT, price_at_time REAL, date TEXT, operator TEXT)')
c.execute("INSERT OR IGNORE INTO users VALUES ('admin', '8888', 'admin')")
conn.commit()
init_db()
--- 2. 工具函數 ---
def get_product_stats(name):
c.execute("SELECT big_unit, small_unit, ratio, cost, price, alert_level FROM products WHERE name=?", (name,))
p = c.fetchone()
if not p: return None
big_u, small_u, ratio, cost, price, alert = p
logs_df = pd.read_sql_query("SELECT type, qty, unit, price_at_time FROM logs WHERE name=?", conn, params=(name,))
small_qty, profit = 0, 0
u_cost = (cost / ratio if ratio > 0 else 0)
for _, row in logs_df.iterrows():
real_q = row['qty'] * ratio if row['unit'] == big_u else row['qty']
if row['type'] == '進貨': small_qty += real_q
else:
small_qty -= real_q
profit += (row['qty'] * row['price_at_time']) - (real_q * u_cost)
return {
"qty": small_qty, "display": f"{small_qty // ratio} {big_u} {small_qty % ratio} {small_u}",
"profit": profit, "is_alert": small_qty <= (alert or 0),
"ratio": ratio, "big_u": big_u, "small_u": small_u, "price": price, "cost": cost
}
def generate_pdf():
buf = io.BytesIO()
p = canvas.Canvas(buf, pagesize=A4)
p.drawString(50, 800, f"Stock Report - {datetime.now().strftime('%Y-%m-%d')}")
y = 770
c.execute("SELECT name FROM products")
for (n,) in c.fetchall():
s = get_product_stats(n)
p.drawString(50, y, f"Prod: {n} | Stock: {s['display']} | Profit: ${s['profit']:,.0f}")
y -= 20
p.save(); buf.seek(0); return buf
--- 3. 登入邏輯 (徹底解決 ('admin', 'admin') 元組問題) ---
if "user" not in st.session_state:
st.title("🔐 系統登入")
with st.container(border=True):
u = st.text_input("帳號")
p = st.text_input("密碼", type="password")
if st.button("確認進入", use_container_width=True):
c.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
res = c.fetchone()
if res:
st.session_state["user"] = str(res[0]) # 強制轉字串
st.session_state["role"] = str(res[1]) # 強制轉字串
st.rerun()
else: st.error("❌ 帳密錯誤")
st.stop()
current_user = st.session_state["user"]
current_role = st.session_state["role"]
--- 4. 導覽選單 ---
menu = ["📊 庫存戰情室", "📝 進出貨登記"]
if current_role == "admin":
menu += ["🍎 商品檔案管理", "👥 使用者帳號管理"]
choice = st.sidebar.selectbox("功能選單", menu)
if st.sidebar.button("🚪 登出"):
st.session_state.clear(); st.rerun()
--- 5. 功能實作 ---
if choice == "📊 庫存戰情室":
st.subheader("📊 庫存即時戰情")
# 頂部管理員工具箱 (修復截圖中的排版破碎)
if current_role == "admin":
with st.expander("🛠️ 管理員智慧工具箱", expanded=True):
c1, c2, c3 = st.columns(3)
if c1.button("✨ AI 數據診斷", use_container_width=True):
with st.spinner("AI 正在閱讀報表..."):
c.execute("SELECT name FROM products")
inv = [f"{n}: {get_product_stats(n)['display']}" for (n,) in c.fetchall()]
genai.configure(api_key=GEMINI_API_KEY)
try:
model = genai.GenerativeModel('gemini-1.5-flash')
res = model.generate_content(f"分析庫存：{str(inv)}。請給3點補貨建議（繁中）。")
st.info(res.text)
except Exception as e: st.error(f"AI 連線失敗: {e}")
c2.download_button("📥 匯出 PDF", generate_pdf(), f"Report_{datetime.now().date()}.pdf", "application/pdf", use_container_width=True)
h_df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC", conn)
c3.download_button("📥 匯出 CSV", h_df.to_csv(index=False).encode('utf-8-sig'), "history.csv", "text/csv", use_container_width=True)
st.session_state.is_locked = st.toggle("🔒 盤點鎖定模式", value=st.session_state.get("is_locked", False))
# 庫存展示 (修正卡片不顯示問題)
c.execute("SELECT name, image_data, description FROM products")
prods = c.fetchall()
if not prods:
st.info("目前庫存空空如也，請先前往「商品檔案管理」建檔。")
else:
cols = st.columns(2 if st.sidebar.checkbox("手機版顯示", True) else 4)
for i, (n, img, desc) in enumerate(prods):
s = get_product_stats(n)
with cols[i % len(cols)]:
with st.container(border=True):
if img: st.image(f"data:image/jpeg;base64,{img}", use_container_width=True)
st.markdown(f"{n}")
if s["is_alert"]: st.error(f"⚠️ 庫存: {s['display']}")
else: st.success(f"📦 庫存: {s['display']}")
st.subheader("📜 最近異動紀錄")
st.dataframe(pd.read_sql_query("SELECT id, name, type, qty, unit, date FROM logs ORDER BY id DESC LIMIT 10", conn), use_container_width=True)
elif choice == "📝 進出貨登記":
st.subheader("📝 登記進銷貨")
if st.session_state.get("is_locked", False):
st.error("🛑 系統鎖定中，請聯繫管理員解鎖。")
else:
c.execute("SELECT name FROM products")
names = [r[0] for r in c.fetchall()]
scan = st.text_input("🔍 搜尋品項或掃描")
target = st.selectbox("選定商品", names, index=names.index(scan) if scan in names else 0)
if target:
s = get_product_stats(target)
st.info(f"💡 當前庫存：{s['display']}")
with st.form("trade", clear_on_submit=True):
t_type = st.radio("作業類型", ["進貨", "出貨"], horizontal=True)
t_qty = st.number_input("數量", min_value=1, value=1)
t_unit = st.selectbox("使用單位", [s["big_u"], s["small_u"]])
t_price = st.number_input("成交單價", value=s["price"] if t_type=="出貨" else s["cost"])
if st.form_submit_button("✅ 確認提交並返回"):
tx = t_qty * s["ratio"] if t_unit == s["big_u"] else t_qty
if t_type == "出貨" and tx > s["qty"]: st.error("❌ 庫存不足")
else:
c.execute("INSERT INTO logs (name,type,qty,unit,price_at_time,date,operator) VALUES (?,?,?,?,?,?,?)",
(target, t_type, t_qty, t_unit, t_price, datetime.now().strftime("%m-%d %H:%M"), current_user))
conn.commit(); st.success("登記完成！"); st.rerun()
elif choice == "🍎 商品檔案管理":
st.subheader("🍎 商品檔案建檔")
c.execute("SELECT name FROM products")
existing = ["+ 新增商品"] + [r[0] for r in c.fetchall()]
mode = st.selectbox("選擇商品", existing)
with st.form("p_form", clear_on_submit=True):
p_name = st.text_input("名稱", value="" if mode.startswith("+") else mode)
col1, col2 = st.columns(2)
p_cost = col1.number_input("大進價", min_value=0.0)
p_price = col2.number_input("小售價", min_value=0.0)
col3, col4, col5 = st.columns(3)
p_big, p_small, p_ratio = col3.text_input("大單位", value="箱"), col4.text_input("小單位", value="瓶"), col5.number_input("換算率", min_value=1, value=1)
p_alert = st.number_input("低水位預警", min_value=0, value=5)
p_desc = st.text_area("說明")
p_img = st.file_uploader("圖片", type=['jpg', 'png'])
if st.form_submit_button("💾 儲存商品檔案"):
img_b64 = ""
if p_img:
img = Image.open(p_img); img.thumbnail((300, 300))
buf = io.BytesIO(); img.save(buf, format="JPEG"); img_b64 = base64.b64encode(buf.getvalue()).decode()
if mode.startswith("+"):
c.execute("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?)", (p_name, p_cost, p_price, p_big, p_small, p_ratio, p_alert, img_b64, p_desc))
else:
c.execute("UPDATE products SET cost=?, price=?, big_unit=?, small_unit=?, ratio=?, alert_level=?, image_data=?, description=? WHERE name=?", (p_cost, p_price, p_big, p_small, p_ratio, p_alert, img_b64, p_desc, mode))
conn.commit(); st.success("儲存成功"); st.rerun()
elif choice == "👥 使用者帳號管理":
st.subheader("👥 使用者管理")
# 修正截圖中的狀態提示衝突
if "msg" in st.session_state:
st.toast(st.session_state.msg)
del st.session_state.msg
with st.container(border=True):
nu = st.text_input("新增帳號名稱")
np = st.text_input("設定密碼", type="password")
nr = st.selectbox("賦予權限", ["staff", "admin"])
if st.button("確認建立帳號", use_container_width=True):
try:
c.execute("INSERT INTO users VALUES (?,?,?)", (nu, np, nr))
conn.commit()
st.session_state.msg = "✅ 帳號建立成功"
st.rerun()
except:
st.error("❌ 帳號名稱重複")
st.divider()
# 修正列表排版：改用表格顯示，避免手機版圖示分行
user_data = pd.read_sql_query("SELECT username, role FROM users", conn)
st.write("📋 現有帳號清單")
st.dataframe(user_data, use_container_width=True)
for i, r in user_data.iterrows():
if r['username'] != 'admin':
if st.button("刪除", key=f"del_{i}", use_container_width=True):
c.execute("DELETE FROM users WHERE username=?", (r['username'],))
conn.commit(); st.rerun()
