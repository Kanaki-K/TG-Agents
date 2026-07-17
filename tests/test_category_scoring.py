"""Тесты честной статистики рейтинга (core/category_scoring): усадка, нижняя граница, уверенность."""
from datetime import date

from core import category_scoring as cs


def _dps(cat, scores):
    return [{"category": cat, "threads_best": s, "tg_quality": None} for s in scores]


def test_non_bank_categories_ignored():
    # в петлю идут только 7 крипто-категорий банка; «личное»/UNKNOWN — мимо
    dps = (_dps("рынок", [60, 60, 60, 60]) + _dps("личное", [95, 95, 95, 95])
           + _dps(cs.topic_category.UNKNOWN, [10]))
    rows = {r["category"]: r for r in cs.leaderboard(dps)}
    assert "рынок" in rows
    assert "личное" not in rows and cs.topic_category.UNKNOWN not in rows


def test_topic_score_blend_and_fallback():
    assert cs.topic_score(40, 80) == 66.0     # 0.65*80 + 0.35*40
    assert cs.topic_score(None, 80) == 80.0
    assert cs.topic_score(40, None) == 40.0
    assert cs.topic_score(None, None) is None


def test_shrinkage_pulls_small_sample_to_global_mean():
    # 1 «везучая» точка 100 в философии vs 4 по 40 в рынке → μ≈52
    dps = _dps("философия", [100]) + _dps("рынок", [40, 40, 40, 40])
    rows = {r["category"]: r for r in cs.leaderboard(dps)}
    fil = rows["философия"]
    assert 52 < fil["shrunk"] < 100          # усадка утянула 100 к μ, не поверила одной точке
    assert fil["confidence"] < 0.3           # мало данных → низкая уверенность


def test_lucky_single_point_barely_moves_weight():
    dps = _dps("философия", [100]) + _dps("рынок", [40, 40, 40, 40])
    w = cs.category_weights(dps)
    assert 0.97 < w["философия"] < 1.10       # один «стрельнувший» пост НЕ задирает вес
    assert w["рынок"] < 1.0                   # уверенно-ниже-среднего → вниз


def test_confident_strong_and_weak_tilt():
    dps = _dps("рынок", [80] * 8) + _dps("словарь", [20] * 8)
    w = cs.category_weights(dps)
    assert w["рынок"] > 1.1                    # много данных + сильная → заметно вверх
    assert w["словарь"] < 0.9                  # много данных + слабая → вниз
    assert cs.WEIGHT_MIN <= w["словарь"] and w["рынок"] <= cs.WEIGHT_MAX


def test_variance_lowers_ranking():
    # одинаковое среднее 80, но у словаря высокая дисперсия → ниже по нижней границе
    dps = _dps("рынок", [80, 80, 80, 80]) + _dps("словарь", [95, 65, 95, 65])
    rows = cs.leaderboard(dps)
    assert rows[0]["category"] == "рынок"     # стабильная сверху, шумная ниже
    assert rows[0]["lower"] > rows[1]["lower"]


def test_single_category_neutral():
    w = cs.category_weights(_dps("рынок", [80, 80, 80, 80]))
    assert w["рынок"] == 1.0                   # сравнивать не с чем → нейтрально
    assert w["философия"] == 1.0               # нет данных → нейтрально


def test_recency_lifts_recent():
    today = date(2026, 7, 17)
    dps = [{"category": "рынок", "threads_best": 80, "tg_quality": None, "created": "2026-07-17"},
           {"category": "рынок", "threads_best": 20, "tg_quality": None, "created": "2026-03-19"}]
    with_rec = cs.leaderboard(dps, today=today)[0]["mean"]
    flat = cs.leaderboard(dps, today=None)[0]["mean"]
    assert flat == 50.0
    assert with_rec > flat                     # свежий успех тянет среднее вверх


# --- #3 разведка (bandit) ---

def test_explore_bonus_favors_undersampled():
    dps = _dps("рынок", [50] * 8)              # хорошо изучена
    b = cs.explore_bonus(dps)
    assert b["философия"] == round(cs.EXPLORE_MAX / 1.0, 3)   # не пробована → максимум
    assert b["рынок"] < b["философия"]         # изученная → бонус меньше


def test_picker_weights_explore_lifts_unknown():
    dps = _dps("рынок", [50] * 4)              # нейтральная, изучена
    pw = cs.picker_weights(dps)
    assert pw["философия"] > pw["рынок"]        # неизвестную пробуем охотнее нейтрально-изученной
    assert all(cs.WEIGHT_MIN <= v <= cs.WEIGHT_MAX for v in pw.values())


def test_exploration_saves_unlucky_from_starvation():
    # слабая категория с малой выборкой не падает в пол — разведка держит шанс отыграться
    dps = _dps("рынок", [80] * 8) + _dps("словарь", [20, 25])
    exploit = cs.category_weights(dps)
    pw = cs.picker_weights(dps)
    assert pw["словарь"] > exploit["словарь"]   # разведка приподняла над чистой эксплуатацией
