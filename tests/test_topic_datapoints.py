"""Тесты сборки датапоинтов (core/topic_datapoints): join флагман+дистилляция → датапоинт."""
from core import topic_datapoints as td
from core import topic_category as tc

BANK = """## Слой 3.4 — Математика стратегии
- IRR — почему «иксы» врут: 3x за 5 лет ≠ 3x за год
"""


def _bank(tmp_path, monkeypatch):
    f = tmp_path / "flagship_topics.md"
    f.write_text(BANK, encoding="utf-8")
    monkeypatch.setattr(tc, "BANK_FILE", f)


FLAGSHIP = {
    "date": "2026-07-16",
    "theme": "IRR — почему «иксы» врут: 3x за 5 лет ≠ 3x за год",
    "text": "иксы врут доходность годовых процент удвоение дистанция актив держать",
}


def test_datapoint_joins_all_three(tmp_path, monkeypatch):
    _bank(tmp_path, monkeypatch)
    tg_posts = [
        {"text": "иксы врут доходность годовых процент удвоение дистанция актив держать дольше", "quality": 72.0},
        {"text": "постороннее про стейблы рельсы", "quality": 5.0},
    ]
    threads_posts = [
        {"date": "2026-07-16", "text": "иксы врут годовых процент", "quality": 60.0},
        {"date": "2026-07-16", "text": "доходность удвоение дистанция актив", "quality": 80.0},
    ]
    res = td.build([FLAGSHIP], tg_posts, threads_posts)
    assert len(res["datapoints"]) == 1
    dp = res["datapoints"][0]
    assert dp["category"] == "рынок"          # Слой 3.* → рынок
    assert dp["threads_best"] == 80.0         # ЛУЧШИЙ из двух постов, не среднее
    assert dp["tg_quality"] == 72.0           # матч с постом канала
    assert dp["n_threads"] == 2
    assert dp["created"] == "2026-07-16"


def test_tg_none_when_no_match(tmp_path, monkeypatch):
    _bank(tmp_path, monkeypatch)
    threads_posts = [{"date": "2026-07-16", "text": "иксы врут годовых процент", "quality": 60.0}]
    res = td.build([FLAGSHIP], [{"text": "ничего общего", "quality": 9.0}], threads_posts)
    dp = res["datapoints"][0]
    assert dp["tg_quality"] is None           # поста канала не нашли — ТГ-объектив пуст
    assert dp["threads_best"] == 60.0         # Threads-объектив есть


def test_unmatched_threads_reported(tmp_path, monkeypatch):
    _bank(tmp_path, monkeypatch)
    threads_posts = [{"date": "2026-07-16", "text": "иксы врут годовых", "quality": 60.0},
                     {"date": "2026-07-16", "text": "личный пост ни о чём общем", "quality": 90.0}]
    res = td.build([FLAGSHIP], [], threads_posts)
    assert len(res["datapoints"]) == 1
    assert len(res["unmatched_threads"]) == 1  # личный пост не привязался
