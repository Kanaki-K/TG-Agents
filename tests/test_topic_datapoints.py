"""Тесты сборки датапоинтов (core/topic_datapoints): журнал (тугой) + флагман-фаззи (запасной)."""
from core import topic_datapoints as td
from core import topic_category as tc

BANK = """## Слой 3.4 — Математика стратегии
- IRR — иксы врут
"""

FLAG = {"date": "2026-07-16", "theme": "IRR — иксы врут",
        "text": "иксы врут доходность годовых процент удвоение дистанция актив держать"}
ENTRY = {"flagship_date": "2026-07-16", "theme": "IRR — иксы врут", "category": "рынок",
         "posts": ["иксы врут годовых процент", "доходность удвоение дистанция актив"], "post_ids": []}
TG = [{"text": "иксы врут доходность годовых процент удвоение дистанция актив держать дольше", "quality": 72.0}]
THREADS = [{"id": "1", "date": "2026-07-16", "text": "иксы врут годовых процент", "quality": 60.0},
           {"id": "2", "date": "2026-07-16", "text": "доходность удвоение дистанция актив", "quality": 80.0}]


def _bank(tmp_path, monkeypatch):
    f = tmp_path / "flagship_topics.md"
    f.write_text(BANK, encoding="utf-8")
    monkeypatch.setattr(tc, "BANK_FILE", f)


def test_journal_path_tight(tmp_path, monkeypatch):
    _bank(tmp_path, monkeypatch)
    res = td.build([ENTRY], [FLAG], TG, THREADS)
    assert len(res["datapoints"]) == 1
    dp = res["datapoints"][0]
    assert dp["category"] == "рынок"          # из записи журнала
    assert dp["via"] == "text"                # связь через текст серии (тугой), не фаззи
    assert dp["threads_best"] == 80.0         # лучший из двух
    assert dp["tg_quality"] == 72.0           # флагман ↔ пост канала
    assert dp["n_threads"] == 2


def test_flagship_fuzzy_fallback(tmp_path, monkeypatch):
    _bank(tmp_path, monkeypatch)
    # журнал ПУСТ (до-журнальная дистилляция) → должен сработать запасной флагман-фаззи
    res = td.build([], [FLAG], TG, THREADS)
    assert len(res["datapoints"]) == 1
    dp = res["datapoints"][0]
    assert dp["via"] == "flagship-fuzzy"
    assert dp["category"] == "рынок"          # из банка (фаззи-путь)
    assert dp["threads_best"] == 80.0


def test_tg_none_when_no_channel_match(tmp_path, monkeypatch):
    _bank(tmp_path, monkeypatch)
    res = td.build([ENTRY], [FLAG], [{"text": "ничего общего", "quality": 9.0}], THREADS)
    dp = res["datapoints"][0]
    assert dp["tg_quality"] is None           # поста канала не нашли
    assert dp["threads_best"] == 80.0


def test_unmatched_reported(tmp_path, monkeypatch):
    _bank(tmp_path, monkeypatch)
    threads = THREADS + [{"id": "9", "date": "2026-07-16", "text": "личный пост про совсем иное вообще"}]
    res = td.build([ENTRY], [FLAG], TG, threads)
    assert len(res["datapoints"]) == 1
    assert len(res["unmatched_threads"]) == 1  # пост без категории и без связи не привязался


def test_standalone_self_written_becomes_datapoint(tmp_path, monkeypatch):
    _bank(tmp_path, monkeypatch)
    # пост НЕ из дистилляции, но классификатор дал крипто-категорию → свой датапоинт (via=standalone)
    threads = [{"id": "9", "date": "2026-07-10", "text": "мой пост про рынок",
                "category": "рынок", "quality": 70.0}]
    res = td.build([], [], [], threads)
    assert len(res["datapoints"]) == 1
    dp = res["datapoints"][0]
    assert dp["category"] == "рынок" and dp["via"] == "standalone"
    assert dp["threads_best"] == 70.0 and dp["tg_quality"] is None
    assert res["unmatched_threads"] == []


def test_personal_post_excluded_from_loop(tmp_path, monkeypatch):
    _bank(tmp_path, monkeypatch)
    threads = [{"id": "8", "date": "2026-07-10", "text": "личный пост", "category": "личное", "quality": 90.0}]
    res = td.build([], [], [], threads)
    assert res["datapoints"] == []             # «личное» — не крипто-категория, пикеру не действие
    assert len(res["unmatched_threads"]) == 1
