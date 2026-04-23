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

# --- 💡 安全修正：從 Streamlit Secrets 讀取 Key，不再公開 ---
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    GEMINI_API_KEY = "" # 若本機測試則預設為空

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

# --- 2. 工具函數 (略，保持不變) ---
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

# --- 💡 核心修正：穩定版 AI 分析函數 ---
def run_ai_analysis(inventory_summary, sales_summary):
    if not GEMINI_API_KEY:
        return "⚠️ 請先在 Streamlit Secrets 設定 GEMINI_API_KEY"
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # 使用 models/ 前綴以確保路徑正確
        model = genai.GenerativeModel('models/gemini-1.5-flash')
        
        prompt = f"""
        你是一位專業的進銷存分析師。請根據數據提供3條建議：
        庫存現狀：{inventory_summary}
        最近銷售：{sales_summary}
        請針對「補貨」與「利潤」回覆繁體中文，語氣精簡。
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 連線失敗。這可能是因為 API Key 被 Google 封鎖。請更換新 Key 並存入 Secrets。\n錯誤詳情：{str(e)}"

# --- 3. 登入系統與其餘功能 (保持 v17 穩定邏輯) ---
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
    st.stop()

current_user, current_role = st.session_state["user"], st.session_state["role"]

# --- 功能模組 (報表、登記、設定 - 維持原本邏輯) ---
# ... (這裡請接續原本的快速選單、功能分流等代碼) ...
# 為節省長度，請確保快速選單呼叫 run_ai_analysis 時不再需要傳入 API Key
