"""Лёгкое сопоставление текстов по отличительным токенам — для линкера (пост ↔ флагман).

Не «похожесть» в общем смысле, а асимметричное ПОКРЫТИЕ: какая доля токенов короткого
текста (Threads-пост / тело флагмана) встречается в длинном (флагман / пост канала).
Дистилляция переиспользует ключевые слова/числа флагмана → покрытие ловит родство даже при
переписывании. Токен = число или слово ≥4 букв (лат/кир); мелочь и пунктуация отброшены.
"""
from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[0-9]+|[a-zа-яё]{4,}", re.IGNORECASE)


def tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def coverage(short_text: str, long_text: str) -> float:
    """Доля токенов КОРОТКОГО текста, покрытых длинным (0..1). Пустой короткий → 0."""
    a = tokens(short_text)
    if not a:
        return 0.0
    return len(a & tokens(long_text)) / len(a)
