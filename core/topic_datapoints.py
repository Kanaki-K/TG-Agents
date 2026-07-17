"""Сборка датапоинтов «флагман + дистилляция» для рейтинга категорий (core/category_scoring).

Соединяет три источника в один датапоинт на тему:
- КАТЕГОРИЯ — из темы флагмана (core/topic_category);
- threads_best — ЛУЧШЕЕ Качество среди Threads-постов дистилляции (линкер их привязал);
- tg_quality — Качество ТГ-флагмана (матч флагман↔пост канала по тексту → его quality).

Чистая логика: посты приходят УЖЕ обогащённые скорингом (несут 'quality'); загрузку файлов и
enrich делает вызывающий (core/self_learn_check). Так модуль тестируется без тяжёлых зависимостей.
"""
from __future__ import annotations

from core import text_match, threads_flagship_link, topic_category

TG_MIN_COVERAGE = 0.5     # тело флагмана ≈ текст поста канала → покрытие высокое; ниже = не тот пост


def _tg_quality_for(flagship: dict, tg_posts: list[dict]) -> tuple[float | None, float]:
    """Качество ТГ-поста этого флагмана: матч по покрытию тела флагмана текстом поста.
    Возвращает (quality|None, покрытие). quality может быть None (пост ещё не зрел) при валидном матче."""
    body = flagship.get("text", "")
    best, best_cov = None, 0.0
    for p in tg_posts:
        cov = text_match.coverage(body, p.get("text", ""))
        if cov > best_cov:
            best, best_cov = p, cov
    if best is not None and best_cov >= TG_MIN_COVERAGE:
        return best.get("quality"), round(best_cov, 2)
    return None, round(best_cov, 2)


def build(flagships: list[dict], tg_posts: list[dict], threads_posts: list[dict]) -> dict:
    """Датапоинты + диагностика. tg_posts/threads_posts — УЖЕ обогащены скорингом ('quality').

    Возвращает {"datapoints": [...], "unmatched_threads": [...]}. Датапоинт:
    {category, theme, tg_quality, threads_best, created, n_threads, tg_coverage}."""
    linked = threads_flagship_link.link(flagships, threads_posts)
    dps = []
    for g in linked["groups"]:
        fl = g["flagship"]
        theme = fl.get("theme", "")
        quals = [gp["post"].get("quality") for gp in g["posts"]]
        threads_best = max([q for q in quals if q is not None], default=None)  # 1 прострел из N — норма
        tg_q, tg_cov = _tg_quality_for(fl, tg_posts)
        dps.append({
            "category": topic_category.category_of(theme),
            "theme": theme,
            "tg_quality": tg_q,
            "threads_best": threads_best,
            "created": (fl.get("date") or "")[:10],
            "n_threads": len(g["posts"]),
            "tg_coverage": tg_cov,
        })
    return {"datapoints": dps, "unmatched_threads": linked["unmatched"]}
