"""Text normalization helpers."""

from __future__ import annotations

import re
import unicodedata


def fix_text_encoding(value: str) -> str:
    """Sửa chuỗi UTF-8 bị decode nhầm thành latin-1."""

    text = value.strip()
    if not text:
        return text
    if "Ã" in text or "â€™" in text or "á»" in text:
        try:
            repaired = text.encode("latin1").decode("utf-8")
            if repaired and "Ã" not in repaired:
                return repaired.strip()
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return text


_VIET_MAP = str.maketrans(
    {
        "đ": "d",
        "Đ": "d",
        "ă": "a",
        "â": "a",
        "ê": "e",
        "ô": "o",
        "ơ": "o",
        "ư": "u",
    }
)


def fold_vietnamese(value: str) -> str:
    """Bỏ dấu để so khớp trùng nội dung."""

    lowered = value.casefold().translate(_VIET_MAP)
    normalized = unicodedata.normalize("NFD", lowered)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def dedupe_limitations(items: list[str]) -> list[str]:
    """Loại trùng và ưu tiên bản tiếng Việt có dấu."""

    cleaned: list[str] = []
    folds: list[str] = []

    for raw in items:
        text = fix_text_encoding(str(raw).strip())
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue

        fold = fold_vietnamese(text)
        existing_index = next((i for i, existing_fold in enumerate(folds) if existing_fold == fold), None)
        if existing_index is not None:
            if _has_vietnamese_diacritics(text) and not _has_vietnamese_diacritics(cleaned[existing_index]):
                cleaned[existing_index] = text
            continue

        folds.append(fold)
        cleaned.append(text)

    return cleaned


def _has_vietnamese_diacritics(value: str) -> bool:
    for char in value:
        if unicodedata.category(char) == "Mn":
            return True
        if char in "ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ":
            return True
    return False
