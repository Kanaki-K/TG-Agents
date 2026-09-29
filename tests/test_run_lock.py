"""Замок прогона. Живой случай 10.09: флагман и скоуп запущены параллельно и делили драфты,
аутбокс обложки и файл последнего формата."""
import json
import time

import pytest

from core import run_lock


@pytest.fixture(autouse=True)
def lockfile(tmp_path, monkeypatch):
    monkeypatch.setattr(run_lock, "LOCK", tmp_path / "pipeline.lock")


def test_second_run_is_refused_not_queued():
    """Ожидание хуже отказа: иначе владелец получит два поста в отложке подряд через полчаса."""
    assert run_lock.acquire("флагман") is True
    assert run_lock.acquire("скоуп") is False
    assert "Уже идёт" in run_lock.busy_message()


def test_release_frees_the_lock():
    run_lock.acquire("флагман")
    run_lock.release()
    assert run_lock.acquire("скоуп") is True


def test_stale_lock_is_taken_over():
    """Иначе один упавший процесс запер бы конвейер навсегда."""
    run_lock.LOCK.write_text(json.dumps({"what": "мертвец", "pid": 1,
                                         "at_ts": time.time() - run_lock.STALE_SECONDS - 10}),
                             encoding="utf-8")
    assert run_lock.holder() == {}
    assert run_lock.acquire("скоуп") is True


def test_broken_lock_file_does_not_block():
    run_lock.LOCK.write_text("не json", encoding="utf-8")
    assert run_lock.acquire("флагман") is True


def test_foreign_lock_is_not_released():
    """Перехватили протухший, а старый процесс ожил — пусть дорабатывает."""
    run_lock.LOCK.write_text(json.dumps({"what": "чужой", "pid": 999999, "at_ts": time.time()}),
                             encoding="utf-8")
    run_lock.release()
    assert run_lock.LOCK.exists()
