"""Тесты сигнала пикера флагманов (core/self_learn): взвешенная выборка + сборка ТГ-датапоинтов."""
import json
from datetime import datetime

from core import analytics, self_learn, topic_category as tc


def test_size_and_unique():
    out = self_learn.weighted_sample(list(range(20)), 5, lambda x: 1.0)
    assert len(out) == 5 and len(set(out)) == 5 and set(out) <= set(range(20))


def test_k_ge_len_returns_all():
    assert sorted(self_learn.weighted_sample([1, 2, 3], 10, lambda x: 1.0)) == [1, 2, 3]


def test_empty():
    assert self_learn.weighted_sample([], 5, lambda x: 1.0) == []


def test_favors_high_weight():
    items = ["a", "b", "c", "d"]
    w = {"a": 8.0}
    top = {it: 0 for it in items}
    for _ in range(500):
        top[self_learn.weighted_sample(items, 1, lambda x: w.get(x, 1.0))[0]] += 1
    assert top["a"] > top["b"] and top["a"] > top["c"]  # тяжёлый чаще становится топ-1


# --- сквозной путь данных пикера флагмана (интеграция tg_datapoints/tg_category_weights) ---

def _posts():
    return [
        {"id": 1, "dt": datetime(2026, 7, 10, 12), "date": "2026-07-10 12:00",
         "views": 500, "reactions": 10, "comments": 3, "forwards": 5, "text": "рынок"},
        {"id": 2, "dt": datetime(2026, 7, 11, 12), "date": "2026-07-11 12:00",
         "views": 400, "reactions": 5, "comments": 1, "forwards": 1, "text": "личное"},
        {"id": 3, "dt": datetime(2026, 7, 12, 12), "date": "2026-07-12 12:00",
         "views": 600, "reactions": 8, "comments": 2, "forwards": 2, "text": "без темы"},
    ]


def test_tg_datapoints_filters_and_shapes(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics, "_load_posts", lambda: _posts())
    topics = tmp_path / "post_topics.json"
    topics.write_text(json.dumps({"1": {"category": "рынок", "angle": "мнение"},
                                  "2": {"category": "личное", "angle": "личный"}}), encoding="utf-8")
    monkeypatch.setattr(self_learn, "_TG_TOPICS", topics)
    dps = self_learn.tg_datapoints()
    assert [d["category"] for d in dps] == ["рынок"]      # «личное» и пост без темы отфильтрованы
    assert dps[0]["angle"] == "мнение" and dps[0]["threads_best"] is None
    assert dps[0]["created"] == "2026-07-10"


def test_tg_category_weights_neutral_when_no_data(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics, "_load_posts", lambda: [])
    monkeypatch.setattr(self_learn, "_TG_TOPICS", tmp_path / "absent.json")   # нет файла → io_safe → {}
    w = self_learn.tg_category_weights()
    assert set(w) == set(tc.all_slugs()) and all(v == 1.0 for v in w.values())  # fail-safe: равномерно
