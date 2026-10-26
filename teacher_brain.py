"""Offline retrieval and deterministic evaluation. Never calls a hosted model."""
from __future__ import annotations

import re
import unicodedata

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

NOT_IN_BOOK = "This information is not in the book."


def normalize(value):
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    return " ".join(re.sub(r"[^\w\s]", " ", value).split())


def validate_answers(raw, part_ids):
    if not isinstance(raw, dict) or not raw:
        raise ValueError("مفتاح الإجابات يجب أن يكون كائناً غير فارغ يربط معرّف الجزء بقائمة أسئلة.")
    clean = {}
    for part_id, questions in raw.items():
        if part_id not in part_ids or not isinstance(questions, list) or not questions or len(questions) > 100:
            raise ValueError(f"معرّف جزء غير معروف أو قائمة أسئلة غير صالحة: {part_id}")
        clean[part_id] = []
        for question in questions:
            if not isinstance(question, dict) or not isinstance(question.get("question"), str) or not question["question"].strip():
                raise ValueError("كل سؤال يحتاج نص question.")
            accepted = question.get("accepted")
            if not isinstance(accepted, list) or not accepted or any(not isinstance(a, str) or not normalize(a) for a in accepted):
                raise ValueError("كل سؤال يحتاج قائمة accepted من إجابات نصية غير فارغة.")
            for field in ("hint", "explanation"):
                if not isinstance(question.get(field, ""), str):
                    raise ValueError(f"الحقل {field} يجب أن يكون نصاً.")
            clean[part_id].append({"question": question["question"], "accepted": accepted,
                                   "hint": question.get("hint", "راجع نص الجزء الحالي."), "explanation": question.get("explanation", "")})
    return clean


def evaluate(questions, responses):
    if len(questions) != len(responses):
        raise ValueError("Answer every question")
    results = [normalize(answer) in {normalize(a) for a in question["accepted"]}
               for question, answer in zip(questions, responses)]
    return {"correct": all(results), "results": results, "score": sum(results), "total": len(results)}


def ask_teacher(query, lesson_context, chat_history=None):
    # lesson_context is already restricted to unlocked parts of the selected lesson.
    items = lesson_context["items"]
    sources = {s["id"]: s for s in lesson_context["sources"]}
    texts = [item["text"] for item in items]
    if not texts or not query.strip():
        return {"answer": NOT_IN_BOOK, "citations": []}
    try:
        vectorizer = TfidfVectorizer(strip_accents="unicode", ngram_range=(1, 2), stop_words="english", sublinear_tf=True)
        matrix = vectorizer.fit_transform(texts)
        scores = cosine_similarity(vectorizer.transform([query]), matrix).ravel()
    except ValueError:
        return {"answer": NOT_IN_BOOK, "citations": []}
    selected = sorted(range(len(items)), key=lambda i: float(scores[i]), reverse=True)
    citations = []
    for index in selected[:3]:
        if scores[index] < .10:
            continue
        item = items[index]
        citations.append({"id": item["id"], "page": sources[item["id"]]["page"], "part": item["part"],
                          "text": item["text"], "image_path": item["image_path"]})
    return {"answer": "إليك المقاطع الأقرب لسؤالك من الدرس المتاح. هذه اقتباسات من الكتاب وليست إجابة مولّدة." if citations else NOT_IN_BOOK,
            "citations": citations}
