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
import io  # 👈 مكتبة جديدة للتعامل مع ملفات الإكسل

# --- إعداد الصفحة ---
st.set_page_config(page_title="Al-Amin Finance ⚡", page_icon="🔋", layout="centered")

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
    
    .card-income { border-right: 6px solid #2e7d32; }
    .card-expense { border-right: 6px solid #c62828; }

    .transaction-card span { color: #333 !important; }
    .transaction-card strong { color: #000 !important; font-size: 1.1em; }
    .small-details { font-size: 0.85em; color: #666 !important; margin-top: 6px; }

    div.stButton > button { width: 100%; border-radius: 12px; height: 50px; font-size: 18px; }
    .metric-value { font-family: 'Arial'; direction: ltr; }
</style>
""", unsafe_allow_html=True)

# --- الحماية ---
def get_manager(): return stx.CookieManager(key="amin_manager_v6")
cookie_manager = get_manager()

def check_auth():
    if st.session_state.get("auth_success", False): return True
    try:
        if cookie_manager.get("amin_key_v6") == st.secrets["FAMILY_PASSWORD"]:
            st.session_state.auth_success = True
            return True
    except: pass

    st.markdown("<h2 style='text-align: center;'>⚡ المهندس الأمين</h2>", unsafe_allow_html=True)
    
    def password_entered():
        if st.session_state["password_input"] == st.secrets["FAMILY_PASSWORD"]:
            st.session_state.auth_success = True
            cookie_manager.set("amin_key_v6", st.session_state["password_input"], expires_at=datetime.now() + timedelta(days=90))
        else:
            st.session_state.auth_success = False
            
    st.text_input("Access Code", type="password", key="password_input", on_change=password_entered)
    
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
    1. item: احتفظ بالتفاصيل كاملة.
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

# الإدخال
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

# السجل
st.subheader("📜 آخر الحركات")
if not df.empty:
    for index, item in df.head(30).iterrows():
        amount = float(item['amount'])
        
        if amount > 0: css_class = "card-income"
        else: css_class = "card-expense"
            
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

# --- القائمة الجانبية (محرك التصدير الجديد) ---
with st.sidebar:
    st.title("⚙️ الأدوات")
    if st.button("🔄 تحديث"): st.rerun()
    st.write("---")
    
    # 👇 دالة سحرية لتحويل البيانات إلى ملف Excel منسق وملون
    def to_excel(df_in):
        output = io.BytesIO()
        # 1. ترتيب وتسمية الأعمدة بالعربي
        df_export = df_in.rename(columns={
            'timestamp': 'التاريخ والوقت',
            'item': 'البيان',
            'amount': 'القيمة (د.ل)',
            'category': 'التصنيف',
            'account': 'الحساب',
            'type': 'نوع العملية'
        })
        # اختيار الأعمدة بالترتيب المنطقي
        df_export = df_export[['التاريخ والوقت', 'البيان', 'القيمة (د.ل)', 'الحساب', 'التصنيف', 'نوع العملية']]
        
        # تحويل التاريخ لنص عشان ما يتلخبط في الإكسل
        df_export['التاريخ والوقت'] = df_export['التاريخ والوقت'].dt.strftime('%Y-%m-%d %I:%M %p')

        # 2. الكتابة باستخدام XlsxWriter
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_export.to_excel(writer, index=False, sheet_name='كشف_حساب')
            workbook = writer.book
            worksheet = writer.sheets['كشف_حساب']
            
            # 3. التنسيقات (Format)
            # تنسيق العناوين (أخضر غامق، خط أبيض، عريض)
            header_fmt = workbook.add_format({
                'bold': True, 'font_size': 12, 'bg_color': '#1b5e20', 
                'font_color': '#ffffff', 'border': 1, 'align': 'center'
            })
            # تنسيق الخلايا العادية
            cell_fmt = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})
            # تنسيق الأرقام (3 خانات عشرية)
            num_fmt = workbook.add_format({'border': 1, 'align': 'center', 'num_format': '0.000'})
            
            # تطبيق التنسيق على العناوين
            for col_num, value in enumerate(df_export.columns.values):
                worksheet.write(0, col_num, value, header_fmt)
            
            # 4. ضبط عرض الأعمدة وتجاه الورقة
            worksheet.right_to_left() # اتجاه عربي
            worksheet.set_column('A:A', 22, cell_fmt) # التاريخ
            worksheet.set_column('B:B', 30, cell_fmt) # البيان (عريض)
            worksheet.set_column('C:C', 15, num_fmt)  # القيمة
            worksheet.set_column('D:F', 15, cell_fmt) # باقي الأعمدة

        return output.getvalue()

    # قسم التحميل
    with st.expander("📥 تحميل التقارير (Excel)", expanded=True):
        if not df.empty:
            now = datetime.now() + timedelta(hours=2)
            
            # 1. تحميل الكل
            excel_data = to_excel(df)
            st.download_button(
                "📄 تحميل السجل كامل (.xlsx)", 
                data=excel_data, 
                file_name=f"Full_Report_{now.date()}.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            st.write("---")
            
            # 2. آخر 30 يوم
            month_date = now - timedelta(days=30)
            df_month = df[df['timestamp'] >= month_date]
            if not df_month.empty:
                excel_month = to_excel(df_month)
                st.download_button(
                    "📅 تقرير آخر شهر (.xlsx)", 
                    data=excel_month, 
                    file_name=f"Monthly_Report_{now.date()}.xlsx", 
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            
            # 3. آخر 7 أيام
            week_date = now - timedelta(days=7)
            df_week = df[df['timestamp'] >= week_date]
            if not df_week.empty:
                excel_week = to_excel(df_week)
                st.download_button(
                    "📆 تقرير آخر أسبوع (.xlsx)", 
                    data=excel_week, 
                    file_name=f"Weekly_Report_{now.date()}.xlsx", 
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        else:
            st.info("سجل عملياتك أولاً...")
    
    st.write("---")
    
    with st.expander("☢️ تصفير المنظومة"):
        del_pass = st.text_input("كلمة السر للتأكيد:", type="password")
        if st.button("🗑️ حذف كل البيانات"):
            if del_pass == st.secrets["FAMILY_PASSWORD"]:
                delete_all_data()
                st.success("تم التصفير!")
                st.rerun()
            else: st.error("غلط")
