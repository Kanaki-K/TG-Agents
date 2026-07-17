"""Сигнал само-обучения для пикера ФЛАГМАНОВ: веса категорий по ТГ-данным + взвешенная выборка.

Флагман живёт в ТГ → учится на ТГ-аналитике. НЕ на Threads: площадки инвертированы (находка 17.07 —
Рынок дно на Threads/топ на ТГ, см. memory). Категория, что заходит на КАНАЛЕ, чаще попадает в
кандидаты пикера — мягкий наклон ротации (±INFLUENCE, самозаглушка при нехватке данных). Финальный
выбор темы по-прежнему за свежестью/рынком/LLM — веса лишь смещают, что вообще попадёт на стол.

Единый источник и для пикера (run_pipeline), и для диагностики (self_learn_check) — чтобы наклон,
который видит владелец, был ровно тем, что применяет пикер.
"""
from __future__ import annotations

import json
import random
from datetime import date

from core import analytics, category_scoring, config, tg_scoring, topic_category

_TG_TOPICS = config.ROOT / "data" / "post_topics.json"


def tg_datapoints() -> list[dict]:
    """Датапоинты канала: каждый пост → его категория (классификатор) + Качество (tg_scoring)."""
    posts = analytics._load_posts()
    tg_scoring.enrich(posts)
    topics = json.loads(_TG_TOPICS.read_text(encoding="utf-8")) if _TG_TOPICS.exists() else {}
    valid = set(topic_category.all_slugs())
    dps = []
    for p in posts:
        meta = topics.get(str(p.get("id", "")), {})
        if meta.get("category") not in valid:
            continue
        dps.append({"category": meta["category"], "angle": meta.get("angle", ""),
                    "tg_quality": p.get("quality"), "threads_best": None,
                    "created": (p.get("date") or "")[:10]})
    return dps


def tg_category_weights() -> dict[str, float]:
    """{категория → вес пикера} по ТГ-данным. Нет данных/сбой → пусто (пикер работает нейтрально)."""
    try:
        return category_scoring.picker_weights(tg_datapoints(), today=date.today())
    except Exception:  # noqa: BLE001 — сигнал не критичен: сбой не должен ронять генерацию флагмана
        return {}


def weighted_sample(items: list, k: int, weight_fn) -> list:
    """k элементов БЕЗ повторов, вероятность ∝ весу (Efraimidis-Spirakis: ключ = u**(1/w), берём топ-k).
    Все веса равны → обычная равномерная выборка. Пустой вход → []."""
    keyed = []
    for it in items:
        w = max(float(weight_fn(it)), 1e-6)
        keyed.append((random.random() ** (1.0 / w), it))
    keyed.sort(key=lambda x: -x[0])
    return [it for _, it in keyed[:k]]
