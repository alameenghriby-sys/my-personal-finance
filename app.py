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
import io
import plotly.express as px

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

# --- الحماية ---
def get_manager(): return stx.CookieManager(key="amin_manager_v13")
cookie_manager = get_manager()

def check_auth():
    if st.session_state.get("auth_success", False): return True
    try:
        if cookie_manager.get("amin_key_v13") == st.secrets["FAMILY_PASSWORD"]:
            st.session_state.auth_success = True
            return True
    except: pass

    st.markdown("<h2 style='text-align: center;'>⚡ المهندس الأمين</h2>", unsafe_allow_html=True)
    def password_entered():
        if st.session_state["password_input"] == st.secrets["FAMILY_PASSWORD"]:
            st.session_state.auth_success = True
            cookie_manager.set("amin_key_v13", st.session_state["password_input"], expires_at=datetime.now() + timedelta(days=90))
        else:
            st.session_state.auth_success = False
    st.text_input("Access Code", type="password", key="password_input", on_change=password_entered)
    if st.session_state.get("auth_success") is False: st.error("Access Denied ❌")
    return False

if not check_auth(): st.stop()

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
model = genai.GenerativeModel('gemini-flash-latest')

def analyze_smart(text):
    prompt = f"""
    أنت محاسب شخصي ذكي. حلل النص: '{text}'
    الأنواع: lend (سلف صادر)، repay_in (سداد وارد)، borrow (سلف وارد)، repay_out (سداد صادر)، expense (مصروف)، income (دخل)، transfer (تحويل).
    القواعد: item تفاصيل، amount رقم، category عربي، account كاش/وحدة/شمال أفريقيا.
    المخرجات JSON: type, item, amount, category, account, to_account.
    """
    try:
        response = model.generate_content(prompt)
        clean = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean)
    except: return None

# دالة المحلل الذكي (التي عادت من جديد) 🤖
def ask_analyst(question, dataframe):
    if dataframe.empty: return "مافيش بيانات نحللها يا هندسة."
    data_summary = dataframe.to_string(index=False)
    prompt = f"""
    أنت محلل مالي للمهندس الأمين. لديك البيانات:
    {data_summary}
    أجب على السؤال: "{question}" بلهجة ليبية ودودة ومختصرة.
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except: return "سامحني، صار خطأ في التفكير."

def add_tx(data):
    now = datetime.now() + timedelta(hours=2)
    amt_val = float(data['amount']) 
    final_amount = amt_val
    if data['type'] in ['expense', 'lend', 'repay_out']: final_amount = -abs(amt_val)
    elif data['type'] in ['income', 'repay_in', 'borrow']: final_amount = abs(amt_val)
        
    if data['type'] == 'transfer':
        db.collection(COLLECTION_NAME).add({
            'item': f"تحويل صادر إلى {data.get('to_account')}", 'amount': -abs(amt_val),
            'category': 'تحويلات', 'account': data['account'], 'type': 'transfer_out', 'timestamp': now
        })
        db.collection(COLLECTION_NAME).add({
            'item': f"تحويل وارد من {data['account']}", 'amount': abs(amt_val),
            'category': 'تحويلات', 'account': data.get('to_account', 'Cash'), 'type': 'transfer_in', 'timestamp': now
        })
    else:
        db.collection(COLLECTION_NAME).add({
            'item': data['item'], 'amount': final_amount,
            'category': data['category'], 'account': data.get('account', 'Cash'),
            'type': data['type'], 'timestamp': now
        })

def delete_all_data():
    docs = db.collection(COLLECTION_NAME).stream()
    for doc in docs: doc.reference.delete()

# --- الميزانية ---
def get_budget():
    doc = db.collection(SETTINGS_COLLECTION).document('monthly_budget').get()
    if doc.exists: return doc.to_dict().get('limit', 1000.0)
    return 1000.0

def set_budget(limit):
    db.collection(SETTINGS_COLLECTION).document('monthly_budget').set({'limit': float(limit)})

# --- المعالجة ---
docs = db.collection(COLLECTION_NAME).stream()
all_data = []
for doc in docs: all_data.append(doc.to_dict())

df = pd.DataFrame(all_data)
if not df.empty:
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    if df['timestamp'].dt.tz is not None: df['timestamp'] = df['timestamp'].dt.tz_localize(None)
    df = df.sort_values(by='timestamp', ascending=False)

# الحسابات
balance = {'Cash': 0.0, 'Wahda': 0.0, 'NAB': 0.0}
debt_assets = 0.0; debt_liabilities = 0.0

if not df.empty:
    for index, row in df.iterrows():
        amt = float(row.get('amount', 0.0))
        acc = row.get('account', 'Cash')
        t_type = row.get('type', '')
        if acc in balance: balance[acc] += amt
        if t_type == 'lend': debt_assets += abs(amt)
        elif t_type == 'repay_in': debt_assets -= abs(amt)
        elif t_type == 'borrow': debt_liabilities += abs(amt)
        elif t_type == 'repay_out': debt_liabilities -= abs(amt)

# --- الواجهة الرئيسية ---
st.title("محفظة المهندس 🏗️")

# الأرصدة
col1, col2 = st.columns(2)
col1.metric("💵 الكاش", f"{balance['Cash']:,.3f} د.ل")
col2.metric("🏦 الوحدة", f"{balance['Wahda']:,.3f} د.ل")
col3, col4 = st.columns(2)
col3.metric("🌍 شمال أفريقيا", f"{balance['NAB']:,.3f} د.ل")
col4.metric("💰 الإجمالي", f"{sum(balance.values()):,.3f} د.ل")

st.divider()

# --- 🎯 نظام الميزانية (الذي عاد) ---
st.subheader("🎯 هدف الشهر (الخط الأحمر)")
budget_limit = get_budget()
if not df.empty:
    now = datetime.now() + timedelta(hours=2)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0)
    
    # حساب مصاريف الشهر (Expense only)
    month_expenses = df[
        (df['timestamp'] >= start_of_month) & 
        (df['type'] == 'expense')
    ]['amount'].sum()
    month_spent = abs(month_expenses)
    
    percent = min(month_spent / budget_limit, 1.0)
    st.progress(percent)
    
    c1, c2 = st.columns(2)
    c1.write(f"صرفت: **{month_spent:,.0f}** د.ل")
    c2.write(f"الحد: **{budget_limit:,.0f}** د.ل")
    
    if month_spent > budget_limit:
        st.error(f"⚠️ تجاوزت الميزانية بـ {month_spent - budget_limit:,.0f} د.ل")
else:
    st.info("سجل مصاريف عشان يشتغل العداد")

st.divider()

# أرصدة الديون
st.subheader("⚖️ ميزان الديون")
d1, d2 = st.columns(2)
d1.metric("🟠 لي عند الناس", f"{debt_assets:,.3f} د.ل")
d2.metric("🟣 عليا للناس", f"{debt_liabilities:,.3f} د.ل")

st.divider()

# الرسم البياني
st.subheader("📊 تحليل المصاريف")
if not df.empty:
    expenses_df = df[df['type'] == 'expense']
    if not expenses_df.empty:
        category_sum = expenses_df.groupby('category')['amount'].sum().abs().reset_index()
        fig = px.pie(category_sum, values='amount', names='category', 
                     color_discrete_sequence=px.colors.qualitative.Pastel,
                     hole=0.4) 
        fig.update_traces(textposition='inside', textinfo='percent+label')
        fig.update_layout(showlegend=False, height=350, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("مافيش مصاريف للرسم.")

st.divider()

# --- 💬 المحلل الذكي (الذي عاد) ---
with st.expander("💬 اسأل المحلل الذكي (AI)", expanded=False):
    st.caption("اسأل عن فلوسك، مثلاً: كم صرفت على الأكل؟ من يبي مني فلوس؟")
    user_q = st.text_input("سؤالك:")
    if user_q and not df.empty:
        with st.spinner("قاعد نفكر..."):
            answer = ask_analyst(user_q, df.head(100))
            st.success(answer)

st.divider()

# الإدخال اليدوي
with st.form("entry", clear_on_submit=True):
    txt = st.text_input("📝 الأوامر (مصروف، سلف، دخل...):")
    if st.form_submit_button("تنفيد 🚀") and txt:
        with st.spinner('تحليل...'):
            res = analyze_smart(txt)
            if res:
                add_tx(res)
                st.success("تم!")
                time.sleep(0.5)
                st.rerun()

# --- القائمة الجانبية ---
with st.sidebar:
    st.title("⚙️ غرفة التحكم")
    if st.button("🔄 تحديث"): st.rerun()
    
    st.write("---")
    st.subheader("⚡ عمليات سريعة")
    col_q1, col_q2 = st.columns(2)
    if col_q1.button("🌐 نت (55)"):
        add_tx({'type':'expense', 'item':'اشتراك نت', 'amount':55, 'category':'اتصالات', 'account':'Wahda'})
        st.toast("تم!")
        time.sleep(0.5)
        st.rerun() 
    if col_q2.button("☕ قهوة (5)"):
        add_tx({'type':'expense', 'item':'قهوة', 'amount':5, 'category':'بوفيه', 'account':'Cash'})
        st.toast("صحة!")
        time.sleep(0.5)
        st.rerun()
    if st.button("🏋️ جيم 3 شهور (200)"):
        add_tx({'type':'expense', 'item':'اشتراك جيم', 'amount':200, 'category':'رياضة', 'account':'Cash'})
        st.toast("وحش!")
        time.sleep(0.5)
        st.rerun()

    st.write("---")

    # قسم التقارير المنسق (4 أزرار)
    def to_excel(df_in):
        output = io.BytesIO()
        df_export = df_in.copy()
        trans = {'Groceries':'تموين','Transport':'مواصلات','Gym':'رياضة'}
        if 'category' in df_export.columns:
            df_export['category'] = df_export['category'].map(lambda x: trans.get(x, x))
        df_export = df_export.rename(columns={'timestamp': 'التاريخ', 'item': 'البيان', 'amount': 'القيمة', 'category': 'التصنيف', 'account': 'الحساب', 'type': 'النوع'})
        df_export['التاريخ'] = df_export['التاريخ'].dt.strftime('%Y-%m-%d %I:%M %p')
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_export[['التاريخ', 'البيان', 'القيمة', 'الحساب', 'التصنيف', 'النوع']].to_excel(writer, index=False, sheet_name='Sheet1')
            worksheet = writer.sheets['Sheet1']
            worksheet.right_to_left()
        return output.getvalue()

    with st.expander("📥 التقارير والديون", expanded=True):
        if not df.empty:
            now = datetime.now()
            # 1. أسبوع
            week_date = now - timedelta(days=7)
            df_week = df[df['timestamp'] >= week_date]
            if not df_week.empty:
                st.download_button("📆 تقرير آخر أسبوع", to_excel(df_week), f"Week_{now.date()}.xlsx", use_container_width=True)
            # 2. شهر
            month_date = now - timedelta(days=30)
            df_month = df[df['timestamp'] >= month_date]
            if not df_month.empty:
                st.download_button("📅 تقرير آخر شهر", to_excel(df_month), f"Month_{now.date()}.xlsx", use_container_width=True)
            # 3. كامل
            st.download_button("🗂️ السجل الكامل", to_excel(df), f"Full_{now.date()}.xlsx", use_container_width=True)
            # 4. ديون
            debt_types = ['lend', 'borrow', 'repay_in', 'repay_out']
            df_debt = df[df['type'].isin(debt_types)]
            if not df_debt.empty:
                st.download_button("📒 دفتر الديون (لي وعليا)", to_excel(df_debt), f"Debt_Only_{now.date()}.xlsx", use_container_width=True)

    with st.expander("🎯 ضبط الميزانية"):
        new_limit = st.number_input("الحد الشهري:", value=float(budget_limit), step=100.0)
        if st.button("حفظ الميزانية"):
            set_budget(new_limit)
            st.rerun()

    with st.expander("☢️ تصفير"):
        del_pass = st.text_input("تأكيد الحذف:", type="password")
        if st.button("🗑️ حذف الكل"):
            if del_pass == st.secrets["FAMILY_PASSWORD"]:
                delete_all_data()
                st.rerun()

# السجل
st.subheader("📜 آخر الحركات")
if not df.empty:
    for index, item in df.head(20).iterrows():
        amount = float(item['amount'])
        t_type = item.get('type', '')
        if t_type == 'lend': css = "card-lend"
        elif t_type == 'borrow': css = "card-borrow"
        elif t_type == 'repay_in': css = "card-repay_in"
        elif t_type == 'repay_out': css = "card-repay_out"
        elif amount > 0: css = "card-income"
        else: css = "card-expense"
            
        st.markdown(f'''
        <div class="transaction-card {css}">
            <div style="display: flex; justify-content: space-between;">
                <strong>{amount:,.3f} د.ل</strong>
                <span>{item['item']}</span>
            </div>
            <div class="small-details">
                {item['timestamp'].strftime("%d/%m %I:%M%p")} | {item['account']} | {item.get('category','')}
            </div>
        </div>
        ''', unsafe_allow_html=True)
