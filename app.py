import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from datetime import datetime, timedelta
import time
import io
import plotly.express as px
from PIL import Image

# --- إعداد الصفحة ---
st.set_page_config(page_title="Al-Amin Finance ⚡", page_icon="💎", layout="centered")

# --- تنسيق CSS ---
st.markdown("""
<style>
    .stMarkdown div { color: inherit; }
    
    .transaction-card { 
        background-color: #ffffff !important; 
        padding: 15px; 
        margin-bottom: 12px; 
        border-radius: 12px; 
        direction: rtl; 
        color: #000000 !important; 
        font-weight: 600; 
        box-shadow: 0 2px 6px rgba(0,0,0,0.1); 
    }
    
    /* ألوان العمليات */
    .card-income { border-right: 6px solid #2e7d32; }
    .card-expense { border-right: 6px solid #c62828; }
    .card-lend { border-right: 6px solid #f57c00; }      
    .card-borrow { border-right: 6px solid #7b1fa2; }    
    .card-repay_in { border-right: 6px solid #0288d1; } 
    .card-repay_out { border-right: 6px solid #d32f2f; }

    .transaction-card span { color: #333 !important; }
    .transaction-card strong { color: #000 !important; font-size: 1.1em; }
    .small-details { font-size: 0.85em; color: #666 !important; margin-top: 6px; }

    div.stButton > button { width: 100%; border-radius: 12px; height: 50px; font-size: 16px; }
    .metric-value { font-family: 'Arial'; direction: ltr; }
</style>
""", unsafe_allow_html=True)

# --- الحماية (النظام المستقر) ---
def check_password():
    def password_entered():
        if st.session_state["password"] == st.secrets["FAMILY_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.markdown("<h2 style='text-align: center;'>⚡ المهندس الأمين</h2>", unsafe_allow_html=True)
        st.text_input("🔑 Access Code", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("🔑 Access Code", type="password", on_change=password_entered, key="password")
        st.error("❌ Access Denied")
        return False
    else:
        return True

# --- تصحيح الخطأ هنا: رجعناها للطريقة المباشرة ---
if not check_password():
    st.stop()

# --- قاعدة البيانات ---
if not firebase_admin._apps:
    key_dict = json.loads(st.secrets["FIREBASE_KEY"])
    cred = credentials.Certificate(key_dict)
    firebase_admin.initialize_app(cred)

db = firestore.client()
COLLECTION_NAME = 'amin_personal_data'
SETTINGS_COLLECTION = 'amin_settings'

# --- الذكاء الاصطناعي ---
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-2.5-flash')

# دالة توحيد التصنيفات (The Cleaner) 🧹
def unify_category(cat_name):
    if not cat_name: return "عام"
    cat_lower = str(cat_name).lower().strip()
    
    mapping = {
        'food': 'أكل', 'dining': 'أكل', 'groceries': 'تموين', 'restaurant': 'مطاعم',
        'transport': 'مواصلات', 'fuel': 'بنزينة', 'gas': 'بنزينة', 'car': 'سيارة',
        'internet': 'نت', 'data': 'نت', 'phone': 'رصيد',
        'shopping': 'تسوق', 'clothes': 'ملابس',
        'gym': 'رياضة', 'sport': 'رياضة',
        'gift': 'هدايا', 'gifts': 'هدايا',
        'salary': 'راتب', 'income': 'دخل',
        'طعام وشرب': 'أكل', 'بقالة': 'تموين'
    }
    
    for key, val in mapping.items():
        if key in cat_lower:
            return val
    return cat_name

# تحليل النص (النسخة المحسنة JSON MODE) 🧠
def analyze_text(text):
    prompt = f"""
    أنت نظام محاسبي دقيق. مهمتك تحويل النص إلى JSON.
    النص المدخل: '{text}'
    
    القواعد الصارمة:
    1. استخرج: amount, item, category, type, account.
    2. إذا كان النص يحتوي على رقم فقط (مثل "5000")، اعتبره "رصيد مرحل" أو "إيداع" واجعل النوع income.
    3. ⚠️ ممنوع ترك حقل item فارغاً! إذا لم تجد وصفاً، اكتب "عملية عامة" أو "مصروفات متنوعة".
    4. التصنيفات المسموحة: (أكل, نت, سيارة, تسوق, تموين, ديون, تحويلات, رياضة, هدايا, راتب, عام).
    5. الحقل amount رقم فقط.
    """
    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        data = json.loads(response.text)
        # حماية من القيم الفارغة
        if not data.get('item') or str(data['item']).strip() == "":
            data['item'] = "عملية عامة"
        if not data.get('category'):
            data['category'] = "عام"
        return data
    except Exception as e:
        st.error(f"لم أستطع فهم العملية: {e}")
        return None

# تحليل الصورة
def analyze_image(image):
    prompt = """
    استخرج بيانات المعاملة المالية.
    المطلوب JSON:
    amount: الرقم.
    item: الوصف.
    account: (Wahda, NAB, Cash).
    type: (expense, income).
    category: (أكل, نت, سيارة, تسوق, تموين). *اكتب بالعربي فقط*.
    """
    try:
        response = model.generate_content(
            [prompt, image],
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        st.error(f"خطأ في الصورة: {e}")
        return None

# المحلل الذكي
def ask_analyst(question, dataframe):
    if dataframe.empty: return "مافيش بيانات."
    data_summary = dataframe.to_string(index=False)
    prompt = f"""
    بيانات المهندس الأمين:
    {data_summary}
    جاوب سؤاله: "{question}" بلهجة ليبية ومختصرة.
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except: return "خطأ."

def add_tx(data):
    now = datetime.now() + timedelta(hours=2)
    amt_val = float(data['amount']) 
    final_amount = amt_val
    if data['type'] in ['expense', 'lend', 'repay_out']: final_amount = -abs(amt_val)
    elif data['type'] in ['income', 'repay_in', 'borrow']: final_amount = abs(amt_val)
    
    data['category'] = unify_category(data.get('category', 'عام'))

    if data['type'] == 'transfer':
        db.collection(COLLECTION_NAME).add({
            'item': f"تحويل صادر إلى {data.get('to_account')}", 'amount': -abs(amt_val),
            'category': 'تحويلات', 'account': data['account'], '
