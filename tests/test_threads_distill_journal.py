"""Тесты журнала дистилляций Threads (core/threads_distill_journal): запись связи + категория."""
from core import threads_distill_journal as tdj
from core import topic_category as tc

SEP = "[[POST]]"
BANK = """## Слой 3.4 — Математика стратегии
- IRR — почему «иксы» врут: 3x за 5 лет ≠ 3x за год
"""


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(tdj, "JOURNAL", tmp_path / "threads_distillations.jsonl")
    bank = tmp_path / "flagship_topics.md"
    bank.write_text(BANK, encoding="utf-8")
    monkeypatch.setattr(tc, "BANK_FILE", bank)


def test_record_links_flagship_and_category(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    fl = {"date": "2026-07-16", "theme": "IRR — почему «иксы» врут: 3x за 5 лет ≠ 3x за год", "text": "…"}
    tdj.record(fl, f"пост один {SEP} пост два", SEP)
    e = tdj.entries()
    assert len(e) == 1
    assert e[0]["flagship_date"] == "2026-07-16"
    assert e[0]["category"] == "рынок"           # Слой 3.* → рынок
    assert e[0]["posts"] == ["пост один", "пост два"]


def test_empty_series_not_recorded(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    tdj.record({"date": "x", "theme": "y"}, "   ", SEP)
    assert tdj.entries() == []


def test_append_only(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    tdj.record({"date": "1", "theme": "t"}, "a", SEP)
    tdj.record({"date": "2", "theme": "t"}, "b", SEP)
    assert len(tdj.entries()) == 2


def test_missing_journal_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(tdj, "JOURNAL", tmp_path / "нет.jsonl")
    assert tdj.entries() == []
