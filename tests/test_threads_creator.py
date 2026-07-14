"""Мини-флагман Threads — журнал вышедших флагманов + гейт пустого журнала в пайплайне.

Без API/сети: проверяем сантехнику (запись/чтение журнала, обрезку меты, отказ на пустом журнале).
Качество самой дистилляции проверяется на живых прогонах, не юнит-тестом."""
import json

from core import flagship_journal


def test_journal_round_trip(tmp_path, monkeypatch):
    j = tmp_path / "published_flagships.jsonl"
    monkeypatch.setattr(flagship_journal, "JOURNAL", j)
    assert flagship_journal.latest() is None                    # журнала ещё нет

    flagship_journal.record("Тело флагмана\n[[SPLIT]]\nвнутренняя мета", theme="prediction markets")
    flagship_journal.record("Второй флагман", theme="стейблкоины")

    last = flagship_journal.latest()
    assert last is not None
    assert last["theme"] == "стейблкоины"                       # latest = ПОСЛЕДНЯЯ запись
    assert last["text"] == "Второй флагман"

    lines = [json.loads(l) for l in j.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2                                      # append-only, не перезапись
    assert lines[0]["text"] == "Тело флагмана"                  # мета после [[SPLIT]] отброшена
    assert "date" in lines[0]


def test_record_empty_or_meta_only_ignored(tmp_path, monkeypatch):
    j = tmp_path / "pf.jsonl"
    monkeypatch.setattr(flagship_journal, "JOURNAL", j)
    flagship_journal.record("", theme="x")                      # пустой текст — не пишем
    flagship_journal.record("   ", theme="y")                   # пробелы — не пишем
    flagship_journal.record("[[SPLIT]]\nтолько мета")           # тело пустое после обрезки — не пишем
    assert flagship_journal.latest() is None


def test_pipeline_stops_on_empty_journal(tmp_path, monkeypatch):
    import run_threads_pipeline as rtp
    monkeypatch.setattr(rtp.flagship_journal, "JOURNAL", tmp_path / "empty.jsonl")
    out = rtp.run_threads_cycle(emit=lambda *_: None)           # emit-заглушка: без вывода в терминал
    low = out.lower()
    assert "журнал" in low and "пуст" in low                    # штатный отказ, не падение/не вызов API
