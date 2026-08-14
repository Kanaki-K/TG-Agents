"""Эмодзи-якорь заголовка: анти-повтор по факту канала + смысловая карта (владелец 14.08).

Механизм зеркалит анти-повтор кадра обложек: память — сам канал, вето — в промпт, проверка — в
линтер. Если это молча сломается, заголовки снова поедут одним 📊, и заметит это глазами владелец
через месяц, как было с обложками.
Запуск: python -m pytest tests/test_title_emoji.py
"""
from __future__ import annotations

import json

import pytest

from core import title_emoji as te

MAP = """# Карта

- 📊 — данные, замер, отчёт
- 🌐 — инфраструктура, сети, платежи
- 🔒 — безопасность, ключи, хранение
- не строка карты вовсе
"""


def _posts(tmp_path, rows):
    p = tmp_path / "channel_posts.json"
    p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return p


def _map(tmp_path):
    p = tmp_path / "emoji_map.md"
    p.write_text(MAP, encoding="utf-8")
    return p


def test_lead_emoji_ignores_bold_and_vs():
    assert te.lead_emoji("**⚡️ AI получил кошелёк**") == te.norm("⚡️")
    assert te.lead_emoji("Без якоря вовсе") == ""


def test_recent_is_newest_first_and_dedups(tmp_path):
    p = _posts(tmp_path, [
        {"id": 1, "date": "2026-08-01T10:00:00+00:00", "text": "🔒 Старый пост"},
        {"id": 2, "date": "2026-08-13T10:00:00+00:00", "text": "**📊 Свежий пост**"},
        {"id": 3, "date": "2026-08-12T10:00:00+00:00", "text": "🌐 Средний пост"},
        {"id": 4, "date": "2026-08-11T10:00:00+00:00", "text": "📊 Тот же ярлык"},
        {"id": 5, "date": "2026-08-10T10:00:00+00:00", "text": ""},
    ])
    assert te.recent(path=p) == ["📊", "🌐", "🔒"]        # порядок по дате, дубль 📊 один раз


def test_recent_missing_file_is_soft(tmp_path):
    assert te.recent(path=tmp_path / "нет-такого.json") == []


def test_repeats_recent_flags_used_emoji(tmp_path):
    p = _posts(tmp_path, [{"id": 1, "date": "2026-08-13T10:00:00+00:00", "text": "📊 Данные недели"}])
    assert te.repeats_recent("**📊 Новый заголовок**", path=p) == "📊"
    assert te.repeats_recent("**🔒 Новый заголовок**", path=p) == ""


def test_block_vetoes_used_and_offers_free(tmp_path):
    p = _posts(tmp_path, [{"id": 1, "date": "2026-08-13T10:00:00+00:00", "text": "📊 Данные недели"}])
    got = te.block(posts_path=p, map_path=_map(tmp_path))
    assert "НЕ бери: 📊" in got
    assert "🌐 — инфраструктура" in got
    assert "📊 — данные" not in got, "занятый эмодзи не предлагаем как свободный"


def test_block_empty_without_sources(tmp_path):
    assert te.block(posts_path=tmp_path / "нет.json", map_path=tmp_path / "нет.md") == ""


@pytest.mark.skipif(not te.MAP_FILE.exists(),
                    reason="карта смыслов живёт в ПРИВАТНОЙ памяти — в публичном CI её нет")
def test_real_map_covers_working_palette():
    """Боевая карта обязана перекрывать окно с запасом: иначе вето выжжет весь выбор."""
    rows = te._map_lines()
    assert len(rows) >= te.WINDOW * 4, "карта смыслов мала — после вето выбирать будет не из чего"
    assert len({e for e, _ in rows}) == len(rows), "дубли эмодзи в карте — смыслы начнут спорить"
