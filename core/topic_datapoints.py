"""Сборка датапоинтов «флагман + дистилляция» для рейтинга категорий (core/category_scoring).

Связь Threads-постов с темой — МНОГОУРОВНЕВАЯ, деградирует мягко (см. threads_distill_link):
1. журнал дистилляций (ID / тугой текст серии) — надёжно, основной путь;
2. флагман-фаззи (threads_flagship_link) — ЗАПАСНОЙ, для до-журнальных дистилляций.
Оба сливаются в один датапоинт по флагману (ключ = дата+тема). Датапоинт:
- КАТЕГОРИЯ — из журнала/банка (topic_category);
- threads_best — ЛУЧШЕЕ Качество среди привязанных Threads-постов;
- tg_quality — Качество ТГ-флагмана (матч флагман↔пост канала по тексту).

Чистая логика: посты приходят УЖЕ обогащённые скорингом ('quality'); загрузку/enrich делает
вызывающий (core/self_learn_check).
"""
from __future__ import annotations

from core import text_match, threads_distill_link, threads_flagship_link, topic_category

TG_MIN_COVERAGE = 0.5     # тело флагмана ≈ текст поста канала → покрытие высокое; ниже = не тот пост


def _norm(t: str) -> str:
    return " ".join((t or "").split()).lower()


def _reach_killed(p: dict) -> bool:
    """Пост саботирован механикой (ссылка/хештег режут охват) → НЕ честный тест темы.
    Такие в сигнал категории не берём: иначе тема получает штраф за прошлую механику автора."""
    return bool(p.get("has_link") or p.get("has_hashtag"))


def _find_flagship(flagships: list[dict], date: str, theme: str) -> dict | None:
    """Флагман по теме (точно) или по дате — чтобы достать его текст для матча с ТГ-постом."""
    nt = _norm(theme)
    for fl in flagships:
        if _norm(fl.get("theme", "")) == nt:
            return fl
    d = (date or "")[:10]
    for fl in flagships:
        if (fl.get("date", "") or "")[:10] == d:
            return fl
    return None


def _tg_quality_for(flagship: dict, tg_posts: list[dict]) -> tuple[float | None, float]:
    """Качество ТГ-поста флагмана: матч по покрытию тела флагмана текстом поста канала."""
    body = (flagship or {}).get("text", "")
    best, best_cov = None, 0.0
    for p in tg_posts:
        cov = text_match.coverage(body, p.get("text", ""))
        if cov > best_cov:
            best, best_cov = p, cov
    if best is not None and best_cov >= TG_MIN_COVERAGE:
        return best.get("quality"), round(best_cov, 2)
    return None, round(best_cov, 2)


def build(entries: list[dict], flagships: list[dict], tg_posts: list[dict],
          threads_posts: list[dict]) -> dict:
    """Датапоинты + диагностика. entries — журнал дистилляций; tg/threads посты УЖЕ обогащены ('quality')."""
    buckets: dict[tuple, dict] = {}

    def _bucket(key, theme, category, created, flagship) -> dict:
        b = buckets.setdefault(key, {"flagship": flagship, "theme": theme, "category": category,
                                     "created": created, "posts": [], "via": set()})
        if flagship and not b["flagship"]:
            b["flagship"] = flagship
        return b

    # Ступень 1 — журнал дистилляций (тугой/ID)
    jl = threads_distill_link.link(entries, threads_posts)
    for g in jl["groups"]:
        e = g["entry"]
        theme = e.get("theme", "")
        b = _bucket((e.get("flagship_date", ""), _norm(theme)), theme,
                    e.get("category") or topic_category.category_of(theme),
                    (e.get("flagship_date", "") or "")[:10],
                    _find_flagship(flagships, e.get("flagship_date", ""), theme))
        for gp in g["posts"]:
            b["posts"].append(gp["post"])
            b["via"].add(gp["via"])

    # Ступень 2 — флагман-фаззи, ТОЛЬКО по постам, что журнал не поймал (до-журнальные)
    fl_link = threads_flagship_link.link(flagships, jl["unmatched"])
    for g in fl_link["groups"]:
        fl = g["flagship"]
        theme = fl.get("theme", "")
        b = _bucket(((fl.get("date", "") or "")[:10], _norm(theme)), theme,
                    topic_category.category_of(theme), (fl.get("date", "") or "")[:10], fl)
        for gp in g["posts"]:
            b["posts"].append(gp["post"])
            b["via"].add("flagship-fuzzy")

    dps = []
    for b in buckets.values():
        quals = [p.get("quality") for p in b["posts"] if not _reach_killed(p)]  # саботированные — мимо
        threads_best = max([q for q in quals if q is not None], default=None)
        tg_q, tg_cov = _tg_quality_for(b["flagship"], tg_posts) if b["flagship"] else (None, 0.0)
        dps.append({
            "category": b["category"],
            "theme": b["theme"],
            "tg_quality": tg_q,
            "threads_best": threads_best,
            "created": b["created"],
            "n_threads": len(b["posts"]),
            "via": "+".join(sorted(b["via"])),
            "tg_coverage": tg_cov,
        })

    # STANDALONE — посты вне дистилляций (самописные и пр.): каждый = свой датапоинт по КЛАССИФИКАТОРУ
    # (enrich_topics ставит category). Так «личное>крипта» и виральный самописный крипто-пост тоже
    # считаются. Берём только 7 крипто-категорий (личное/прочее пикеру не действие) — остальное в leftover.
    valid = set(topic_category.all_slugs())
    leftover = []
    for p in fl_link["unmatched"]:
        cat = (p.get("category") or "").strip()
        if cat not in valid or _reach_killed(p):   # не крипто-категория ИЛИ саботирован механикой
            leftover.append(p)
            continue
        dps.append({
            "category": cat,
            "theme": (p.get("theme") or "(самописный пост)"),
            "tg_quality": None,
            "threads_best": p.get("quality"),
            "created": (p.get("date") or p.get("timestamp") or "")[:10],
            "n_threads": 1,
            "via": "standalone",
            "tg_coverage": 0.0,
        })
    return {"datapoints": dps, "unmatched_threads": leftover}
