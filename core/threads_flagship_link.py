"""Линкер: собранные Threads-посты → флагман, из которого их дистиллировали.

Публикация в Threads ручная → ID постов заранее нет. Связываем ПОСТ-ФАКТУМ: пост-дистилляция
выходит в тот же день или чуть позже флагмана (окно) и переиспользует его ключевые токены
(покрытие). Флагман ~1/день, поэтому окно дат почти всегда разводит кандидатов, а покрытие
подтверждает. Флагман даёт тему → категорию (core/topic_category) и мост к ТГ-посту.

Пороги (DATE_WINDOW_DAYS / MIN_COVERAGE) — единственные ручки; настраиваются на живых данных
через core/self_learn_check (он печатает покрытие каждого матча).
"""
from __future__ import annotations

from datetime import date, timedelta

from core import text_match

DATE_WINDOW_DAYS = 3      # пост-дистилляция вышла в [дата_флагмана, +N дней]
MIN_COVERAGE = 0.30       # мин. доля токенов поста, покрытых текстом флагмана


def _to_date(s: str) -> date | None:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def link(flagships: list[dict], threads_posts: list[dict],
         window: int = DATE_WINDOW_DAYS, min_coverage: float = MIN_COVERAGE) -> dict:
    """Сматчить посты с флагманами. Возвращает {"groups": [...], "unmatched": [...]}.

    group = {"flagship": fl, "posts": [{"post": p, "coverage": float}, ...]}.
    Каждый пост привязывается максимум к ОДНОМУ флагману (лучшее покрытие в окне дат)."""
    fdates = [(fl, _to_date(fl.get("date", ""))) for fl in flagships]
    groups: dict[int, dict] = {}
    unmatched: list[dict] = []

    for p in threads_posts:
        pd = _to_date(p.get("date") or p.get("timestamp") or "")
        if pd is None:
            unmatched.append(p)
            continue
        best_i, best_cov = None, 0.0
        for i, (fl, fd) in enumerate(fdates):
            if fd is None or not (fd <= pd <= fd + timedelta(days=window)):
                continue
            cov = text_match.coverage(p.get("text", ""), fl.get("text", ""))
            if cov > best_cov:
                best_i, best_cov = i, cov
        if best_i is not None and best_cov >= min_coverage:
            g = groups.setdefault(best_i, {"flagship": fdates[best_i][0], "posts": []})
            g["posts"].append({"post": p, "coverage": round(best_cov, 2)})
        else:
            unmatched.append(p)

    return {"groups": list(groups.values()), "unmatched": unmatched}
