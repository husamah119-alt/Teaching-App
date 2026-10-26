"""Conservative PDF extraction. Ambiguous layouts remain whole-page exercises."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import fitz

import storage

MAX_BYTES = 40 * 1024 * 1024
MAX_PAGES = 400
MAX_PIXELS = 20_000_000
SECTION = re.compile(r"^(Reading|Vocabulary|Grammar|Listening|Speaking|Writing|Review|Use of English)\s*$", re.I)
PART = re.compile(r"^([A-F])[.)]\s+\S")


def extract_book(content: bytes, filename: str, progress=None):
    if not content or len(content) > MAX_BYTES:
        raise ValueError("اختر ملف PDF لا يتجاوز 40 ميغابايت.")
    identity = hashlib.sha256(content).hexdigest()[:24]
    destination = storage.book_dir(identity)
    if (destination / "book.json").exists():
        return storage.read_json(destination / "book.json")
    try:
        document = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise ValueError("تعذّر قراءة الملف. تأكد أنه PDF صالح.") from exc
    with document:
        if document.needs_pass:
            raise ValueError("الكتاب محمي بكلمة مرور؛ ارفع نسخة يمكنك فتحها دون كلمة مرور.")
        if not 1 <= len(document) <= MAX_PAGES:
            raise ValueError(f"الحد الأقصى للكتاب هو {MAX_PAGES} صفحة.")
        scale = 200 / 72
        for page in document:
            if page.rect.width * page.rect.height * scale**2 > MAX_PIXELS:
                raise ValueError("أبعاد بعض الصفحات كبيرة جداً. أعد تصدير PDF بحجم صفحة عادي.")
        (destination / "text_pages").mkdir(parents=True, exist_ok=True)
        (destination / "exercise_images").mkdir(exist_ok=True)
        items, sources, warnings = [], [], []
        module, lesson, section = None, "غير مصنّف", "غير مصنّف"
        for number, page in enumerate(document, start=1):
            text = page.get_text(sort=True)
            (destination / "text_pages" / f"page_{number:03}.txt").write_text(text, encoding="utf-8")
            lines = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    value = "".join(span["text"] for span in line["spans"]).strip()
                    if value:
                        lines.append((line["bbox"], value))
            lines.sort(key=lambda row: (row[0][1], row[0][0]))
            # Multiple text columns cannot safely be split by horizontal boundaries.
            left = any(b[0] < page.rect.width * .3 for b, _ in lines)
            right = any(b[0] > page.rect.width * .5 for b, t in lines if len(t) > 25)
            ambiguous = left and right
            candidates = [(b, t, PART.match(t)) for b, t in lines if PART.match(t)]
            letters = [m.group(1) for _, _, m in candidates]
            safe = bool(candidates) and not ambiguous and len(letters) == len(set(letters)) and letters == sorted(letters)
            if not safe:
                warnings.append({"page": number, "reason": "حُفظت الصفحة كاملة: لم يتأكد تقسيم الأجزاء آلياً."})
            if not text.strip():
                warnings.append({"page": number, "reason": "صفحة مصوّرة بلا نص قابل للبحث. الصورة متاحة؛ يلزم OCR خارجي محلي لإضافة النص."})
            boundaries = []
            for bbox, value in lines:
                module_match = re.fullmatch(r"Module\s+(\d+)", value, re.I)
                lesson_match = re.fullmatch(r"(?:Lesson\s+)?(\d+[a-z])", value, re.I)
                if module_match:
                    module = int(module_match.group(1))
                if lesson_match:
                    lesson = lesson_match.group(1).lower()
                if SECTION.fullmatch(value):
                    section = value.title()
                match = PART.match(value)
                if safe and match:
                    boundaries.append((bbox[1], match.group(1), module, lesson, section))
            if not safe:
                boundaries = [(0, "Page", module, lesson, section)]
            for index, (top, letter, mod, les, sec) in enumerate(boundaries):
                bottom = boundaries[index + 1][0] - 1 if index + 1 < len(boundaries) else page.rect.height
                clip = fitz.Rect(0, max(0, top - 2), page.rect.width, bottom)
                relative = f"exercise_images/page_{number:03}_part_{letter}.png"
                page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False).save(destination / relative)
                excerpt = page.get_textbox(clip).strip() if safe else text.strip()
                item_id = f"p{number}-{letter}"
                items.append({"id": item_id, "module": mod, "lesson": les, "section": sec, "part": letter,
                              "type": "questions" if safe else "reading", "text": excerpt, "image_path": relative})
                sources.append({"id": item_id, "index": len(items) - 1, "page": number, "bbox": list(clip)})
            if progress:
                progress(number / len(document))
        storage.save_json(destination / "curriculum.json", items)
        storage.save_json(destination / "sources.json", sources)
        storage.save_json(destination / "review.json", warnings)
        (destination / "book.pdf").write_bytes(content)
        metadata = {"id": identity, "title": Path(filename).stem[:120], "pages": len(document), "parts": len(items),
                    "review_count": len({w["page"] for w in warnings})}
        # Publish library entry last, so failed extractions never appear as ready books.
        storage.save_json(destination / "book.json", metadata)
        return metadata


def demo_pdf():
    document = fitz.open()
    lessons = [
        ("1a", "Reading", "A. Read about Lina", "Lina is a student from Baghdad. She studies English every morning.\nShe walks to the library on Fridays. Her favourite book is about space.",
         "B. Check your understanding", "1. Where is Lina from?\n2. When does she go to the library?"),
        ("1b", "Vocabulary", "A. Words in context", "A library is a place where people read and borrow books.\nA student is a person who studies at a school or college.",
         "B. Complete the sentence", "1. A person who studies is a ______.\n2. People borrow books from a ______."),
        ("1c", "Grammar", "A. The present simple", "Use the present simple for habits.\nI study English every day. Lina studies English every morning.\nWith she, he, and it, add -s or -es to the verb in affirmative sentences.",
         "B. Choose the correct verb", "1. Lina (study / studies) English every morning.\n2. I (walk / walks) to school every day."),
    ]
    for lesson, section, a, passage, b, exercise in lessons:
        page = document.new_page(width=595, height=842)
        for y, size, text in [(60, 12, "MODULE 1"), (98, 24, f"Lesson {lesson}"), (145, 18, section),
                              (205, 15, a), (245, 12, passage), (460, 15, b), (505, 12, exercise)]:
            page.insert_text((48, y), text, fontsize=size, color=(.08, .2, .27))
        page.insert_text((48, 790), "Teaching Studio | Demo book | Original example content", fontsize=10)
    content = document.tobytes()
    document.close()
    return content


def install_demo():
    book = extract_book(demo_pdf(), "English — بداية رحلتك.pdf")
    directory = storage.book_dir(book["id"])
    answers = {
        "p1-B": [{"question": "Where is Lina from?", "accepted": ["Baghdad", "from Baghdad", "She is from Baghdad"], "hint": "Read the first sentence.", "explanation": "The book says: Lina is a student from Baghdad."},
                  {"question": "When does she go to the library?", "accepted": ["Friday", "Fridays", "on Fridays"], "hint": "Look for a day of the week.", "explanation": "She walks to the library on Fridays."}],
        "p2-B": [{"question": "A person who studies is a …", "accepted": ["student", "a student"], "hint": "Look at the second definition.", "explanation": "A student is a person who studies."},
                  {"question": "People borrow books from a …", "accepted": ["library", "a library"], "hint": "Look at the first definition.", "explanation": "A library is a place where people read and borrow books."}],
        "p3-B": [{"question": "Lina (study / studies) English every morning.", "accepted": ["studies"], "hint": "Lina can be replaced with 'she'.", "explanation": "With she, add -s or -es: studies."},
                  {"question": "I (walk / walks) to school every day.", "accepted": ["walk"], "hint": "The subject is I.", "explanation": "Use the base form with I: walk."}],
    }
    if not (directory / "answers.json").exists():
        storage.save_json(directory / "answers.json", answers)
    return book


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract a PDF locally into the Riwaq library")
    parser.add_argument("pdf", type=Path, help="Path to a text-based PDF")
    options = parser.parse_args()
    if not options.pdf.is_file() or options.pdf.stat().st_size > MAX_BYTES:
        parser.error("Select an existing PDF no larger than 40 MB")
    try:
        result = extract_book(options.pdf.read_bytes(), options.pdf.name)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Ready: {result['pages']} pages, {result['parts']} parts; id={result['id']}")
