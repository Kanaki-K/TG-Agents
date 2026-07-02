"""Жёсткая ЧЕСТНАЯ логика оценки постов Threads — единый источник правды для таблицы и отчёта.

Что чиним по сравнению с наивным подходом:
1. ВОЗРАСТ. Старый пост копил охват/комменты месяцами, свежий — дни. Линейно делить на возраст
   нельзя (посты плато́ят за ~1-2 недели, а не растут линейно). Поэтому: пост считается ЗРЕЛЫМ
   после MATURITY_DAYS; свежие в сравнения/рейтинги не берём (помечаем «рано судить»).
2. RATE вместо АБСОЛЮТА. «Разных людей» и «распространений» больше там, где больше охват —
   это не качество, а отражение охвата. Качество = сигнал НА ПРОСМОТР (люди/1k, amp_rate...),
   считаем только на постах с достаточным охватом (VIEW_FLOOR — иначе rate шумит на малом знам.).

Итог — ДВА разных объектива, НЕ смешиваем:
- quality (0..100) — «когда увидели, насколько зашло» (на просмотр, зрелые, ≥floor). Реюзит идею
  владельца: главный вес — РАЗНЫЕ ЛЮДИ на просмотр, второй — распространение на просмотр.
- reach_pct (0..100) — «как далеко улетело» (перцентиль сырых просмотров среди зрелых).
"""
from __future__ import annotations

import bisect
import statistics
from datetime import datetime

MATURITY_DAYS = 14      # пост «созрел» — охват в основном набран
VIEW_FLOOR = 150        # ниже — rate-метрики шумят (1 лайк на 20 просмотров = 5%)

# Веса Качества (сумма 1.0). Разные люди/просмотр > распространение/просмотр > лайки > живые ответы.
WQ_PPK, WQ_AMP, WQ_LIKE, WQ_HREP = 0.40, 0.30, 0.20, 0.10


def _ranker(values: list[float]):
    """v → перцентиль (0..1) = доля значений ≤ v. Пустой корпус → 0."""
    s = sorted(values)
    n = len(s)
    def rank(v: float) -> float:
        return bisect.bisect_right(s, v) / n if n else 0.0
    return rank


def _parse(d: str):
    try:
        return datetime.fromisoformat(d)
    except Exception:  # noqa: BLE001
        return None


def enrich(posts: list[dict]) -> dict:
    """Дополняет посты производными метриками (rate + возраст), Качеством, Охватом, тиром.

    Добавляет: amplification, amp_rate, like_rate, human_reply_rate, replies_per_person,
    people_per_k, age_days, mature, quality, reach_pct, tier, tier_ru. Возвращает baselines.
    """
    # «сейчас» = самый свежий пост корпуса (без зависимости от часов машины → воспроизводимо).
    dates = [dt for dt in (_parse(p.get("date", "")) for p in posts) if dt]
    now = max(dates) if dates else None

    for p in posts:
        v = p.get("views") or 0
        amp = int(p.get("reposts") or 0) + int(p.get("quotes") or 0) + int(p.get("shares") or 0)
        pr = int(p.get("people_replies") or 0)
        pc = int(p.get("people_count") or 0)
        p["amplification"] = amp
        p["amp_rate"] = round(amp / v, 4) if v else None
        p["like_rate"] = round((p.get("likes") or 0) / v, 4) if v else None
        p["human_reply_rate"] = round(pr / v, 4) if v else None
        p["replies_per_person"] = round(pr / pc, 1) if pc else 0.0
        p["people_per_k"] = round(pc / v * 1000, 2) if v else None
        dt = _parse(p.get("date", ""))
        p["age_days"] = round((now - dt).total_seconds() / 86400) if (now and dt) else None
        p["mature"] = bool(p["age_days"] is not None and p["age_days"] >= MATURITY_DAYS)
        p["quality"], p["reach_pct"], p["tier"], p["tier_ru"] = None, None, "nodata", ""

    measured = [p for p in posts if (p.get("views") or 0) > 0]
    mature = [p for p in measured if p["mature"]]
    elig = [p for p in mature if p["views"] >= VIEW_FLOOR]   # база для Качества (rate стабилен)
    if not measured:
        return {"measured": 0, "mature": 0, "eligible": 0}

    median_views = statistics.median([p["views"] for p in measured])
    r_reach = _ranker([p["views"] for p in mature]) if mature else None

    # Ранги качества — ТОЛЬКО на eligible (зрелые + достаточный охват).
    if elig:
        r_ppk = _ranker([p["people_per_k"] or 0 for p in elig])
        r_amp = _ranker([p["amp_rate"] or 0 for p in elig])
        r_like = _ranker([p["like_rate"] or 0 for p in elig])
        r_hrep = _ranker([p["human_reply_rate"] or 0 for p in elig])
        for p in elig:
            p["quality"] = round(100 * (
                WQ_PPK * r_ppk(p["people_per_k"] or 0)
                + WQ_AMP * r_amp(p["amp_rate"] or 0)
                + WQ_LIKE * r_like(p["like_rate"] or 0)
                + WQ_HREP * r_hrep(p["human_reply_rate"] or 0)), 1)
        r_qual = _ranker([p["quality"] for p in elig])
    else:
        r_amp = r_qual = None

    for p in measured:
        if r_reach is not None and p["mature"]:
            p["reach_pct"] = round(100 * r_reach(p["views"]), 1)

        eligible = p["mature"] and p["views"] >= VIEW_FLOOR
        pc, pr = p.get("people_count") or 0, p.get("people_replies") or 0
        if not p["mature"]:
            tier, ru = "fresh", "свежий (рано судить)"
        elif p.get("has_link") or p.get("has_hashtag"):
            tier, ru = "throttled", "зарезан (ссылка/хештег)"
        elif pr >= 5 and pc <= 1:
            tier, ru = "one_on_one", "1-на-1 (не вирус)"
        elif eligible and r_amp and (p["amp_rate"] or 0) > 0 \
                and r_amp(p["amp_rate"] or 0) >= 0.9 and p["views"] >= median_views:
            tier, ru = "viral", "виральный"
        elif pc >= 3:
            tier, ru = "discussed", "многолюдный"
        elif eligible and r_qual and p["quality"] is not None and r_qual(p["quality"]) >= 0.75:
            tier, ru = "resonant", "резонансный"
        else:
            tier, ru = "flat", "ровный"
        p["tier"], p["tier_ru"] = tier, ru

    return {
        "measured": len(measured),
        "mature": len(mature),
        "eligible": len(elig),
        "fresh": len(measured) - len(mature),
        "median_views": median_views,
        "median_er": round(statistics.median([p.get("er") or 0 for p in measured]), 2),
        "median_ppk": round(statistics.median([p["people_per_k"] or 0 for p in elig]), 2) if elig else 0,
        "maturity_days": MATURITY_DAYS,
        "view_floor": VIEW_FLOOR,
    }
