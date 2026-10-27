from pathlib import Path

import fitz
import pytest

import storage
from pipeline import demo_pdf, extract_book, install_demo
from teacher_brain import NOT_IN_BOOK, ask_teacher, evaluate, validate_answers


@pytest.fixture
def local_data(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA", tmp_path)
    return tmp_path


def test_pdf_extraction_crops_and_sources(local_data):
    content = demo_pdf()
    book = extract_book(content, "test.pdf")
    directory = storage.book_dir(book["id"])
    items = storage.read_json(directory / "curriculum.json")
    sources = storage.read_json(directory / "sources.json")
    assert book["pages"] == 3 and book["parts"] == 6
    assert [i["part"] for i in items] == ["A", "B"] * 3
    assert [i["lesson"] for i in items] == ["1a", "1a", "1b", "1b", "1c", "1c"]
    assert "Lina is a student" in items[0]["text"]
    assert "Check your understanding" not in items[0]["text"]
    assert "Check your understanding" in items[1]["text"]
    assert sources[1]["page"] == 1
    for item in items:
        image = fitz.Pixmap(str(directory / item["image_path"]))
        assert image.width > 1000 and image.height > 100
    assert extract_book(content, "renamed.pdf") == book
    assert len(storage.library()) == 1


def test_scanned_and_multicolumn_pages_keep_whole_page(local_data):
    document = fitz.open()
    document.new_page()
    page = document.new_page()
    page.insert_text((30, 70), "A. This text begins on the left.")
    page.insert_text((340, 70), "A long right column of book content")
    book = extract_book(document.tobytes(), "layouts.pdf")
    items = storage.read_json(storage.book_dir(book["id"]) / "curriculum.json")
    assert len(items) == 2 and all(i["part"] == "Page" for i in items)
    assert items[0]["text"] == ""
    assert book["review_count"] == 2


def test_unreadable_and_encrypted_pdf(local_data):
    with pytest.raises(ValueError, match="PDF"):
        extract_book(b"not a pdf", "bad.pdf")
    document = fitz.open()
    document.new_page()
    encrypted = document.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="password")
    with pytest.raises(ValueError, match="مرور"):
        extract_book(encrypted, "locked.pdf")
    assert storage.library() == []


def test_retrieval_is_scoped_and_cites_pages(local_data):
    book = install_demo()
    directory = storage.book_dir(book["id"])
    items = storage.read_json(directory / "curriculum.json")
    sources = storage.read_json(directory / "sources.json")
    context = {"items": items[:1], "sources": sources}
    answer = ask_teacher("Where is Lina from?", context, [])
    assert answer["citations"][0]["page"] == 1
    assert "Baghdad" in answer["citations"][0]["text"]
    assert all(c["id"] == "p1-A" for c in answer["citations"])
    assert ask_teacher("quantum computing", context)["answer"] == NOT_IN_BOOK
    assert ask_teacher("present simple habits", context)["citations"] == []


def test_grading_all_answers_and_alternatives():
    questions = [{"question": "City?", "accepted": ["Baghdad", "from Baghdad"]}, {"question": "Day?", "accepted": ["Friday"]}]
    assert evaluate(questions, ["  BAGHDAD! ", "Friday."])["correct"]
    assert evaluate(questions, ["Baghdad", "Monday"])["score"] == 1
    assert not evaluate(questions, ["", ""])["correct"]
    with pytest.raises(ValueError):
        evaluate(questions, ["Baghdad"])
    with pytest.raises(ValueError):
        validate_answers({"unknown": questions}, {"p1-A"})
    with pytest.raises(ValueError):
        validate_answers({"p1-A": [{"question": "?", "accepted": [""]}]}, {"p1-A"})


def test_progress_sequence_and_persistence(local_data):
    items = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    progress = storage.load_progress(local_data, 3)
    with pytest.raises(ValueError):
        storage.complete_part(items, progress, 2, "verified")
    storage.complete_part(items, progress, 0, "self_review")
    assert progress["position"] == 1
    storage.complete_part(items, progress, 1, "verified")
    storage.save_json(local_data / "progress.json", progress)
    assert storage.load_progress(local_data, 3)["completed"] == {"a": "self_review", "b": "verified"}
    assert storage.unlocked_index(items, progress) == 2
    assert not list(local_data.glob("*.tmp"))


def test_corrupt_progress_preserved(local_data):
    path = local_data / "progress.json"
    path.write_text("{invalid", encoding="utf-8")
    with pytest.raises(ValueError):
        storage.load_progress(local_data, 3)
    assert path.read_text() == "{invalid"


def test_streamlit_learning_flow(local_data):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).parents[1] / "learning_app.py"), default_timeout=30).run()
    assert not app.exception
    assert len(app.selectbox[1].options) == 1
    next(c for c in app.checkbox if c.label == "قرأت هذا الجزء وراجعت فهمي").check().run()
    next(b for b in app.button if b.label == "إتمام الجزء والمتابعة ←").click().run()
    assert not app.exception
    assert len(app.selectbox[1].options) == 2
    assert len(app.text_input) == 2
    app.text_input[0].input("Baghdad")
    app.text_input[1].input("Monday")
    next(b for b in app.button if b.label == "تحقّق من إجاباتي ↗").click().run()
    assert not app.exception
    assert len(app.selectbox[1].options) == 2
    assert any("1 من 2" in warning.value for warning in app.warning)
    app.text_input[1].input("Fridays")
    next(b for b in app.button if b.label == "تحقّق من إجاباتي ↗").click().run()
    assert not app.exception
    assert len(app.selectbox[1].options) == 3
    directory = storage.book_dir(storage.library()[0]["id"])
    progress = storage.read_json(directory / "progress.json")
    assert progress["completed"] == {"p1-A": "self_review", "p1-B": "verified"}
    app.radio[0].set_value("مكتبتي").run()
    assert not app.exception
    app.radio[0].set_value("دليل الاستخدام").run()
    assert not app.exception
