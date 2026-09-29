"""Очередь на съём страниц Insights.

Держит два решения, без которых замер врёт: свежий пост важнее старого (у него окно замера
уходит), а пост, померенный молодым, нужно домерить после созревания — иначе мы сравниваем
двухдневный кадр с итоговым и делаем вывод про качество текста из разницы в возрасте."""
import json
from datetime import date, timedelta

import pytest

from core import threads_app_metrics as A
from core import threads_insights_queue as Q


def _post(pid, days_ago, code):
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    return {"id": pid, "date": f"{d}T16:00:00+0000", "text": f"пост {pid}",
            "permalink": f"https://www.threads.com/@kanaki.crypto/post/{code}"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "THREADS_POSTS", tmp_path / "posts.json")
    monkeypatch.setattr(Q, "QUEUE", tmp_path / "queue.txt")
    monkeypatch.setattr(A, "STORE", tmp_path / "app.json")
    return tmp_path


def _write(env, posts, known=None):
    (env / "posts.json").write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
    (env / "app.json").write_text(json.dumps(known or {}, ensure_ascii=False), encoding="utf-8")


def test_never_measured_post_is_queued(env):
    _write(env, [_post("1", 3, "AAA")])
    assert [Q.code_of(p) for p in Q.pending()] == ["AAA"]


def test_post_measured_when_mature_is_not_queued_again(env):
    """Иначе очередь превратится в вечный круг по одним и тем же постам."""
    _write(env, [_post("1", 40, "AAA")], {"1": {"views": 100, "age_days_at_snap": 20}})
    assert Q.pending() == []


def test_post_measured_too_early_is_queued_after_it_matures(env):
    """Владелец: «некоторые посты живут дольше четырёх дней» — снимок на второй день это не итог."""
    _write(env, [_post("1", 30, "AAA")], {"1": {"views": 100, "age_days_at_snap": 2}})
    assert [Q.code_of(p) for p in Q.pending()] == ["AAA"]


def test_young_post_measured_young_waits_until_it_matures(env):
    _write(env, [_post("1", 5, "AAA")], {"1": {"views": 100, "age_days_at_snap": 2}})
    assert Q.pending() == []          # мерить второй раз рано — он ещё растёт


def test_new_posts_come_before_re_measurements(env):
    """У свежего поста окно замера уходит, у старого уже нет — порядок решает здесь, не в скрипте."""
    posts = [_post("1", 30, "OLD"), _post("2", 2, "NEW")]
    _write(env, posts, {"1": {"views": 100, "age_days_at_snap": 1}})
    assert [Q.code_of(p) for p in Q.pending()] == ["NEW", "OLD"]


def test_posts_older_than_the_window_are_ignored(env):
    _write(env, [_post("1", 200, "AAA")])
    assert Q.pending() == []
