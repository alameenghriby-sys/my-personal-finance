import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from datetime import datetime, timedelta
import extra_streamlit_components as stx
import time

# --- إعداد الصفحة ---
st.set_page_config(page_title="Al-Amin Finance ⚡", page_icon="🔋", layout="centered")

# --- تنسيق خاص ---
st.markdown("""
<style>
    .metric-value { font-family: 'Arial'; direction: ltr; }
    .transaction-card { direction: rtl; }
    div.stButton > button { width: 100%; border-radius: 12px; height: 50px; font-size: 18px; }
</style>
""", unsafe_allow_html=True)

# --- مدير الجلسة والحماية ---
def get_manager(): return stx.CookieManager(key="amin_manager")
cookie_manager = get_manager()

def check_auth():
    if st.session_state.get("auth_success", False): return True
    try:
        if cookie_manager.get("amin_key") == st.secrets["FAMILY_PASSWORD"]:
            st.session_state.auth_success = True
            return True
    except: pass

    st.markdown("<h2 style='text-align: center;'>⚡ المهندس الأمين</h2>", unsafe_allow_html=True)
    pwd = st.text_input("Access Code", type="password")
    if st.button("Unlock"):
        if pwd == st.secrets["FAMILY_PASSWORD"]:
            st.session_state.auth_success = True
            cookie_manager.set("amin_key", pwd, expires_at=datetime.now() + timedelta(days=90))
            st.rerun()
        else: st.error("Access Denied")
    return False

if not check_auth(): st.stop()

# --- الاتصال (نفس قاعدة البيانات ولكن Collection مختلف) ---
if not firebase_admin._apps:
    key_dict = json.loads(st.secrets["FIREBASE_KEY"])
    cred = credentials.Certificate(key_dict)
    firebase_admin.initialize_app(cred)

db = firestore.client()
# 🔴 هنا السر: اسم الكولكشن مختلف عن العيلة
COLLECTION_NAME = 'amin_personal_data' 

# --- الذكاء الاصطناعي ---
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-flash-latest')

def analyze_smart(text):
    prompt = f"""
    أنت محاسب شخصي ذكي. حلل النص: '{text}'
    
    الحسابات (Accounts):
    - "Cash": كاش، جيب، محفظة.
    - "Wahda": مصرف الوحدة، موبي كاش، بطاقة الزاد.
    - "NAB": شمال أفريقيا، QR.

    القواعد:
    1. لو ذكر "تحويل" من حساب لحساب (مثلاً: من الوحدة لشمال أفريقيا) -> Type: "transfer".
    2. لو ذكر شراء شيء (مثلاً: شريت يورو، شريت كرسي) -> Type: "expense".
    3. لو ذكر استلام فلوس -> Type: "income".

    المخرجات (JSON):
    - type: "income", "expense", "transfer".
    - item: وصف العملية.
    - amount: المبلغ (دينار).
    - category: التصنيف.
    - account: الحساب المخصوم منه (المصدر).
    - to_account: الحساب المستلم (فقط في حالة التحويل). لو لم يذكر، افترض "Cash".
    """
    try:
        response = model.generate_content(prompt)
        clean = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean)
    except: return None

def add_tx(data):
    now = datetime.now() + timedelta(hours=2)
    
    if data['type'] == 'transfer':
        # خصم من المصدر
        db.collection(COLLECTION_NAME).add({
            'item': f"تحويل صادر إلى {data.get('to_account')}",
            'amount': -float(data['amount']),
            'category': 'تحويلات',
            'account': data['account'],
            'type': 'transfer_out',
            'timestamp': now
        })
        # إضافة للمستلم
        db.collection(COLLECTION_NAME).add({
            'item': f"تحويل وارد من {data['account']}",
            'amount': float(data['amount']),
            'category': 'تحويلات',
            'account': data.get('to_account', 'Cash'),
            'type': 'transfer_in',
            'timestamp': now
        })
    else:
        amt = float(data['amount'])
        if data['type'] == 'expense': amt = -amt
        db.collection(COLLECTION_NAME).add({
            'item': data['item'],
            'amount': amt,
            'category': data['category'],
            'account': data.get('account', 'Cash'),
            'type': data['type'],
            'timestamp': now
        })

# --- الحسابات ---
docs = db.collection(COLLECTION_NAME).stream()
balance = {'Cash': 0, 'Wahda': 0, 'NAB': 0}
history = []

for doc in docs:
    d = doc.to_dict()
    history.append(d)
    acc = d.get('account', 'Cash')
    if acc in balance:
        balance[acc] += d.get('amount', 0)

# ترتيب التاريخ للعرض
history.sort(key=lambda x: x['timestamp'], reverse=True)

# --- الواجهة ---
st.title("محفظة المهندس المستقل 🏗️")
st.caption("إدارة الموارد المالية | بنغازي - زليتن")

# لوحة القيادة
col1, col2 = st.columns(2)
col1.metric("إجمالي السيولة", f"{sum(balance.values()):,.0f} د.ل")
col2.metric("💵 الكاش", f"{balance['Cash']:,.0f} د.ل")

c1, c2 = st.columns(2)
c1.metric("🏦 الوحدة", f"{balance['Wahda']:,.0f} د.ل")
c2.metric("🌍 شمال أفريقيا", f"{balance['NAB']:,.0f} د.ل")

st.divider()

with st.form("entry"):
    txt = st.text_input("📝 أوامر المهندس:")
    if st.form_submit_button("تنفيد 🚀") and txt:
        with st.spinner('تحليل البيانات...'):
            res = analyze_smart(txt)
            if res:
                add_tx(res)
                st.success("تم!")
                time.sleep(1)
                st.rerun()

st.subheader("📜 آخر الحركات")
for item in history[:20]: # عرض آخر 20 فقط
    color = "#81c784" if item.get('amount') > 0 else "#e57373"
    acc = item.get('account')
    
    st.markdown(f'''
    <div style="border-right: 4px solid {color}; background-color: #f9f9f9; padding: 10px; margin-bottom: 8px; direction: rtl; border-radius: 8px;">
        <div style="display: flex; justify-content: space-between;">
            <strong>{item.get('amount'):,.0f} د.ل</strong>
            <span>{item.get('item')}</span>
        </div>
        <div style="font-size: 0.8em; color: #666;">
            {item['timestamp'].strftime("%d/%m %I:%M%p")} | {acc}
        </div>
    </div>
    ''', unsafe_allow_html=True)
