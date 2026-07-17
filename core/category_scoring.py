"""Рейтинг КАТЕГОРИЙ тем по перформансу — сердце петли само-обучения (какой РАЗРЯД тем заходит).

Вход — датапоинты «флагман + его дистилляция», по одному на тему:
    {"category": slug, "tg_quality": 0..100|None, "threads_best": 0..100|None, "created": "ГГГГ-ММ-ДД"|None}
- tg_quality     — Качество ТГ-флагмана (core/tg_scoring), None если ещё не зрел / нет данных.
- threads_best   — ЛУЧШИЙ из 1-3 постов дистилляции (core/threads/scoring). «Лучший», а не среднее:
                   1 прострел из 3 — норма Threads, среднее засудило бы каждую тему до ~33%.
- created        — для окна рецентности (свежие датапоинты весомее старых).

Выход: рейтинг категорий + веса для пикера. Правила честности: Threads весомее ТГ (холодная
аудитория = чище сигнал темы); категория с <MIN_N датапоинтов НЕ ранжируется (вес 1.0 —
самозаглушка, не гадаем на шуме); влияние на пикер ограничено INFLUENCE (доля, не диктат).
Сборку датапоинтов (join журналов со скорингом) делает следующий слой — здесь только агрегация.
"""
from __future__ import annotations

from datetime import date

from core import topic_category

# Threads весомее ТГ: холодная аудитория даёт более честный сигnal интереса к теме (наблюдение
# владельца + недораспространённость ТГ). Сумма = 1.0.
W_THREADS, W_TG = 0.65, 0.35

MIN_N = 4               # <столько датапоинтов в категории — не ранжируем (самозаглушка)
INFLUENCE = 0.30        # макс. доля перекоса веса пикера (±30%): рекомендация, не рельса
WEIGHT_MIN, WEIGHT_MAX = 0.6, 1.4
HALF_LIFE_DAYS = 120    # период полу-затухания рецентности (старый успех весит вдвое меньше)


def topic_score(tg_quality: float | None, threads_best: float | None) -> float | None:
    """Балл одной темы: смесь ТГ+Threads (Threads весомее). Есть только один объектив — берём его.
    Нет ни одного (оба зреют/нет данных) → None (тема ещё не считается)."""
    have_tg = tg_quality is not None
    have_th = threads_best is not None
    if have_tg and have_th:
        return round(W_THREADS * threads_best + W_TG * tg_quality, 1)
    if have_th:
        return round(float(threads_best), 1)
    if have_tg:
        return round(float(tg_quality), 1)
    return None


def _recency_weight(created: str | None, today: date | None) -> float:
    """Вес рецентности 0..1: свежий = 1, старее HALF_LIFE_DAYS = 0.5 и т.д. Без даты → 1.0."""
    if not created or today is None:
        return 1.0
    try:
        age = (today - date.fromisoformat(created)).days
    except ValueError:
        return 1.0
    return 0.5 ** (max(age, 0) / HALF_LIFE_DAYS)


def leaderboard(datapoints: list[dict], today: date | None = None) -> list[dict]:
    """Рейтинг категорий (сильные сверху). Для каждой: n, взвешенный по рецентности балл, ranked.
    today — «сегодня» для рецентности (передаёт вызывающий: date.today()); None → без затухания."""
    by_cat: dict[str, list[tuple[float, float]]] = {}   # slug → [(score, recency_weight)]
    for dp in datapoints:
        cat = dp.get("category")
        if not cat or cat == topic_category.UNKNOWN:
            continue                                    # не из банка — действовать не по чему
        sc = topic_score(dp.get("tg_quality"), dp.get("threads_best"))
        if sc is None:
            continue
        by_cat.setdefault(cat, []).append((sc, _recency_weight(dp.get("created"), today)))

    rows: list[dict] = []
    for cat, pairs in by_cat.items():
        wsum = sum(w for _, w in pairs)
        score = round(sum(s * w for s, w in pairs) / wsum, 1) if wsum else 0.0
        rows.append({"category": cat, "n": len(pairs), "score": score, "ranked": len(pairs) >= MIN_N})
    rows.sort(key=lambda r: (r["ranked"], r["score"]), reverse=True)
    return rows


def category_weights(datapoints: list[dict], today: date | None = None) -> dict[str, float]:
    """Множители для пикера: {категория → вес}. Ранжированные наклоняются к своему баллу
    (в пределах ±INFLUENCE), НЕ ранжированные и отсутствующие = 1.0 (нейтрально). Все категории
    банка присутствуют — пикер получает полную карту."""
    weights = {s: 1.0 for s in topic_category.all_slugs()}
    ranked = [r for r in leaderboard(datapoints, today) if r["ranked"]]
    if len(ranked) < 2:
        return weights                                  # сравнивать не с чем — все нейтральны
    mean = sum(r["score"] for r in ranked) / len(ranked)
    for r in ranked:
        rel = max(-1.0, min(1.0, (r["score"] - mean) / 50.0))   # качество 0..100 → нормируем на 50
        w = 1.0 + INFLUENCE * rel
        weights[r["category"]] = round(max(WEIGHT_MIN, min(WEIGHT_MAX, w)), 3)
    return weights


def render(rows: list[dict]) -> str:
    """Рейтинг строкой — для лог-панели пайплайна."""
    if not rows:
        return "рейтинг категорий: (данных нет)"
    out = ["рейтинг категорий (балл · n · статус):"]
    for r in rows:
        status = "✓ в игре" if r["ranked"] else f"копится ({r['n']}/{MIN_N})"
        out.append(f"  {r['score']:>5} · n={r['n']:<2} · {status:<14} {topic_category.label(r['category'])}")
    return "\n".join(out)
