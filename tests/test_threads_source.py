"""Откуда Threads-ветка берёт исходный ТГ-пост: журнал (боевой путь) и выгрузка канала (обкатка).

Живой баг, из-за которого тест и написан: `content_plan.infer_kind` отвечает ИСТОРИЧЕСКИМ именем
формата ('short'), а сравнивали его с каноничным 'scope' — совпадения не было НИКОГДА, и «скоупы в
выгрузке не находились», хотя их там сотня."""
import json

from core import published_journal, threads_source as ts


def _channel(tmp_path, monkeypatch, posts, formats=None, topics=None):
    (tmp_path / "posts.json").write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "formats.json").write_text(json.dumps(formats or {}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "topics.json").write_text(json.dumps(topics or {}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ts, "POSTS_JSON", tmp_path / "posts.json")
    monkeypatch.setattr(ts, "FORMATS_JSON", tmp_path / "formats.json")
    monkeypatch.setattr(ts, "TOPICS_JSON", tmp_path / "topics.json")


def test_picks_nth_post_of_its_format_from_channel(tmp_path, monkeypatch):
    posts = [
        {"id": 1, "date": "2026-08-01T16:00:00", "text": "к" * 1200},          # скоуп (старый)
        {"id": 2, "date": "2026-08-02T16:00:00", "text": "ф" * 3000},          # флагман
        {"id": 3, "date": "2026-08-03T16:00:00", "text": "к" * 1300},          # скоуп (свежий)
    ]
    _channel(tmp_path, monkeypatch, posts, topics={"3": {"title": "Свежий скоуп"}})

    first = ts.from_channel("scope", 1)
    assert first["date"] == "2026-08-03" and first["theme"] == "Свежий скоуп"   # 1 = самый свежий
    assert "#3" in first["origin"]
    assert ts.from_channel("scope", 2)["date"] == "2026-08-01"                  # 2 = предыдущий
    assert ts.from_channel("flagship", 1)["date"] == "2026-08-02"               # формат не путается
    assert ts.from_channel("scope", 9) is None                                  # столько постов нет


def test_service_messages_and_foreign_formats_are_skipped(tmp_path, monkeypatch):
    posts = [
        {"id": 10, "date": "2026-08-01T16:00:00", "text": "🖥 Медиа | 🥸 Мемы"},   # футер-сообщение
        {"id": 11, "date": "2026-08-02T16:00:00", "text": "л" * 900},            # размечен как личный
        {"id": 12, "date": "2026-08-03T16:00:00", "text": "к" * 1000},           # настоящий скоуп
    ]
    _channel(tmp_path, monkeypatch, posts, formats={"11": "личный"})
    picked = ts.from_channel("scope", 1)
    assert picked["text"].startswith("к") and "#12" in picked["origin"]
    assert ts.from_channel("scope", 2) is None                                   # больше кандидатов нет


def test_resolve_switches_between_journal_and_channel(tmp_path, monkeypatch):
    monkeypatch.setattr(published_journal, "JOURNAL", tmp_path / "journal.jsonl")
    monkeypatch.setattr(published_journal, "LEGACY_JOURNAL", tmp_path / "legacy.jsonl")
    published_journal.record("Свежий из журнала", theme="из журнала", kind="scope")
    _channel(tmp_path, monkeypatch, [{"id": 5, "date": "2026-08-01T16:00:00", "text": "к" * 1000}])

    assert ts.resolve("scope")["text"] == "Свежий из журнала"        # 0 = боевой путь
    assert ts.resolve("scope")["origin"] == "журнал вышедших постов"
    assert ts.resolve("scope", 1)["text"].startswith("к")            # ≥1 = обкатка по истории канала
