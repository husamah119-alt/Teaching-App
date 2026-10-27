from __future__ import annotations

import html
import json
from pathlib import Path

import streamlit as st

import storage
from pipeline import extract_book, install_demo
from teacher_brain import ask_teacher, evaluate, validate_answers

st.set_page_config(page_title="رِواق | تعلّم من كتابك", page_icon="📖", layout="wide", initial_sidebar_state="auto")


def safe(value):
    return html.escape(str(value))


def markup(value):
    st.markdown(value, unsafe_allow_html=True)


def read_local(path, default=None):
    try:
        return storage.read_json(path, default)
    except (ValueError, OSError):
        st.error(f"تعذّرت قراءة {path.name}. احتفظنا بالملف كما هو. استعد نسخة سليمة من مجلد بيانات الكتاب قبل المتابعة.")
        st.stop()


with st.sidebar:
    markup('<div class="brand"><span class="brand-symbol">ر</span><div>رِواق<small>مساحة صغيرة، معرفة أكبر</small></div></div>')
    dark = st.toggle("الوضع الداكن", key="dark_mode")

palette = {"bg": "#101b24", "card": "#172631", "ink": "#edf5f6", "muted": "#aabdc5", "line": "#2b3e4b", "tint": "#193a38"} if dark else {
    "bg": "#f5f7f9", "card": "#ffffff", "ink": "#203442", "muted": "#6e8290", "line": "#e6ecef", "tint": "#eaf5f2"}
css = Path(__file__).with_name("style.css").read_text(encoding="utf-8")
for key, value in palette.items():
    css = css.replace(f"__{key}__", value)
markup(f"<style>{css}</style>")

with st.sidebar:
    page_view = st.radio("مساحتك", ["مساحة التعلّم", "مكتبتي", "دليل الاستخدام"], label_visibility="collapsed")
    st.divider()

books = storage.library()
if not books:
    with st.spinner("نحضّر لك كتاباً تجريبياً صغيراً…"):
        try:
            install_demo()
            books = storage.library()
        except (ValueError, OSError) as exc:
            st.error(f"تعذّر تجهيز الكتاب التجريبي: {exc}")

book_ids = [b["id"] for b in books]
requested = st.session_state.pop("open_book", None)
if requested in book_ids:
    st.session_state["book_choice"] = requested
if st.session_state.get("book_choice") not in book_ids and book_ids:
    st.session_state["book_choice"] = book_ids[0]

with st.sidebar:
    titles = {b["id"]: b["title"] for b in books}
    active = st.selectbox("كتابك الحالي", book_ids, format_func=lambda b: titles[b], key="book_choice") if books else None
    markup('<div class="privacy"><span>● يعمل محلياً</span><br>لا مفاتيح API، لا اشتراكات.<br>ملفاتك تبقى على الجهاز الذي يشغّل التطبيق.</div>')

markup('<div class="topline"><span>YOUR PERSONAL LEARNING SPACE</span><span class="status-dot">● &nbsp; تعلّم على مهل</span></div>')


def library_view():
    markup('<div class="eyebrow">مكتبتك الشخصية</div><h1>لكل كتاب، بداية جديدة<span class="accent">.</span></h1><p class="lead">ارفع كتابك، واجمع دروسك وتقدّمك في مكان واحد.</p>')
    left, right = st.columns([1.4, 1], gap="large")
    with left, st.container(border=True):
        markup('<div class="section-icon">＋</div><h3>أضف كتاباً إلى رحلتك</h3>')
        st.caption("PDF حتى 40 ميغابايت و400 صفحة. الكتب النصية هي الأنسب للبحث.")
        uploaded = st.file_uploader("اختر كتاب PDF", type=["pdf"], key="pdf_upload")
        if st.button("معالجة الكتاب وفتح الدروس", type="primary", disabled=uploaded is None, width="stretch"):
            bar = st.progress(0, text="نستخرج الصفحات ونجهّز صور الأجزاء…")
            try:
                book = extract_book(uploaded.getvalue(), uploaded.name, progress=bar.progress)
                st.session_state["open_book"] = book["id"]
                st.success("أُضيف كتابك. افتح مساحة التعلّم لبدء الدرس.")
                st.rerun()
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
            finally:
                bar.empty()
    with right:
        markup('<div class="callout"><div class="eyebrow">من الورق إلى التعلّم</div><h3>كتابك هو المصدر.</h3><p>نحفظ نص كل صفحة وصورتها، ونذكر مصدر المقاطع التي تجدها. الصفحات المعقدة تبقى كاملة كي لا نخفي شيئاً من التمرين.</p></div>')
        st.caption("لا تُرفع الملفات إلى خدمات ذكاء اصطناعي. إن شغّلت التطبيق على خادم، تُحفظ الملفات على ذلك الخادم.")
    st.subheader("على رفّك")
    for book in storage.library():
        with st.container(border=True):
            col_a, col_b = st.columns([4, 1])
            with col_a:
                markup(f'<div class="book-row"><div class="book-icon">▤</div><div><strong>{safe(book["title"])}</strong><p>{book["pages"]} صفحات &nbsp; · &nbsp; {book["parts"]} أجزاء</p></div></div>')
            with col_b:
                if st.button("اختيار الكتاب", key=f"open_{book['id']}", width="stretch"):
                    st.session_state["open_book"] = book["id"]
                    st.rerun()


def guide_view():
    markup('<div class="eyebrow">ابدأ بخطوة بسيطة</div><h1>من كتابك، وبإيقاعك<span class="accent">.</span></h1>')
    for number, title, text in [
        ("01", "أضف كتابك", "من مكتبتي، ارفع PDF. تستطيع تجربة المحتوى الأصلي الصغير الموجود مسبقاً قبل رفع كتابك."),
        ("02", "اقرأ جزءاً واحداً", "التعلّم متسلسل: يمكنك مراجعة ما سبق، ويفتح الجزء التالي بعد إتمام الحالي. أرقام الصفحات تشير إلى ترتيب PDF وقد تختلف عن ترقيم الكتاب المطبوع."),
        ("03", "اسأل وابحث", "اكتب كلمات من النص الإنجليزي. البحث يسترجع اقتباسات من الأجزاء المتاحة في الدرس نفسه، ولا يترجم السؤال العربي ولا يولّد شرحاً جديداً. غياب نتيجة لا يثبت غياب المعلومة من الكتاب كله."),
        ("04", "تحقّق من فهمك", "الكتاب التجريبي يتضمن مفتاح إجابات. لكتابك، استورد مفتاحاً موثوقاً من تبويب التمارين. إن لم يتوفر، سجّل مراجعة ذاتية؛ لا تُعدّ هذه نجاحاً مصحّحاً."),
    ]:
        markup(f'<div class="guide-step"><span>{number}</span><div><h3>{title}</h3><p>{text}</p></div></div>')
    st.info("هذه النسخة مجانية وتعتمد على البحث المحلي. لا تتضمن نموذج محادثة توليدياً أو فهم الرسومات أو OCR. صفحات الكتب الممسوحة تبقى قابلة للعرض، لكن البحث يحتاج نصاً مستخرجاً.")
    st.warning("التطبيق مساحة لمتعلّم واحد، بلا حسابات أو عزل بين المستخدمين. استخدمه شخصياً أو خلف بوابة دخول موثوقة؛ لا تنشر مكتبتك الخاصة للعامة.")


if page_view == "مكتبتي":
    library_view()
elif page_view == "دليل الاستخدام":
    guide_view()
elif active:
    directory = storage.book_dir(active)
    book = read_local(directory / "book.json")
    items = read_local(directory / "curriculum.json")
    sources = read_local(directory / "sources.json")
    try:
        progress = storage.load_progress(directory, len(items))
    except (ValueError, OSError):
        st.error("ملف التقدم غير صالح. لم نغيّره. استعد نسخة سليمة من progress.json في مجلد بيانات الكتاب.")
        st.stop()
    answers = read_local(directory / "answers.json", {})
    if answers:
        try:
            answers = validate_answers(answers, {i["id"] for i in items})
        except ValueError as exc:
            st.error(str(exc))
            st.stop()
    unlocked = storage.unlocked_index(items, progress)
    completed = len([i for i in items if i["id"] in progress["completed"]])
    verified = sum(progress["completed"].get(i["id"]) == "verified" for i in items)
    with st.sidebar:
        st.divider()
        st.caption("خريطة التعلّم")
        position = st.selectbox("الدرس والجزء", list(range(unlocked + 1)), index=min(progress["position"], unlocked),
                                format_func=lambda n: f"{items[n]['lesson']} · {items[n]['section']} · {items[n]['part']}  {'✓' if items[n]['id'] in progress['completed'] else '○'}",
                                key=f"nav_{active}_{progress['position']}")
        if position != progress["position"]:
            progress["position"] = position
            storage.save_json(directory / "progress.json", progress)
        st.progress(completed / len(items))
        st.caption(f"{completed} من {len(items)} أجزاء مكتملة")
        if unlocked + 1 < len(items):
            st.caption(f"🔒 {len(items) - unlocked - 1} أجزاء تُفتح بالتتابع")
        with st.expander("التسلسل الكامل"):
            for index, entry in enumerate(items):
                icon = "✓" if entry["id"] in progress["completed"] else "○" if index <= unlocked else "🔒"
                st.caption(f"{icon} {entry['lesson']} / {entry['section']} / {entry['part']}")
        st.download_button("تنزيل نسخة من التقدم", json.dumps(progress, ensure_ascii=False, indent=2), file_name="progress.json", mime="application/json", width="stretch")

    item = items[position]
    source = sources[position]
    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(flash)
    markup('<div class="eyebrow">مساحة التعلّم / MY STUDY SPACE</div><h1>خطوة اليوم، معرفة الغد<span class="accent">.</span></h1><p class="lead">اقرأ بتركيز، جرّب بنفسك، ودع فضولك يقودك.</p>')
    with st.container(key="metrics"):
        a, b, c = st.columns(3)
    with a:
        markup(f'<div class="metric"><span>رحلتك في الكتاب</span><strong>{round(100 * completed / len(items))}<small>%</small></strong><em>{completed} من {len(items)} أجزاء</em></div>')
    with b:
        markup(f'<div class="metric"><span>محطتك الحالية</span><strong class="latin">{safe(item["lesson"])}</strong><em>{safe(item["section"])} · الجزء {safe(item["part"])}</em></div>')
    with c:
        markup(f'<div class="metric"><span>إتقان موثّق</span><strong>{verified}<small> أجزاء</small></strong><em>بمفتاح إجابات معتمد منك</em></div>')
    markup(f'<div class="lesson-banner"><div><span class="eyebrow">CONTINUE YOUR JOURNEY</span><h2>{safe(book["title"])}</h2><p>الوحدة {safe(item["module"] or "—")} &nbsp; / &nbsp; الدرس {safe(item["lesson"])} &nbsp; / &nbsp; صفحة PDF {source["page"]}</p></div><div class="banner-art" aria-hidden="true">Aa<span>learn a little.<br>grow a lot.</span></div></div>')
    learn, chat, notes, details = st.tabs(["📖  الدرس والتمارين", "✦  ابحث في الدرس", "✎  ملاحظاتي", "⚙  مصادر الكتاب"])

    def finish(method):
        storage.complete_part(items, progress, position, method)
        storage.save_json(directory / "progress.json", progress)
        st.session_state["flash"] = "أحسنت! حُفظ تقدّمك وانتقلت إلى الجزء التالي." if position < len(items) - 1 else "أتممت الكتاب! يمكنك العودة لأي جزء للمراجعة."
        st.rerun()

    with learn:
        left, right = st.columns([1.35, 1], gap="large")
        with left, st.container(border=True):
            markup(f'<div class="card-heading"><span>من صفحات كتابك</span><span class="tag">PAGE {source["page"]} · {safe(item["part"])}</span></div>')
            image = directory / item["image_path"]
            if image.exists():
                st.image(str(image), width="stretch")
            else:
                st.warning("صورة هذا الجزء غير موجودة؛ راجع ملفات الكتاب.")
            with st.expander("عرض النص المستخرج"):
                st.text(item["text"] or "لا يوجد نص قابل للاستخراج في هذه الصفحة.")
            st.caption("يمكن تكبير الصورة من الزر في زاويتها. راجع القصّ مع الصفحة الأصلية عند الحاجة.")
        with right:
            with st.container(border=True):
                markup('<div class="card-heading"><span>حان دورك</span><span class="tag">PRACTICE</span></div>')
                questions = answers.get(item["id"], [])
                answer_key = f"result_{active}_{item['id']}"
                reveal_key = f"reveal_{active}_{item['id']}"
                if questions:
                    st.caption("أجب بالإنجليزية. التصحيح يقارن إجابتك بالبدائل المسجلة، وقد تحتاج الإجابات الحرة إلى مراجعة.")
                    with st.form(f"quiz_{active}_{item['id']}"):
                        responses = [st.text_input(f"{i + 1}. {q['question']}", key=f"response_{active}_{item['id']}_{i}") for i, q in enumerate(questions)]
                        submitted = st.form_submit_button("تحقّق من إجاباتي ↗", type="primary", width="stretch")
                    if submitted:
                        if not all(a.strip() for a in responses):
                            st.warning("أكمل جميع الإجابات أولاً.")
                        else:
                            result = evaluate(questions, responses)
                            st.session_state[answer_key] = result
                            if result["correct"]:
                                finish("self_review" if st.session_state.get(reveal_key) else "verified")
                    result = st.session_state.get(answer_key)
                    if result and not result["correct"]:
                        st.warning(f"أجبت بشكل صحيح عن {result['score']} من {result['total']}. جرّب مرة أخرى.")
                        for index, correct in enumerate(result["results"]):
                            if not correct:
                                st.info(f"تلميح للسؤال {index + 1}: {questions[index]['hint']}")
                    if st.button("كشف الإجابات والشرح", key=f"reveal_btn_{active}_{item['id']}", width="stretch"):
                        st.session_state[reveal_key] = True
                    if st.session_state.get(reveal_key):
                        for index, q in enumerate(questions, start=1):
                            st.write(f"{index}. {q['accepted'][0]}")
                            st.caption(q["explanation"])
                        st.caption("الإكمال بعد كشف الحل يُسجّل مراجعة ذاتية.")
                        if st.button("راجعت الحل • متابعة", width="stretch"):
                            finish("self_review")
                else:
                    st.subheader("اقرأ. لاحظ. جرّب.")
                    st.write("خذ وقتك مع هذا الجزء، ثم اكتب ملخصاً قصيراً في ملاحظاتك أو ابحث عن الكلمات التي تحتاجها.")
                    st.info("لا يوجد مفتاح إجابات لهذا الجزء. المتابعة تُسجَّل كمراجعة ذاتية، لا تصحيحاً مؤكداً.")
                    reviewed = st.checkbox("قرأت هذا الجزء وراجعت فهمي", key=f"reviewed_{active}_{item['id']}")
                    if st.button("إتمام الجزء والمتابعة ←", type="primary", width="stretch", disabled=not reviewed):
                        finish("self_review")
            markup('<div class="small-tip"><strong>قليل مستمر، خير من كثير منقطع.</strong><p>عشر دقائق بتركيز قد تصنع فرقاً في رحلتك اليوم.</p></div>')

    with chat:
        st.subheader("الجواب يبدأ من النص")
        st.caption("بحث محلي في أجزاء الدرس المفتوحة فقط. استخدم كلمات إنجليزية من الكتاب؛ لا يوجد نموذج توليد أو ترجمة في هذا الوضع.")
        history_key = f"chat_{active}_{item['lesson']}_{position}"
        history = st.session_state.setdefault(history_key, [])
        if not history:
            st.info("جرّب في الكتاب التجريبي: Where is Lina from? أو library")
        def show_message(message):
            with st.chat_message(message["role"]):
                # Plain text rendering prevents user/book markup being interpreted as HTML.
                st.text(message["text"])
                for citation in message.get("citations", []):
                    st.caption(f"صفحة PDF {citation['page']} · الجزء {citation['part']} · {citation['id']}")
                    st.text(citation["text"])
                    with st.expander(f"صورة المصدر · {citation['id']}"):
                        st.image(str(directory / citation["image_path"]), width="stretch")
        for message in history:
            show_message(message)
        query = st.chat_input("اكتب سؤالك أو كلمة من الدرس…", max_chars=1000)
        if query:
            allowed = [entry for index, entry in enumerate(items) if index <= min(position, unlocked) and entry["lesson"] == item["lesson"] and entry["module"] == item["module"]]
            result = ask_teacher(query, {"items": allowed, "sources": sources}, history)
            history.extend([{"role": "user", "text": query}, {"role": "assistant", "text": result["answer"], "citations": result["citations"]}])
            st.session_state[history_key] = history[-30:]
            st.rerun()
        if history and st.button("مسح محادثة هذا الجزء"):
            st.session_state[history_key] = []
            st.rerun()
        st.caption("المحادثة مؤقتة للجلسة. البحث اللفظي قد لا يجد كل الإجابات، ولا يتحقق من صحة الافتراضات داخل سؤالك.")

    with notes:
        st.subheader("أفكار تستحق الاحتفاظ بها")
        st.caption("ملاحظاتك محفوظة مع تقدم هذا الكتاب على جهاز التشغيل.")
        with st.form(f"notes_{active}_{item['id']}"):
            note = st.text_area("كلمات جديدة، ملخص أو سؤال للعودة إليه", value=progress["notes"].get(item["id"], ""), height=220, max_chars=10000)
            if st.form_submit_button("حفظ ملاحظاتي", type="primary"):
                progress["notes"][item["id"]] = note
                storage.save_json(directory / "progress.json", progress)
                st.success("حُفظت الملاحظة.")

    with details:
        st.subheader("المصادر وإعداد التصحيح")
        st.code(f"معرّف الجزء الحالي: {item['id']}", language=None)
        download_a, download_b = st.columns(2)
        with download_a:
            st.download_button("تنزيل المنهج JSON", (directory / "curriculum.json").read_bytes(), file_name="curriculum.json", mime="application/json", width="stretch")
        with download_b:
            st.download_button("تنزيل PDF الأصلي", (directory / "book.pdf").read_bytes(), file_name="book.pdf", mime="application/pdf", width="stretch")
        warnings = read_local(directory / "review.json", [])
        if warnings:
            with st.expander(f"ملاحظات الاستخراج • {len(warnings)} ملاحظات"):
                for warning in warnings:
                    st.write(f"صفحة {warning['page']}: {warning['reason']}")
        st.markdown("**استيراد مفتاح إجابات موثوق**")
        st.caption("يستبدل المفتاح الخاص بهذا الكتاب. تحقّق من ربط الأسئلة بمعرّفات الأجزاء وترتيبها؛ لا يُنشئ التطبيق حلولاً بالتخمين.")
        template = {item["id"]: [{"question": "Your question", "accepted": ["correct answer", "accepted alternative"], "hint": "A hint from the book", "explanation": "Explanation with the source"}]}
        st.download_button("تنزيل قالب الإجابات", json.dumps(template, ensure_ascii=False, indent=2), file_name="answers-template.json", mime="application/json")
        uploaded_answers = st.file_uploader("ملف answers.json", type=["json"], key=f"answers_upload_{active}")
        confirmed = st.checkbox("راجعت المفتاح وأوافق على استبدال الإجابات الحالية", key=f"confirm_answers_{active}")
        if st.button("استيراد الإجابات", disabled=uploaded_answers is None or not confirmed):
            try:
                if uploaded_answers.size > 1_000_000:
                    raise ValueError("حجم المفتاح يتجاوز 1 ميغابايت.")
                parsed = validate_answers(json.loads(uploaded_answers.getvalue()), {entry["id"] for entry in items})
                storage.save_json(directory / "answers.json", parsed)
                # Old grading/reveal state must never be reused with a new answer key.
                for key in list(st.session_state):
                    if key.startswith((f"result_{active}_", f"reveal_{active}_")):
                        del st.session_state[key]
                st.session_state["flash"] = "حُفظ مفتاح الإجابات. التصحيح جاهز للأجزاء المرتبطة به."
                st.rerun()
            except (ValueError, UnicodeError, OSError) as exc:
                st.error(f"لم يُستورد الملف: {exc}")
else:
    library_view()

markup('<div class="footer">رِواق &nbsp; / &nbsp; مساحة للتعلّم من كتابك <span>مصدر واضح. خطوة واحدة كل مرة.</span></div>')
