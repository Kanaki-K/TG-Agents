"""Дневной счётчик подписчиков Threads.

Без сети: журнал уводим во временный файл. Проверяем ровно то, ради чего модуль написан —
что прирост НЕ приписывается посту, когда в дне постов несколько (делить поровну = выдумывать),
что разрыв в снимках не склеивается в фальшивую дельту, и что на коротком ряду модуль честно
отказывается считать средние, а не выдаёт красивое число."""
import json

import pytest

from core import threads_followers as tf


@pytest.fixture
def journal(tmp_path, monkeypatch):
    path = tmp_path / "followers.jsonl"
    monkeypatch.setattr(tf, "JOURNAL", path)
    return path


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def test_snapshot_one_per_day_last_wins(journal):
    tf.snapshot(600, when="2026-09-09")
    tf.snapshot(610, when="2026-09-09")      # перезапуск того же дня не плодит дубль
    rows = tf.entries()
    assert len(rows) == 1 and rows[0]["followers"] == 610


def test_broken_line_does_not_kill_the_series(journal):
    journal.write_text('{"date": "2026-09-09", "followers": 600}\nне json\n'
                       '{"date": "2026-09-10", "followers": 604}\n', encoding="utf-8")
    assert [r["followers"] for r in tf.entries()] == [600, 604]


def test_growth_belongs_to_the_earlier_day(journal):
    """Пост дня D живёт в окне между снимком D и снимком D+1 — дельта принадлежит D, не D+1."""
    _write(journal, [{"date": "2026-09-09", "followers": 600},
                     {"date": "2026-09-10", "followers": 607}])
    assert tf.growth() == {"2026-09-09": 7}


def test_gap_in_snapshots_is_not_glued(journal):
    """Пропустили день — дельта за двое суток к одному дню не приписывается."""
    _write(journal, [{"date": "2026-09-09", "followers": 600},
                     {"date": "2026-09-11", "followers": 620}])
    assert tf.growth() == {}


def test_losses_are_recorded_not_swallowed(journal):
    _write(journal, [{"date": "2026-09-09", "followers": 600},
                     {"date": "2026-09-10", "followers": 594}])
    assert tf.growth() == {"2026-09-09": -6}


def test_attribution_only_for_days_with_a_single_post(journal):
    _write(journal, [{"date": "2026-09-09", "followers": 600},
                     {"date": "2026-09-10", "followers": 610},
                     {"date": "2026-09-11", "followers": 615}])
    posts = [{"id": "1", "date": "2026-09-09T16:00:00+0000", "text": "один в дне"},
             {"id": "2", "date": "2026-09-10T16:00:00+0000", "text": "первый из двух"},
             {"id": "3", "date": "2026-09-10T18:00:00+0000", "text": "второй из двух"}]
    tf.attach(posts)
    assert posts[0]["followers_gain"] == 10 and posts[0]["gain_solo"] is True
    for p in posts[1:]:
        assert p["followers_gain"] == 5 and p["gain_posts"] == 2
        assert p["gain_solo"] is False          # прирост дня между двумя постами не делим


def test_short_series_refuses_to_average(journal):
    _write(journal, [{"date": "2026-09-09", "followers": 600},
                     {"date": "2026-09-10", "followers": 607}])
    text = tf.report()
    assert "620" not in text and "медиана" not in text
    assert "нужно ≥7 суток" in text


def test_quiet_snapshot_does_not_call_api_twice_a_day(journal, monkeypatch):
    calls = []
    monkeypatch.setattr(tf, "snapshot", lambda *a, **k: calls.append(1) or {"followers": 1})
    _write(journal, [{"date": tf._today(), "followers": 620}])
    assert tf.snapshot_quiet() is None and not calls


def test_quiet_snapshot_swallows_network_failure(journal, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("Мета молчит")
    monkeypatch.setattr(tf, "snapshot", _boom)
    assert tf.snapshot_quiet() is None          # фоновая гигиена не имеет права уронить прогон
