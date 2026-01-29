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

# --- تنسيق CSS (الأبيض الناصع) ---
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
    
    .card-income { border-right: 6px solid #2e7d32; }
    .card-expense { border-right: 6px solid #c62828; }

    .transaction-card span { color: #333 !important; }
    .transaction-card strong { color: #000 !important; font-size: 1.1em; }
    .small-details { font-size: 0.85em; color: #666 !important; margin-top: 6px; }

    div.stButton > button { width: 100%; border-radius: 12px; height: 50px; font-size: 18px; }
    .metric-value { font-family: 'Arial'; direction: ltr; }
</style>
""", unsafe_allow_html=True)

# --- الحماية الذكية (بدون أزرار) ⚡ ---
def get_manager(): return stx.CookieManager(key="amin_manager_v4")
cookie_manager = get_manager()

def check_auth():
    # 1. لو مسجل دخول من الجلسة الحالية
    if st.session_state.get("auth_success", False): return True
    
    # 2. لو مسجل دخول من الكوكيز
    try:
        if cookie_manager.get("amin_key_v4") == st.secrets["FAMILY_PASSWORD"]:
            st.session_state.auth_success = True
            return True
    except: pass

    # 3. شاشة الدخول (بدون زر)
    st.markdown("<h2 style='text-align: center;'>⚡ المهندس الأمين</h2>", unsafe_allow_html=True)
    
    # الدالة اللي بتشتغل أول ما تضغط Enter
    def password_entered():
        if st.session_state["password_input"] == st.secrets["FAMILY_PASSWORD"]:
            st.session_state.auth_success = True
            # حفظ الكوكيز لمدة 90 يوم
            cookie_manager.set("amin_key_v4", st.session_state["password_input"], expires_at=datetime.now() + timedelta(days=90))
        else:
            st.session_state.auth_success = False
            
    # حقل الإدخال مع on_change (السر هنا)
    st.text_input(
        "Access Code", 
        type="password", 
        key="password_input", 
        on_change=password_entered # هذا يخليه يدخل طول
    )
    
    if st.session_state.get("auth_success") is False:
        st.error("Access Denied ❌")
        
    return False

if not check_auth(): st.stop()

# --- قاعدة البيانات ---
if not firebase_admin._apps:
    key_dict = json.loads(st.secrets["FIREBASE_KEY"])
    cred = credentials.Certificate(key_dict)
    firebase_admin.initialize_app(cred)

db = firestore.client()
COLLECTION_NAME = 'amin_personal_data'

# --- الذكاء الاصطناعي ---
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-flash-latest')

def analyze_smart(text):
    prompt = f"""
    أنت محاسب شخصي دقيق. حلل النص: '{text}'
    القواعد:
    1. item: احتفظ بالتفاصيل (مثال: "شريت قهوة وشكلاطة" -> "قهوة وشكلاطة").
    2. amount: الرقم بدقة.
    3. account: "Cash", "Wahda", "NAB".
    4. type: "income", "expense", "transfer".
    المخرجات JSON: type, item, amount, category, account, to_account.
    """
    try:
        response = model.generate_content(prompt)
        clean = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean)
    except: return None

def add_tx(data):
    now = datetime.now() + timedelta(hours=2)
    amt_val = float(data['amount']) 
    
    if data['type'] == 'transfer':
        db.collection(COLLECTION_NAME).add({
            'item': f"تحويل صادر إلى {data.get('to_account')}",
            'amount': -amt_val,
            'category': 'تحويلات',
            'account': data['account'],
            'type': 'transfer_out',
            'timestamp': now
        })
        db.collection(COLLECTION_NAME).add({
            'item': f"تحويل وارد من {data['account']}",
            'amount': amt_val,
            'category': 'تحويلات',
            'account': data.get('to_account', 'Cash'),
            'type': 'transfer_in',
            'timestamp': now
        })
    else:
        if data['type'] == 'expense': amt_val = -amt_val
        db.collection(COLLECTION_NAME).add({
            'item': data['item'],
            'amount': amt_val,
            'category': data['category'],
            'account': data.get('account', 'Cash'),
            'type': data['type'],
            'timestamp': now
        })

def delete_all_data():
    docs = db.collection(COLLECTION_NAME).stream()
    for doc in docs: doc.reference.delete()

# --- المعالجة ---
docs = db.collection(COLLECTION_NAME).stream()
all_data = []
for doc in docs:
    all_data.append(doc.to_dict())

df = pd.DataFrame(all_data)
if not df.empty:
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    if df['timestamp'].dt.tz is not None:
        df['timestamp'] = df['timestamp'].dt.tz_localize(None)
    df = df.sort_values(by='timestamp', ascending=False)

# حساب الأرصدة
balance = {'Cash': 0.0, 'Wahda': 0.0, 'NAB': 0.0}
if not df.empty:
    for index, row in df.iterrows():
        acc = row.get('account', 'Cash')
        if acc in balance:
            balance[acc] += float(row.get('amount', 0.0))

# --- الواجهة ---
st.title("محفظة المهندس 🏗️")

# الأرصدة
col1, col2 = st.columns(2)
col1.metric("💵 الكاش", f"{balance['Cash']:,.3f} د.ل")
col2.metric("🏦 الوحدة", f"{balance['Wahda']:,.3f} د.ل")

col3, col4 = st.columns(2)
col3.metric("🌍 شمال أفريقيا", f"{balance['NAB']:,.3f} د.ل")
col4.metric("💰 الإجمالي", f"{sum(balance.values()):,.3f} د.ل")

st.divider()

# التحليلات
st.subheader("📊 تحليلات الصرف")
if not df.empty:
    expenses = df[df['amount'] < 0].copy()
    expenses['abs_amount'] = expenses['amount'].abs()
    
    now = datetime.now() + timedelta(hours=2)
    start_of_week = now - timedelta(days=now.weekday())
    start_of_month = now.replace(day=1)
    
    week_exp = expenses[expenses['timestamp'] >= start_of_week]['abs_amount'].sum()
    month_exp = expenses[expenses['timestamp'] >= start_of_month]['abs_amount'].sum()
    
    days_active = (now - df['timestamp'].min()).days
    if days_active < 1: days_active = 1
    daily_avg = expenses['abs_amount'].sum() / days_active

    a1, a2, a3 = st.columns(3)
    a1.metric("الأسبوع هذا", f"{week_exp:,.3f}")
    a2.metric("الشهر هذا", f"{month_exp:,.3f}")
    a3.metric("المتوسط اليومي", f"{daily_avg:,.3f}")
else:
    st.info("البيانات قيد التجميع...")

st.divider()

# الإدخال (مع المسح التلقائي)
with st.form("entry", clear_on_submit=True):
    txt = st.text_input("📝 أوامر المهندس:")
    if st.form_submit_button("تنفيد 🚀") and txt:
        with st.spinner('تحليل...'):
            res = analyze_smart(txt)
            if res:
                add_tx(res)
                st.success("تم!")
                time.sleep(0.5)
                st.rerun()

# السجل (أبيض)
st.subheader("📜 آخر الحركات")
if not df.empty:
    for index, item in df.head(30).iterrows():
        amount = float(item['amount'])
        
        if amount > 0:
            css_class = "card-income"
        else:
            css_class = "card-expense"
            
        t_str = item['timestamp'].strftime("%d/%m %I:%M%p")
        
        st.markdown(f'''
        <div class="transaction-card {css_class}">
            <div style="display: flex; justify-content: space-between;">
                <strong>{amount:,.3f} د.ل</strong>
                <span>{item['item']}</span>
            </div>
            <div class="small-details">
                {t_str} | {item['account']} | {item.get('category','')}
            </div>
        </div>
        ''', unsafe_allow_html=True)

# الأدوات
with st.sidebar:
    st.title("⚙️ الأدوات")
    if st.button("🔄 تحديث"): st.rerun()
    st.write("---")
    
    with st.expander("📥 تحميل سجل مخصص"):
        st.write("حدد الفترة:")
        col_d1, col_d2 = st.columns(2)
        d_start = col_d1.date_input("من", value=datetime.now()-timedelta(days=30))
        d_end = col_d2.date_input("إلى", value=datetime.now())
        
        if not df.empty:
            mask = (df['timestamp'].dt.date >= d_start) & (df['timestamp'].dt.date <= d_end)
            filtered_df = df.loc[mask]
            
            if not filtered_df.empty:
                export = filtered_df[['timestamp', 'item', 'amount', 'category', 'account', 'type']].copy()
                export['timestamp'] = export['timestamp'].apply(lambda x: x.strftime('%Y-%m-%d %I:%M %p'))
                csv = export.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📄 تحميل الملف", csv, "Statement.csv", "text/csv")
    
    with st.expander("☢️ تصفير المنظومة"):
        del_pass = st.text_input("كلمة السر للتأكيد:", type="password")
        if st.button("🗑️ حذف كل البيانات"):
            if del_pass == st.secrets["FAMILY_PASSWORD"]:
                delete_all_data()
                st.success("تم التصفير!")
                st.rerun()
            else: st.error("غلط")
