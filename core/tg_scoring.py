"""Честная оценка постов Telegram — зеркало логики connectors/threads/scoring.py под поля TG.

Зачем: наивный рейтинг (сырой ER / сумма просмотров) врёт по двум причинам —
1. ВОЗРАСТ: старый пост копил охват неделями, свежий — дни. Судить их вместе нельзя.
   Пост считается ЗРЕЛЫМ после MATURITY_DAYS; свежие в рейтинги не берём («рано судить»).
2. RATE вместо АБСОЛЮТА: «много репостов/реакций» бывает там, где просто много просмотров —
   это охват, а не качество. Качество = сигнал НА ПРОСМОТР, считаем только на постах с
   достаточным охватом (иначе rate шумит на малом знаменателе).

Два разных объектива, НЕ смешиваем:
- quality (0..100) — «когда увидели, насколько зашло» (на просмотр, зрелые, ≥floor).
  Веса под идею владельца: ЦЕННОСТЬ = поделился (репост/просмотр) > живой отклик
  (коммент/просмотр) > дешёвая реакция (реакция/просмотр).
- reach_pct (0..100) — «как далеко улетело» (перцентиль сырых просмотров среди зрелых).

TG-ограничение: «разных людей на просмотр» (people_per_k у Threads) тут пока нет —
для него нужен отдельный сбор id реагентов+комментаторов (следующий шаг). Пока качество
опирается на rate-метрики по счётчикам, которые уже собраны в channel_posts.json.

Запуск (у себя, где есть Python):
    python -m core.tg_scoring                 # весь зрелый корпус, топ по качеству
    python -m core.tg_scoring --recent 4       # только посты за последние 4 мес. (окно рецентности)
    python -m core.tg_scoring --format флагман # только один формат
    python -m core.tg_scoring --n 40           # сколько строк показать
"""
from __future__ import annotations

import bisect
import statistics
import sys
from datetime import timedelta

from core import analytics

MATURITY_DAYS = 14        # пост «созрел» — охват в основном набран (модель владельца: ~2 недели)
VIEW_FLOOR_FRAC = 0.2     # ниже 20% медианных просмотров rate-метрики шумят — в качество не берём
VIEW_FLOOR_MIN = 100      # абсолютный минимум знаменателя

# Веса Качества (сумма 1.0). Поделился > живой отклик > дешёвая реакция.
WQ_FWD, WQ_COMMENT, WQ_REACT = 0.40, 0.35, 0.25


def _ranker(values: list[float]):
    """v → перцентиль (0..1) = доля значений ≤ v. Пустой корпус → 0."""
    s = sorted(values)
    n = len(s)

    def rank(v: float) -> float:
        return bisect.bisect_right(s, v) / n if n else 0.0
    return rank


def enrich(posts: list[dict]) -> dict:
    """Дополняет посты rate-метриками, возрастом, Качеством, Охватом, тиром. Возвращает baselines.

    Мутирует переданные dict-и (добавляет ключи). posts — из analytics._load_posts()
    (там уже есть views/reactions/comments/forwards/dt/format/preview).
    """
    dts = [p["dt"] for p in posts if p.get("dt")]
    now = max(dts) if dts else None      # «сейчас» = самый свежий пост корпуса (воспроизводимо)

    for p in posts:
        v = p.get("views") or 0
        p["fwd_rate"] = round((p.get("forwards") or 0) / v, 5) if v else None
        p["comment_rate"] = round((p.get("comments") or 0) / v, 5) if v else None
        p["react_rate"] = round((p.get("reactions") or 0) / v, 5) if v else None
        dt = p.get("dt")
        p["age_days"] = round((now - dt).total_seconds() / 86400) if (now and dt) else None
        p["mature"] = bool(p["age_days"] is not None and p["age_days"] >= MATURITY_DAYS)
        p["quality"], p["reach_pct"], p["tier_ru"] = None, None, ""

    measured = [p for p in posts if (p.get("views") or 0) > 0]
    if not measured:
        return {"measured": 0, "mature": 0, "eligible": 0}
    median_views = statistics.median([p["views"] for p in measured])
    floor = max(VIEW_FLOOR_MIN, median_views * VIEW_FLOOR_FRAC)

    mature = [p for p in measured if p["mature"]]
    elig = [p for p in mature if p["views"] >= floor]     # база Качества: зрелые + достаточный охват
    r_reach = _ranker([p["views"] for p in mature]) if mature else None

    if elig:
        r_fwd = _ranker([p["fwd_rate"] or 0 for p in elig])
        r_com = _ranker([p["comment_rate"] or 0 for p in elig])
        r_rea = _ranker([p["react_rate"] or 0 for p in elig])
        for p in elig:
            p["quality"] = round(100 * (
                WQ_FWD * r_fwd(p["fwd_rate"] or 0)
                + WQ_COMMENT * r_com(p["comment_rate"] or 0)
                + WQ_REACT * r_rea(p["react_rate"] or 0)), 1)
        r_qual = _ranker([p["quality"] for p in elig])
    else:
        r_fwd = r_qual = None

    for p in measured:
        if r_reach is not None and p["mature"]:
            p["reach_pct"] = round(100 * r_reach(p["views"]), 1)
        eligible = p["mature"] and p["views"] >= floor
        if not p["mature"]:
            p["tier_ru"] = "свежий (рано судить)"
        elif eligible and r_fwd and (p["fwd_rate"] or 0) > 0 \
                and r_fwd(p["fwd_rate"] or 0) >= 0.9 and p["views"] >= median_views:
            p["tier_ru"] = "виральный"
        elif eligible and r_qual and p["quality"] is not None and r_qual(p["quality"]) >= 0.75:
            p["tier_ru"] = "резонансный"
        elif eligible and r_com and (p["comment_rate"] or 0) > 0 and r_com(p["comment_rate"] or 0) >= 0.75:
            p["tier_ru"] = "многолюдный"
        else:
            p["tier_ru"] = "ровный"

    return {
        "measured": len(measured),
        "mature": len(mature),
        "eligible": len(elig),
        "fresh": len(measured) - len(mature),
        "median_views": int(median_views),
        "view_floor": int(floor),
        "maturity_days": MATURITY_DAYS,
    }


def _arg(flag: str, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else default
    return default


def ranking(recent_months: int = 0, fmt: str = "", n: int = 30) -> str:
    posts = analytics._load_posts()
    if not posts:
        return "Данных по постам нет. Сначала собери (collect)."
    if recent_months:
        dts = [p["dt"] for p in posts if p.get("dt")]
        cutoff = max(dts) - timedelta(days=30 * recent_months)
        posts = [p for p in posts if p.get("dt") and p["dt"] >= cutoff]
    if fmt:
        f = fmt.strip().lower()
        posts = [p for p in posts if f in (p.get("format") or "")]
    base = enrich(posts)
    if not base.get("measured"):
        return "Нет постов с просмотрами под эти фильтры."

    scored = [p for p in posts if p.get("quality") is not None]
    scored.sort(key=lambda p: p["quality"], reverse=True)
    scope = (f"формат «{fmt}» | " if fmt else "") + (f"последние {recent_months} мес | " if recent_months else "")
    head = (f"ЧЕСТНЫЙ РЕЙТИНГ ({scope}зрелость ≥{base['maturity_days']}дн, "
            f"порог охвата {base['view_floor']}):\n"
            f"всего с просмотрами {base['measured']} | зрелых {base['mature']} | "
            f"в рейтинге {base['eligible']} | свежих (рано судить) {base['fresh']}\n"
            f"медиана просмотров {base['median_views']}\n"
            f"{'кач':>3} {'охв':>3} {'тир':<10} {'id':>5} {'дата':<10} {'формат':<10} "
            f"{'реп/1k':>7} {'ком/1k':>7} {'реа/1k':>7}  тема")
    rows = [head, "-" * 96]
    for p in scored[:n]:
        rows.append(
            f"{p['quality']:>3.0f} {p.get('reach_pct') or 0:>3.0f} {p['tier_ru']:<10} "
            f"{p['id']:>5} {p['date'][:10]:<10} {(p.get('format') or '—'):<10} "
            f"{(p['fwd_rate'] or 0)*1000:>7.2f} {(p['comment_rate'] or 0)*1000:>7.2f} "
            f"{(p['react_rate'] or 0)*1000:>7.2f}  {p.get('preview','')[:38]}")
    fresh = [p for p in posts if p.get("mature") is False and (p.get("views") or 0) > 0]
    if fresh:
        rows.append("-" * 96)
        rows.append("СВЕЖИЕ (ещё зреют, не в рейтинге): "
                    + ", ".join(f"#{p['id']}({p['age_days']}дн)" for p in fresh[:12]))
    return "\n".join(rows)


def main() -> None:
    recent = int(_arg("--recent", 0) or 0)
    fmt = _arg("--format", "") or ""
    n = int(_arg("--n", 30) or 30)
    print(ranking(recent_months=recent, fmt=fmt, n=n))


if __name__ == "__main__":
    main()
