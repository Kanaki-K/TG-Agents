"""Тесты рейтинга категорий (core/category_scoring): балл темы, лидерборд, веса, рецентность."""
from datetime import date

from core import category_scoring as cs


def test_topic_score_blend_and_fallback():
    # оба объектива → Threads весомее (0.65*80 + 0.35*40 = 66.0)
    assert cs.topic_score(40, 80) == 66.0
    assert cs.topic_score(None, 80) == 80.0   # только Threads
    assert cs.topic_score(40, None) == 40.0   # только ТГ
    assert cs.topic_score(None, None) is None  # оба зреют → тема не считается


def test_leaderboard_min_n_and_unknown():
    dps = [{"category": "рынок", "threads_best": 80, "tg_quality": None} for _ in range(4)]
    dps += [{"category": "психология", "threads_best": 50, "tg_quality": None}]  # n=1 < MIN_N
    dps += [{"category": cs.topic_category.UNKNOWN, "threads_best": 99, "tg_quality": None}]  # игнор
    rows = cs.leaderboard(dps)
    by = {r["category"]: r for r in rows}
    assert cs.topic_category.UNKNOWN not in by            # не из банка — не ранжируем
    assert by["рынок"]["ranked"] is True and by["рынок"]["n"] == 4
    assert by["психология"]["ranked"] is False
    assert rows[0]["category"] == "рынок"                 # ранжированные и сильные — сверху


def test_category_weights_tilt_and_selfmute():
    dps = [{"category": "рынок", "threads_best": 80, "tg_quality": None} for _ in range(4)]
    dps += [{"category": "словарь", "threads_best": 20, "tg_quality": None} for _ in range(4)]
    dps += [{"category": "психология", "threads_best": 50, "tg_quality": None}]  # n=1 → нейтрально
    w = cs.category_weights(dps)
    assert w["рынок"] > 1.0                    # сильная категория — вес вверх
    assert w["словарь"] < 1.0                  # слабая — вниз
    assert w["психология"] == 1.0              # мало данных — самозаглушка
    assert w["философия"] == 1.0               # нет данных вовсе — нейтрально
    assert cs.WEIGHT_MIN <= w["словарь"] and w["рынок"] <= cs.WEIGHT_MAX


def test_weights_neutral_when_under_two_ranked():
    dps = [{"category": "рынок", "threads_best": 80, "tg_quality": None} for _ in range(4)]
    w = cs.category_weights(dps)               # одна ранжированная — сравнивать не с чем
    assert all(v == 1.0 for v in w.values())


def test_recency_weights_recent_higher():
    today = date(2026, 7, 17)
    dps = [
        {"category": "рынок", "threads_best": 80, "tg_quality": None, "created": "2026-07-17"},
        {"category": "рынок", "threads_best": 20, "tg_quality": None, "created": "2026-03-19"},  # ~240д
    ]
    with_rec = cs.leaderboard(dps, today=today)[0]["score"]
    flat = cs.leaderboard(dps, today=None)[0]["score"]
    assert flat == 50.0                        # без рецентности — простое среднее
    assert with_rec > flat                     # свежий успех тянет балл вверх
