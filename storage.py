"""Local, atomic storage for a single learner. No credentials or remote services."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("TEACHER_DATA_DIR", ROOT / "data"))


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    # Corrupt files are deliberately not overwritten silently.
    return json.loads(path.read_text(encoding="utf-8"))


def library():
    books = []
    for path in sorted((DATA / "books").glob("*/book.json")):
        try:
            books.append(read_json(path))
        except (OSError, ValueError):
            continue
    return books


def book_dir(book_id: str) -> Path:
    if not book_id or any(c not in "0123456789abcdef" for c in book_id):
        raise ValueError("Invalid book identifier")
    return DATA / "books" / book_id


def load_progress(directory: Path, count: int):
    state = read_json(directory / "progress.json", {"position": 0, "completed": {}, "notes": {}})
    if not isinstance(state, dict) or not isinstance(state.get("completed"), dict) or not isinstance(state.get("notes"), dict):
        raise ValueError("Invalid progress file")
    position = state.get("position", 0)
    if not isinstance(position, int) or not 0 <= position < count:
        raise ValueError("Invalid saved position")
    return state


def unlocked_index(items, progress):
    for index, item in enumerate(items):
        if item["id"] not in progress["completed"]:
            return index
    return len(items) - 1


def complete_part(items, progress, index: int, method: str):
    if method not in {"verified", "self_review"}:
        raise ValueError("Unknown completion method")
    if not 0 <= index < len(items) or index > unlocked_index(items, progress):
        raise ValueError("Finish previous parts first")
    progress["completed"][items[index]["id"]] = method
    progress["position"] = min(index + 1, unlocked_index(items, progress))
    return progress
