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

# --- تنسيق خاص (إصلاح مشكلة الألوان) ---
st.markdown("""
<style>
    /* إجبار النص يكون أسود داخل البطاقات */
    .stMarkdown div { color: inherit; }
    .transaction-card { 
        direction: rtl; 
        color: black !important; /* هذا السطر يحل مشكلة الاختفاء */
    }
    .transaction-card span, .transaction-card strong {
        color: black !important;
    }
    div.stButton > button { width: 100%; border-radius: 12px; height: 50px; font-size: 18px; }
    .metric-value { font-family: 'Arial'; direction: ltr; }
</style>
""", unsafe_allow_html=True)

# --- مدير الجلسة والحماية ---
def get_manager(): return stx.CookieManager(key="amin_manager_v2")
cookie_manager = get_manager()

def check_auth():
    if st.session_state.get("auth_success", False): return True
    try:
        if cookie_manager.get("amin_key_v2") == st.secrets["FAMILY_PASSWORD"]:
            st.session_state.auth_success = True
            return True
    except: pass

    st.markdown("<h2 style='text-align: center;'>⚡ المهندس الأمين</h2>", unsafe_allow_html=True)
    pwd = st.text_input("Access Code", type="password")
    if st.button("Unlock"):
        if pwd == st.secrets["FAMILY_PASSWORD"]:
            st.session_state.auth_success = True
            cookie_manager.set("amin_key_v2", pwd, expires_at=datetime.now() + timedelta(days=90))
            st.rerun()
        else: st.error("Access Denied")
    return False

if not check_auth(): st.stop()

# --- الاتصال بقاعدة البيانات ---
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
    أنت محاسب شخصي ذكي. حلل النص: '{text}'
    القواعد:
    1. لو ذكر "تحويل" من حساب لحساب -> Type: "transfer".
    2. لو شراء أو صرف -> Type: "expense".
    3. لو استلام فلوس أو رصيد مبدئي -> Type: "income".
    
    الحسابات: "Cash", "Wahda", "NAB". (لو لم يذكر، افترض Cash).

    المخرجات (JSON):
    - type: "income", "expense", "transfer".
    - item: وصف العملية.
    - amount: المبلغ (دينار).
    - category: التصنيف (أكل، سيارة، نت، دراسة، أخرى).
    - account: الحساب المخصوم منه.
    - to_account: الحساب المستلم (للتحويل فقط).
    """
    try:
        response = model.generate_content(prompt)
        clean = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean)
    except: return None

def add_tx(data):
    now = datetime.now() + timedelta(hours=2) # توقيت ليبيا
    
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

def delete_all_data():
    docs = db.collection(COLLECTION_NAME).stream()
    for doc in docs: doc.reference.delete()

# --- جلب ومعالجة البيانات ---
docs = db.collection(COLLECTION_NAME).stream()
all_data = []
for doc in docs:
    d = doc.to_dict()
    all_data.append(d)

# تحويل لـ DataFrame للتحليل
df = pd.DataFrame(all_data)
if not df.empty:
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    # ترتيب حسب التاريخ (الأحدث فوق)
    df = df.sort_values(by='timestamp', ascending=False)

# حساب الأرصدة الحالية
balance = {'Cash': 0, 'Wahda': 0, 'NAB': 0}
if not df.empty:
    for index, row in df.iterrows():
        acc = row.get('account', 'Cash')
        if acc in balance:
            balance[acc] += row.get('amount', 0)

# --- الواجهة الرئيسية ---
st.title("محفظة المهندس 🏗️")

# 1. لوحة الأرصدة (Dashboard)
col1, col2 = st.columns(2)
col1.metric("💵 الكاش", f"{balance['Cash']:,.0f} د.ل")
col2.metric("🏦 الوحدة", f"{balance['Wahda']:,.0f} د.ل")
col3, col4 = st.columns(2)
col3.metric("🌍 شمال أفريقيا", f"{balance['NAB']:,.0f} د.ل")
col4.metric("💰 الإجمالي", f"{sum(balance.values()):,.0f} د.ل")

st.divider()

# 2. تحليل المصاريف (جديد!) 📊
st.subheader("📊 تحليلات الصرف")
if not df.empty:
    # فلترة المصاريف فقط (السالب)
    expenses = df[df['amount'] < 0].copy()
    expenses['abs_amount'] = expenses['amount'].abs()
    
    # حساب تواريخ الأسبوع والشهر
    now = datetime.now() + timedelta(hours=2)
    start_of_week = now - timedelta(days=now.weekday()) # بداية الأسبوع
    start_of_month = now.replace(day=1) # بداية الشهر
    
    # حساب المجموع
    week_exp = expenses[expenses['timestamp'] >= start_of_week]['abs_amount'].sum()
    month_exp = expenses[expenses['timestamp'] >= start_of_month]['abs_amount'].sum()
    
    # المتوسط (إجمالي المصاريف / عدد الأيام منذ أول عملية)
    days_active = (now - df['timestamp'].min()).days
    if days_active < 1: days_active = 1
    daily_avg = expenses['abs_amount'].sum() / days_active

    a1, a2, a3 = st.columns(3)
    a1.metric("الأسبوع هذا", f"{week_exp:,.0f} د.ل")
    a2.metric("الشهر هذا", f"{month_exp:,.0f} د.ل")
    a3.metric("المتوسط اليومي", f"{daily_avg:,.1f} د.ل")
else:
    st.info("سجل بيانات لتبدأ التحليلات...")

st.divider()

# 3. إدخال الأوامر
with st.form("entry"):
    txt = st.text_input("📝 أوامر المهندس:")
    if st.form_submit_button("تنفيد 🚀") and txt:
        with st.spinner('تحليل...'):
            res = analyze_smart(txt)
            if res:
                add_tx(res)
                st.success("تم!")
                time.sleep(1)
                st.rerun()

# 4. سجل الحركات (CSS fixed)
st.subheader("📜 آخر الحركات")
if not df.empty:
    for index, item in df.head(20).iterrows(): # عرض آخر 20
        color = "#81c784" if item['amount'] > 0 else "#e57373"
        t_str = item['timestamp'].strftime("%d/%m %I:%M%p")
        
        # كود HTML مع CSS إجباري للون الأسود
        st.markdown(f'''
        <div class="transaction-card" style="
            border-right: 5px solid {color}; 
            background-color: #f9f9f9; 
            padding: 10px; 
            margin-bottom: 8px; 
            border-radius: 8px;">
            <div style="display: flex; justify-content: space-between;">
                <strong style="color: black;">{item['amount']:,.0f} د.ل</strong>
                <span style="color: black;">{item['item']}</span>
            </div>
            <div style="font-size: 0.8em; color: #555; margin-top: 5px;">
                {t_str} | {item['account']} | {item.get('category','')}
            </div>
        </div>
        ''', unsafe_allow_html=True)
else:
    st.write("لا توجد بيانات.")

# --- القائمة الجانبية (الأدوات) ---
with st.sidebar:
    st.title("⚙️ الأدوات")
    if st.button("🔄 تحديث"): st.rerun()
    
    st.write("---")
    
    # 5. التحميل المتقدم (جديد!) 📥
    with st.expander("📥 تحميل سجل مخصص"):
        st.write("حدد الفترة:")
        col_d1, col_d2 = st.columns(2)
        d_start = col_d1.date_input("من", value=datetime.now()-timedelta(days=30))
        d_end = col_d2.date_input("إلى", value=datetime.now())
        
        if not df.empty:
            # فلترة حسب التاريخ
            mask = (df['timestamp'].dt.date >= d_start) & (df['timestamp'].dt.date <= d_end)
            filtered_df = df.loc[mask]
            
            if not filtered_df.empty:
                # تجهيز CSV
                export = filtered_df[['timestamp', 'item', 'amount', 'category', 'account', 'type']].copy()
                export['timestamp'] = export['timestamp'].apply(lambda x: x.strftime('%Y-%m-%d %I:%M %p'))
                csv = export.to_csv(index=False).encode('utf-8-sig')
                
                st.download_button(
                    "📄 تحميل Excel للفترة المحددة",
                    csv,
                    f"Statement_{d_start}_{d_end}.csv",
                    "text/csv"
                )
                st.caption(f"عدد العمليات: {len(filtered_df)}")
            else:
                st.warning("لا توجد بيانات في هذه الفترة.")
    
    # 6. زر التصفير (جديد!) ☢️
    with st.expander("☢️ تصفير المنظومة"):
        del_pass = st.text_input("كلمة السر للتأكيد:", type="password")
        if st.button("🗑️ حذف كل البيانات نهائياً"):
            if del_pass == st.secrets["FAMILY_PASSWORD"]:
                with st.spinner("جاري الفورمات..."):
                    delete_all_data()
                st.success("تم التصفير!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("الرمز غلط")
