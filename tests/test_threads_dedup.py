"""Threads анти-повтор — дайджест окна свежести и мягкий отказ (без API/сети)."""
from core import threads_dedup


def test_digest_windows_and_orders():
    posts = [
        {"id": 1, "date": "2026-07-01T10:00:00", "text": "старый пост"},
        {"id": 2, "date": "2026-07-20T10:00:00", "text": "недавний A"},
        {"id": 3, "date": "2026-07-25T10:00:00", "text": "недавний B"},
        {"id": 4, "date": "2026-05-01T10:00:00", "text": "древний пост"},
    ]
    topics = {"2": {"title": "Заголовок A", "theme": "личное", "summary": "суть A"},
              "3": {"title": "Заголовок B", "theme": "крипта", "summary": "суть B"}}
    d = threads_dedup.digest(weeks=4, posts=posts, topics=topics)
    lines = d.splitlines()
    assert len(lines) == 3                     # id4 (05-01) вне окна 4 нед от свежего (07-25) — отброшен
    assert "древний" not in d
    assert lines[0].startswith("2026-07-25")   # свежие сверху
    assert "Заголовок B" in lines[0]
    assert "Заголовок A" in d                  # id без топика берёт заголовок из текста — не падаем


def test_digest_empty():
    assert "нет выгрузки" in threads_dedup.digest(posts=[], topics={}).lower()


def test_check_empty_candidate_soft_ok():
    v = threads_dedup.check("")                # пустой кандидат → мягкий ОК БЕЗ вызова API
    assert "СТАТУС: ОК" in v
