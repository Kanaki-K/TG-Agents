"""ЗАМОК ПРОГОНА: проверить ≠ занять, и мёртвый процесс не держит конвейер час (16.09.2026).

ЖИВОЙ СЛУЧАЙ. Ассистент дважды позвал `run_lock.acquire('проверка')`, чтобы посмотреть, идёт ли
прогон. Но acquire не проверяет, а БЕРЁТ: первый раз замок держал прогон владельца и пришёл отказ,
второй раз замок был свободен — и достался процессу ассистента, который тут же завершился. Владелец
получил «⏳ Уже идёт "проверка" (pid 8581)» и остался без конвейера до протухания замка через час.

ДВЕ ПРИЧИНЫ, ОБЕ ЧИНЯТСЯ:
1. не было read-only проверки — теперь есть `is_busy()`;
2. замок держался по таймеру, хотя процесс был мёртв — теперь смотрим живость pid.

⚠️ ЖИВОСТЬ ТОЛЬКО НА СВОЕЙ МАШИНЕ. /workspace — общий диск между Windows владельца и Linux-контейнером
ассистента. Pid 8581 из контейнера на Windows означает другой процесс или ничей, поэтому в замке
пишется `host`, и живость проверяется, лишь когда хост совпал. Иначе «уборка мусора» сняла бы ЖИВОЙ
прогон владельца — отказ хуже, но снос чужого прогона хуже намного.

Запуск: python -m pytest tests/test_run_lock_liveness.py"""
from __future__ import annotations

import json
import os
import socket
import time

import pytest

from core import run_lock


@pytest.fixture
def lock(tmp_path, monkeypatch):
    """Замок в песочнице: тесты не трогают ЖИВОЙ data/pipeline.lock владельца."""
    monkeypatch.setattr(run_lock, "LOCK", tmp_path / "pipeline.lock")
    return run_lock.LOCK


def _write(path, **over):
    row = {"what": "скоуп", "pid": os.getpid(), "host": socket.gethostname(),
           "at_ts": time.time(), "at": "2026-09-16T19:33:27+02:00"}
    row.update(over)
    path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")


# ── проверить ≠ занять ──────────────────────────────────────────────────────────────────────────

def test_is_busy_does_not_take_the_lock(lock):
    """Главный тест: read-only проверка НЕ создаёт замок. Из-за этого владелец потерял час."""
    assert run_lock.is_busy() is False
    assert not lock.exists(), "проверка занятости создала замок — ровно баг 16.09"


def test_is_busy_sees_a_live_run(lock):
    _write(lock)
    assert run_lock.is_busy() is True


# ── мёртвый процесс замка не держит ─────────────────────────────────────────────────────────────

def test_dead_pid_on_this_host_frees_the_lock(lock):
    """Процесса нет — замок брошен. Ждать час незачем: именно так и выглядел случай 16.09."""
    _write(lock, pid=999_999)                       # заведомо несуществующий
    assert run_lock.holder() == {}
    assert run_lock.acquire("новый прогон") is True


def test_live_pid_on_this_host_keeps_the_lock(lock):
    _write(lock)                                    # pid текущего процесса — он жив
    assert run_lock.acquire("второй") is False


def test_foreign_host_is_never_probed(lock):
    """Чужая машина: pid оттуда у нас ничего не значит. Ждём таймер, живость НЕ проверяем —
    иначе снесли бы ЖИВОЙ прогон владельца на Windows."""
    _write(lock, pid=999_999, host="DESKTOP-LODK9")
    assert run_lock.holder() != {}, "замок чужой машины снят по нашему pid — это снос чужого прогона"
    assert run_lock.acquire("наш") is False


def test_legacy_lock_without_host_is_respected(lock):
    """Замки, записанные до 16.09, поля host не имеют — считаем их чужими и ждём таймер."""
    row = {"what": "скоуп", "pid": 999_999, "at_ts": time.time(), "at": "2026-09-16T19:33:27+02:00"}
    lock.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    assert run_lock.holder() != {}


def test_stale_by_timer_still_works(lock):
    """Страховка по времени осталась: чужой хост с мёртвым процессом освободится через час."""
    _write(lock, pid=999_999, host="DESKTOP-LODK9", at_ts=time.time() - run_lock.STALE_SECONDS - 10)
    assert run_lock.holder() == {}


# ── снятие ──────────────────────────────────────────────────────────────────────────────────────

def test_release_only_removes_our_own_lock(lock):
    _write(lock, pid=999_999, host="DESKTOP-LODK9")
    run_lock.release()
    assert lock.exists(), "сняли ЧУЖОЙ замок — так теряется чужой прогон"
    _write(lock)
    run_lock.release()
    assert not lock.exists()


def test_acquire_writes_the_host(lock):
    assert run_lock.acquire("скоуп")
    assert json.loads(lock.read_text(encoding="utf-8"))["host"] == socket.gethostname()


def test_busy_message_names_who_and_when(lock):
    _write(lock)
    msg = run_lock.busy_message()
    assert "скоуп" in msg and "19:33" in msg
