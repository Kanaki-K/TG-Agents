"""Честный скоринг постов (core.tg_scoring) — чистые функции на синтетическом корпусе.

Без сети/LLM/файлов: строим посты руками и проверяем _ranker (перцентиль), гейт зрелости
(MATURITY_DAYS), порог охвата (view_floor — низкий знаменатель не судим), присвоение тиров.
tg_scoring уже в проде Аналитика (analyst_tools honest_ranking) — эти инварианты держат его честность."""
from datetime import datetime, timedelta

from core import tg_scoring


# --- _ranker: v → доля значений ≤ v ---

def test_ranker_empty_is_zero():
    assert tg_scoring._ranker([])(5.0) == 0.0


def test_ranker_percentile():
    r = tg_scoring._ranker([1, 2, 3, 4])
    assert r(4) == 1.0          # максимум → 100-й перцентиль
    assert r(0) == 0.0          # ниже всех → 0
    assert r(2) == 0.5          # bisect_right([1,2,3,4], 2)=2 → 2/4
    assert r(2.5) == 0.5


# --- enrich: корпус ---

_NOW = datetime(2026, 7, 1)


def _post(pid, views, fwd, com, rea, days_ago):
    return {"id": pid, "date": "2026-06-01", "preview": f"p{pid}", "format": "флагман",
            "views": views, "forwards": fwd, "comments": com, "reactions": rea,
            "dt": _NOW - timedelta(days=days_ago)}


def _corpus():
    # 5 зрелых с достаточным охватом (views 1000), 1 зрелый ниже порога (views 150),
    # 1 свежий (age < 14). Самый свежий = точка отсчёта «сейчас».
    return [
        _post(1, 1000, 50, 10, 20, 30),   # высокий fwd_rate .05 → виральный
        _post(2, 1000, 5, 40, 20, 30),    # высокий comment_rate
        _post(3, 1000, 5, 5, 60, 30),     # высокий react_rate
        _post(4, 1000, 4, 4, 10, 30),     # ровный
        _post(5, 1000, 3, 3, 8, 30),      # ровный
        _post(6, 150, 100, 100, 100, 30), # МАТЁРЫЙ, но views < floor → не судим (ровный)
        _post(7, 500, 50, 50, 50, 3),     # свежий (age 0 относительно самого свежего)
    ]


def test_enrich_empty_and_zero_views():
    assert tg_scoring.enrich([])["measured"] == 0
    zero = [dict(_post(1, 0, 0, 0, 0, 30))]
    assert tg_scoring.enrich(zero)["measured"] == 0


def test_enrich_baselines():
    posts = _corpus()
    base = tg_scoring.enrich(posts)
    assert base["measured"] == 7        # все с views>0
    assert base["mature"] == 6          # свежий (#7) не зрел
    assert base["eligible"] == 5        # #6 ниже порога охвата выпал
    assert base["median_views"] == 1000
    assert base["view_floor"] == 200    # max(100, median*0.2)
    assert base["maturity_days"] == tg_scoring.MATURITY_DAYS


def test_enrich_fresh_not_judged():
    posts = _corpus()
    tg_scoring.enrich(posts)
    fresh = next(p for p in posts if p["id"] == 7)
    assert fresh["mature"] is False
    assert fresh["quality"] is None
    assert fresh["tier_ru"] == "свежий (рано судить)"


def test_enrich_view_floor_protects_low_denominator():
    # #6 матёрый и с огромными rate, НО views ниже порога → в качество не берём (ровный, quality None)
    posts = _corpus()
    tg_scoring.enrich(posts)
    low = next(p for p in posts if p["id"] == 6)
    assert low["mature"] is True
    assert low["quality"] is None
    assert low["tier_ru"] == "ровный"


def test_enrich_tiers_and_quality():
    posts = _corpus()
    tg_scoring.enrich(posts)
    by_id = {p["id"]: p for p in posts}
    # #1 — топ по fwd_rate и views ≥ медианы → виральный
    assert by_id[1]["tier_ru"] == "виральный"
    # все eligible (#1..#5) получили числовое Качество
    for pid in (1, 2, 3, 4, 5):
        assert by_id[pid]["quality"] is not None
