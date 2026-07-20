"""Рейтинг КАТЕГОРИЙ тем по перформансу — сердце петли само-обучения (какой РАЗРЯД тем заходит).

Вход — датапоинты «флагман + дистилляция», по одному на тему:
    {"category": slug, "tg_quality": 0..100|None, "threads_best": 0..100|None, "created": "ГГГГ-ММ-ДД"|None}

ЧЕСТНАЯ СТАТИСТИКА (не наивное среднее):
- Усадка к глобальному среднему (empirical-Bayes): категория с малой выборкой тянется к μ, а не
  верит своим 1-2 точкам. Плавно заменяет жёсткий порог MIN_N — самозаглушка становится градиентной.
- Нижняя граница (усадка − стандартная ошибка): для РАНЖИРОВАНИЯ. Высокая дисперсия ИЛИ мало данных →
  шире неопределённость → ниже граница → категория не всплывает наверх на шуме/везении.
- Уверенность c = n_eff/(n_eff+K) масштабирует влияние на пикер: мало данных → c→0 → вес ≈ 1
  (нейтрально, категория остаётся исследуемой, не задавлена — задел под разведку #3).
- Рецентность: свежие датапоинты весомее (эффективный размер выборки n_eff по Kish это учитывает).

Правила ценности: Threads весомее ТГ (0.65/0.35 — холодная аудитория = честный сигнал интереса);
балл дистилляции = ЛУЧШИЙ из 1-3 постов (1 прострел из 3 — норма); влияние на пикер ограничено ±INFLUENCE.
"""
from __future__ import annotations

import math
import os
from datetime import date

from core import topic_category

W_THREADS, W_TG = 0.65, 0.35
SHRINK_K = 4.0          # псевдо-счёт усадки к μ (плавная замена жёсткого MIN_N)
INFLUENCE = 0.30        # макс. доля перекоса веса пикера (±30%) — рекомендация, не рельса
EXPLORE_MAX = 0.15      # макс. бонус разведки (не пробованная категория → +0.15 к весу; затухает ~1/√n)
WEIGHT_MIN, WEIGHT_MAX = 0.6, 1.4
# Полу-затухание рецентности. 180 дней (6 мес, решение владельца): свежий пост честнее старого,
# где механика (ссылки/хештеги/редактура) и крафт были слабее, НО хорошая эра шире 3-4 мес и резать
# в ½ уже на 90 днях — терять данные зря. Пост 6-мес весит ½, годовой ¼, 90-дн ~0.7. Настраивается.
HALF_LIFE_DAYS = float(os.getenv("THREADS_HALFLIFE_DAYS", "180"))
CONF_RANKED = 0.5       # c ≥ этого → «в игре» (только метка для человека; вес использует c непрерывно)


def topic_score(tg_quality: float | None, threads_best: float | None) -> float | None:
    """Балл темы: смесь ТГ+Threads (Threads весомее). Один объектив → берём его. Нет ни одного → None."""
    have_tg, have_th = tg_quality is not None, threads_best is not None
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


def _group(datapoints: list[dict], key: str, valid: set | None,
           today: date | None) -> dict[str, list[tuple[float, float]]]:
    """Сгруппировать датапоинты по произвольному объективу (key='category' тема / 'angle' подача).
    valid — множество допустимых значений (None = любое непустое)."""
    out: dict[str, list[tuple[float, float]]] = {}
    for dp in datapoints:
        k = dp.get(key)
        if not k or (valid is not None and k not in valid):
            continue
        sc = topic_score(dp.get("tg_quality"), dp.get("threads_best"))
        if sc is None:
            continue
        out.setdefault(k, []).append((sc, _recency_weight(dp.get("created"), today)))
    return out


def _global(by_cat: dict) -> tuple[float | None, float]:
    """Глобальные μ и σ по всем датапоинтам (взвешенные) — приор для усадки и масштаб перекоса."""
    pairs = [pw for lst in by_cat.values() for pw in lst]
    wsum = sum(w for _, w in pairs)
    if wsum <= 0:
        return None, 0.0
    mu = sum(s * w for s, w in pairs) / wsum
    var = sum(w * (s - mu) ** 2 for s, w in pairs) / wsum
    return mu, math.sqrt(var)


def _cat_stats(pairs: list[tuple[float, float]], mu: float) -> dict:
    """Статистика категории: усадка к μ, нижняя граница, уверенность."""
    wsum = sum(w for _, w in pairs)
    w2 = sum(w * w for _, w in pairs)
    n_eff = (wsum * wsum) / w2 if w2 else 0.0        # эффективный размер выборки (Kish)
    xbar = sum(s * w for s, w in pairs) / wsum if wsum else mu
    var = sum(w * (s - xbar) ** 2 for s, w in pairs) / wsum if wsum else 0.0
    std = math.sqrt(max(var, 0.0))
    se = std / math.sqrt(n_eff) if n_eff > 0 else std
    shrunk = (n_eff * xbar + SHRINK_K * mu) / (n_eff + SHRINK_K)
    conf = n_eff / (n_eff + SHRINK_K)
    return {"n": len(pairs), "n_eff": round(n_eff, 1), "mean": round(xbar, 1),
            "shrunk": round(shrunk, 1), "lower": round(shrunk - se, 1),
            "confidence": round(conf, 2)}


def leaderboard_by(datapoints: list[dict], key: str = "category", valid: set | None = None,
                   today: date | None = None) -> list[dict]:
    """Рейтинг по объективу key (тема/угол) по НИЖНЕЙ границе (надёжно-сильные сверху)."""
    by = _group(datapoints, key, valid, today)
    mu, _ = _global(by)
    if mu is None:
        return []
    rows = []
    for grp, pairs in by.items():
        st = _cat_stats(pairs, mu)
        st["category"] = grp                # slug объектива (тема или угол)
        st["ranked"] = st["confidence"] >= CONF_RANKED
        rows.append(st)
    rows.sort(key=lambda r: (r["lower"], r["confidence"]), reverse=True)
    return rows


def leaderboard(datapoints: list[dict], today: date | None = None) -> list[dict]:
    """Рейтинг ТЕМ (7 крипто-категорий банка)."""
    return leaderboard_by(datapoints, "category", set(topic_category.all_slugs()), today)


def category_weights(datapoints: list[dict], today: date | None = None) -> dict[str, float]:
    """Множители пикера: {категория → вес}. Перекос = усадка относительно μ, масштабированный
    уверенностью c (мало данных → c→0 → вес ≈ 1, категория не задавлена). Все категории банка есть."""
    weights = {s: 1.0 for s in topic_category.all_slugs()}
    by_cat = _group(datapoints, "category", set(topic_category.all_slugs()), today)
    mu, sigma = _global(by_cat)
    if mu is None:
        return weights
    spread = sigma or 1.0
    for cat, pairs in by_cat.items():
        st = _cat_stats(pairs, mu)
        rel = max(-1.0, min(1.0, (st["shrunk"] - mu) / spread))
        w = 1.0 + INFLUENCE * st["confidence"] * rel
        weights[cat] = round(max(WEIGHT_MIN, min(WEIGHT_MAX, w)), 3)
    return weights


def explore_bonus(datapoints: list[dict], today: date | None = None) -> dict[str, float]:
    """Бонус РАЗВЕДКИ per категория: недосэмплированные пробуем чаще, чтобы не голодали
    (категория, которой не повезло на старте, иначе никогда не отыграется). Бонус ~1/√(n_eff+1):
    не пробованная → EXPLORE_MAX, хорошо изученная → почти 0. Все категории банка."""
    by_cat = _group(datapoints, "category", set(topic_category.all_slugs()), today)
    out: dict[str, float] = {}
    for cat in topic_category.all_slugs():
        pairs = by_cat.get(cat, [])
        wsum = sum(w for _, w in pairs)
        w2 = sum(w * w for _, w in pairs)
        n_eff = (wsum * wsum) / w2 if w2 else 0.0
        out[cat] = round(EXPLORE_MAX / math.sqrt(n_eff + 1.0), 3)
    return out


def picker_weights(datapoints: list[dict], today: date | None = None) -> dict[str, float]:
    """ИТОГОВЫЕ веса для пикера = эксплуатация (усадка-тилт, #2) + разведка (недосэмплированные вверх, #3).
    Это то, что реально наклоняет ротацию тем. Мало данных → тилт≈0, но разведка держит категорию
    в игре; накопилась статистика → решает уже перформанс. Все категории банка, клампится в [MIN,MAX]."""
    exploit = category_weights(datapoints, today)
    explore = explore_bonus(datapoints, today)
    return {cat: round(max(WEIGHT_MIN, min(WEIGHT_MAX, exploit.get(cat, 1.0) + explore.get(cat, 0.0))), 3)
            for cat in topic_category.all_slugs()}


def spread(rows: list[dict]) -> float:
    """Разброс объектива = lb лучшего − lb худшего среди ранжированных. Круче спред → объектив
    сильнее объясняет, что заходит. Сравнив спред тем и углов, видно, что решает — тема или подача."""
    ranked = [r for r in rows if r["ranked"]]
    if len(ranked) < 2:
        return 0.0
    lbs = [r["lower"] for r in ranked]
    return round(max(lbs) - min(lbs), 1)


def render(rows: list[dict], label_fn=None) -> str:
    """Рейтинг строкой — для лог-панели. label_fn — как назвать slug (тема/угол)."""
    label_fn = label_fn or topic_category.label
    if not rows:
        return "(данных нет)"
    out = []
    for r in rows:
        status = "✓ в игре" if r["ranked"] else "копится"
        out.append(f"  {r['shrunk']:>5} · lb {r['lower']:>5} · n={r['n']:<2}(эфф {r['n_eff']}) · "
                   f"увер {r['confidence']:<4} · {status:<8} {label_fn(r['category'])}")
    return "\n".join(out)
