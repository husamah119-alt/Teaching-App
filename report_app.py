from __future__ import annotations

from dataclasses import asdict
import html
import re

import streamlit as st

from document_export import build_docx
from report_engine import (ReportRequest, KINDS, LANGUAGES, LEVELS, LENGTHS, SOURCE_MODES,
                           demo_report, generate_report, activate_model)
from local_models import discover_models, inspect_model
from report_sources import extract_file, fetch_source, MAX_TEXT

st.set_page_config(page_title='رِواق | من الفكرة إلى المستند', page_icon='📝', layout='wide')
st.markdown('''<style>
.stApp {background:#f5f7fa;color:#203442;}
[data-testid="stMainBlockContainer"] {max-width:1250px;padding-top:2rem;}
[data-testid="stMain"] {direction:rtl;font-family:'Noto Sans Arabic',Arial,sans-serif;}
[data-testid="stSidebar"] {background:#fff;direction:rtl;}
h1,h2,h3,p,label,button {font-family:'Noto Sans Arabic',Arial,sans-serif!important;}
textarea,input {text-align:start;}
.hero {background:linear-gradient(125deg,#103b3c,#176e65);border-radius:24px;padding:38px 40px;color:white;margin:10px 0 26px;}
.hero h1 {font-size:2.6rem!important;color:white;line-height:1.6;margin:8px 0;}
.hero p {color:#dbefeb;max-width:720px;line-height:1.9;font-size:1.03rem;}
.eyebrow {font-size:.8rem;letter-spacing:2px;color:#bde6dc;}
.brand {font-size:1.65rem;font-weight:800;color:#167d73;margin:12px 0;}
.chip {display:inline-block;border:1px solid #80bab0;border-radius:20px;padding:4px 13px;font-size:.78rem;margin:8px 0 0 8px;color:#dff3ed;}
[data-testid="stForm"] {background:#fff;border-radius:20px;padding:26px!important;border:1px solid #e2e9ec;}
.stButton>button[kind="primary"],.stFormSubmitButton>button[kind="primary"] {background:#167d73;border-color:#167d73;border-radius:10px;}
[data-testid="stMetric"] {background:white;border:1px solid #e2e9ec;border-radius:14px;padding:12px 18px;}
[data-testid="stTextArea"] textarea {line-height:1.85;}
.footer {color:#798990;font-size:.8rem;text-align:center;padding:30px 0 10px;}
@media(max-width:640px){.hero{padding:22px}.hero h1{font-size:1.9rem!important}[data-testid="stForm"]{padding:16px!important}}
</style>''', unsafe_allow_html=True)

with st.sidebar:
    st.markdown('<div class="brand">رِواق / مستندات</div>', unsafe_allow_html=True)
    st.caption('فكرة واضحة. شرح متكامل. مستند جاهز.')
    st.divider()
    st.subheader('تشغيل مجاني ومحلي')
    st.caption('الفحص يقرأ ملفات الجهاز الذي يشغّل التطبيق. عند التشغيل بالسحابة لن يرى ملفات حاسوبك الشخصي.')
    extra_folder = st.text_input('مجلد نماذج إضافي (اختياري)', key='extra_model_folder',
                                 placeholder='مثال: D:/Models أو /home/user/models')
    refresh_models = st.button('تحديث النماذج المحلية', width='stretch')
    if refresh_models or 'discovered_models' not in st.session_state:
        with st.spinner('نفحص مجلدات النماذج المحلية…'):
            found, scan_warnings = discover_models(extra_folder)
        st.session_state['discovered_models'] = [asdict(m) for m in found]
        st.session_state['model_scan_warnings'] = scan_warnings
    found = st.session_state['discovered_models']
    by_path = {m['path']: m for m in found}
    if found:
        st.caption(f'عثرنا على {len(found)} نموذج GGUF محلي.')
        # Keep selection when refreshing, unless its file disappeared.
        if st.session_state.get('model_choice') not in by_path:
            st.session_state['model_choice'] = found[0]['path']
        chosen = st.selectbox('النموذج المحلي', list(by_path), key='model_choice',
                              format_func=lambda path: f"{by_path[path]['name']} · {by_path[path]['size'] / 1024 ** 3:.2f} GB")
        st.caption(chosen)
        if st.button('تفعيل النموذج المختار', type='primary', width='stretch'):
            try:
                with st.spinner('نحمّل النموذج ونفحص إمكانية تشغيله…'):
                    activated = activate_model(chosen)
                st.session_state['active_local_model'] = asdict(activated)
                st.session_state['report_method_choice'] = 'صياغة بنموذج محلي مجاني'
                st.success('تم تفعيل النموذج للاستخدام في هذه الجلسة.')
            except (ValueError, OSError) as exc:
                st.error(str(exc))
    else:
        st.info('لم نعثر على نموذج GGUF. أضف مجلده أعلاه ثم اضغط تحديث النماذج المحلية. تحليل المصادر متاح الآن.')
    if st.session_state.get('model_scan_warnings'):
        with st.expander('ملاحظات فحص النماذج'):
            for warning in st.session_state['model_scan_warnings']:
                st.write(warning)
    active = st.session_state.get('active_local_model')
    active_path = None
    if active:
        try:
            current = inspect_model(active['path'])
            if current.identity != (active['path'], active['size'], active['modified_ns']):
                raise ValueError('تغير ملف النموذج؛ حدّث القائمة وفعّله مرة أخرى.')
            active_path = current.path
            st.caption(f"● النموذج المفعّل: {active['name']}")
        except ValueError:
            st.warning('النموذج المفعّل تغيّر أو لم يعد متاحاً؛ حدّث القائمة وفعّل نموذجاً صالحاً.')
    method = st.radio('طريقة إعداد التقرير', ['تحليل المصادر دون نموذج', 'صياغة بنموذج محلي مجاني'],
                      key='report_method_choice')
    use_model = method == 'صياغة بنموذج محلي مجاني'
    if use_model and not active_path:
        st.info('اختر نموذجاً من القائمة واضغط تفعيل النموذج المختار أولاً.')
    elif not use_model:
        st.caption('جاهز الآن: اختيار مقاطع من مصادرك وتنظيمها محلياً. هذا تحليل استخراجي، وليس تأليفاً أو ترجمة بالذكاء الاصطناعي.')
    st.caption('الصياغة المحلية تعتمد على قدرة الجهاز والنموذج. لا يرسل التطبيق مصادر ملفاتك إلى خدمة توليد خارجية.')
    st.divider()
    st.subheader('جرّب التنسيق')
    st.caption('افتح عيّنة ثابتة لتجربة المحرر وتصدير Word.')
    sample = st.button('فتح نموذج تنسيق', width='stretch')
    clear = st.button('مسح التقرير من الجلسة', width='stretch')
    st.caption('عدد الصفحات تقديري ويتغيّر حسب المحتوى والخط وإعدادات Word.')

if clear:
    for key in ('report_text', 'report_spec', 'report_citations', 'report_manifest', 'is_demo'):
        st.session_state.pop(key, None)
if sample:
    st.session_state['report_text'] = demo_report()
    st.session_state['report_spec'] = asdict(ReportRequest(topic='نموذج تنسيق: التعلّم النشط', length=list(LENGTHS)[0]))
    st.session_state['report_citations'] = []
    st.session_state['report_manifest'] = []
    st.session_state['is_demo'] = True

st.markdown('''<div class="hero"><div class="eyebrow">RIWAQ · DOCUMENT STUDIO</div>
<h1>من فكرةٍ في بالك،<br>إلى مستندٍ بين يديك.</h1>
<p>حدّد موضوعك وأضف مصادرك. أنشئ شرحاً منظّماً، راجعه بأسلوبك، وصدّره إلى Word بتنسيق احترافي يدعم العربية.</p>
<span class="chip">عربية وEnglish</span><span class="chip">مصادرك في مكان واحد</span><span class="chip">تصدير DOCX</span></div>''', unsafe_allow_html=True)

with st.form('report_request'):
    st.subheader('01 / ما الذي تريد شرحه؟')
    topic = st.text_input('موضوع البحث / الشرح الرئيسي *', placeholder='مثال: تطبيقات الذكاء الاصطناعي في التعليم', max_chars=300)
    details = st.text_area('تفاصيل الموضوع ونطاقه', placeholder='ما الأسئلة التي تريد الإجابة عنها؟ وما الجوانب التي ينبغي التركيز عليها؟', height=110, max_chars=10000)
    a, b, c = st.columns(3)
    with a:
        kind = st.selectbox('نوع الشرح', KINDS)
        level = st.selectbox('المستوى المستهدف', LEVELS, index=1)
    with b:
        language = st.selectbox('لغة التقرير', LANGUAGES)
        length = st.selectbox('طول الشرح', list(LENGTHS), index=1)
    with c:
        source_mode = st.selectbox('المصادر المعتمدة', SOURCE_MODES, index=2)
        st.caption('الطول هدف تقريبي. قد تحتاج التقارير الطويلة إلى مراجعة أو توسعة بعد التوليد.')
    st.divider()
    st.subheader('02 / أضف ما يستند إليه التقرير')
    st.caption('اختياري، عدا وضع «المصادر المرفقة فقط». الحد: 5 ملفات، 10 ميغابايت للملف، و90 ألف حرف للمصادر مجتمعة. الملفات المصوّرة تحتاج إلى OCR خارجي.')
    uploads = st.file_uploader('ملفات المصادر', type=['pdf', 'docx', 'txt', 'md'], accept_multiple_files=True)
    urls = st.text_area('الروابط الإلكترونية', placeholder='رابط HTTPS واحد في كل سطر — حتى 5 روابط عامة', height=90)
    extracted = st.text_area('نصوص المصادر أو النصوص المستخرجة', placeholder='ألصق مقتطفات تريد تحليلها، مع أسمائها أو مراجعها إن توفرت.', height=110, max_chars=MAX_TEXT)
    instructions = st.text_area('تعليمات إضافية', placeholder='مثال: استخدم أمثلة من المدارس العراقية وأضف جدول مقارنة.', height=90, max_chars=8000)
    st.caption('تُعالج الملفات والنصوص محلياً دون مفاتيح أو اشتراكات. البحث وقراءة الروابط يحتاجان الإنترنت. نزّل عملك قبل إنهاء الجلسة.')
    submitted = st.form_submit_button('إنشاء الشرح والمستند  ←', type='primary', width='stretch')

if submitted:
    spec = ReportRequest(topic, details, kind, language, length, level, source_mode, instructions)
    try:
        spec.validate()
        if use_model and not active_path:
            raise ValueError('اختر نموذجاً محلياً وفعّله من الشريط الجانبي أولاً، أو استخدم تحليل المصادر دون نموذج.')
        if not use_model and source_mode == SOURCE_MODES[0]:
            raise ValueError('الكتابة من المعرفة العامة تحتاج إلى النموذج المحلي. لتحليل نصوصك اختر المصادر المرفقة فقط.')
        if len(uploads) > 5:
            raise ValueError('يمكن إرفاق خمسة ملفات كحد أقصى.')
        links = [line.strip() for line in urls.splitlines() if line.strip()]
        if len(links) > 5:
            raise ValueError('يمكن إضافة خمسة روابط كحد أقصى.')
        has_inputs = bool(uploads or links or extracted.strip())
        if source_mode == SOURCE_MODES[0] and has_inputs:
            raise ValueError('أضفت مصادر؛ اختر «المصادر المرفقة فقط» أو «مزيج من المصادر والمعرفة والبحث» لاستخدامها.')
        parts, manifest = [], []
        with st.status('نجهّز المصادر ونكتب التقرير…', expanded=True) as status:
            def add_source(label, text):
                parts.append(f'SOURCE: {label}\n{text}')
                if sum(len(p) for p in parts) > MAX_TEXT:
                    raise ValueError('تجاوز مجموع المصادر 90 ألف حرف. اختصر النصوص أو قلّل الملفات.')
                manifest.append({'المصدر': label, 'الأحرف المستخرجة': len(text)})
            for upload in uploads:
                st.write(f'استخراج: {upload.name}')
                add_source(upload.name, extract_file(upload.name, upload.getvalue()))
            for link in links:
                st.write(f'قراءة المصدر: {html.escape(link)}')
                add_source(link, fetch_source(link))
            if extracted.strip():
                add_source('نص أرفقه المستخدم', extracted.strip())
            if spec.web_search:
                st.write('البحث المجاني عن مصادر عامة…')
                from report_sources import search_sources
                for title, url, body in search_sources(spec.topic):
                    add_source(title + ' — ' + url, body)
            st.write('صياغة التقرير محلياً…' if use_model else 'اختيار المقاطع وتنظيمها محلياً…')
            options = {'use_model': use_model}
            if use_model:
                options['model_path'] = active_path
            text, citations = generate_report(spec, '\n\n'.join(parts), **options)
            st.session_state['report_text'] = text
            st.session_state['report_spec'] = asdict(spec)
            st.session_state['report_citations'] = citations
            st.session_state['report_manifest'] = manifest
            st.session_state['is_demo'] = False
            st.session_state['report_method'] = method
            status.update(label='اكتمل التوليد؛ التقرير جاهز للمراجعة والتصدير.', state='complete', expanded=False)
    except (ValueError, OSError) as exc:
        st.error(str(exc))

if 'report_text' in st.session_state:
    st.divider()
    st.subheader('03 / راجع، حرّر، ثم صدّر')
    if st.session_state.get('is_demo'):
        st.info('هذه عيّنة تنسيق ثابتة وقصيرة؛ لم يحدث توليد بالذكاء الاصطناعي أو بحث عبر الإنترنت.')
    if not st.session_state.get('is_demo'):
        st.caption(st.session_state.get('report_method', ''))
    preview, editing, sources = st.tabs(['معاينة التقرير', 'تحرير المحتوى', 'المصادر والمواصفات'])
    with editing:
        st.caption('استخدم ## للأقسام و### للعناوين الفرعية؛ يُنشأ الغلاف والفهرس تلقائياً عند التصدير.')
        st.text_area('محتوى التقرير بصيغة Markdown', key='report_text', height=580, max_chars=200000)
    text = st.session_state['report_text']
    with preview:
        spec_snapshot = ReportRequest(**st.session_state['report_spec'])
        direction = 'ltr' if spec_snapshot.language == 'English' else 'rtl'
        st.markdown(f'<style>.st-key-report_preview {{direction:{direction};text-align:{"left" if direction == "ltr" else "right"};}}</style>', unsafe_allow_html=True)
        with st.container(key='report_preview'):
            st.markdown(text)  # Generated content never executes HTML.
    with sources:
        if st.session_state['report_manifest']:
            st.dataframe(st.session_state['report_manifest'], hide_index=True, width='stretch')
        for citation in st.session_state['report_citations']:
            st.write(citation.get('title', 'مصدر'))
            st.write(citation['url'])
        if not st.session_state['report_manifest'] and not st.session_state['report_citations']:
            st.caption('لا توجد ملفات مقروءة أو إحالات بحث مسترجعة لهذه النتيجة.')
        st.json(st.session_state['report_spec'])
    a, b, c = st.columns(3)
    a.metric('كلمات التقرير', f'{len(text.split()):,}')
    b.metric('عناوين الأقسام', str(len(re.findall(r'^#{2,6} ', text, re.M))))
    c.metric('مصادر مقروءة ومسترجعة', str(len(st.session_state['report_manifest']) + len(st.session_state['report_citations'])))
    st.caption('راجع دقة المحتوى والإحالات قبل الاعتماد الأكاديمي. الفهرس يشمل العناوين؛ أرقام صفحات المستند يحددها Word عند الفتح.')
    if text.strip():
        try:
            data = build_docx(text, spec_snapshot, st.session_state['report_citations'])
            filename = re.sub(r'[^\w\-\u0600-\u06ff]+', '-', spec_snapshot.topic).strip('-')[:100] or 'report'
            a, b = st.columns(2)
            a.download_button('تنزيل مستند Word  ↓', data, file_name=filename + '.docx',
                              mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document', type='primary', width='stretch')
            b.download_button('تنزيل النص Markdown  ↓', text, file_name=filename + '.md', mime='text/markdown', width='stretch')
        except ValueError as exc:
            st.error(str(exc))
else:
    st.info('ابدأ بإدخال الموضوع أعلاه، أو افتح نموذج التنسيق من الشريط الجانبي لتجربة المحرر والتصدير.')

st.markdown('<div class="footer">رِواق · من المعرفة إلى مستند يستحق القراءة</div>', unsafe_allow_html=True)
