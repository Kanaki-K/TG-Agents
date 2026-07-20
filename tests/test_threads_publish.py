"""Полоса записи Threads: два ключа, бюджеты, линт охвата, publish без сети (всё замокано).

Проверяем то, что охраняет аккаунт: запись закрыта по умолчанию даже при открытом чтении;
бюджеты записи бьют по рукам; пост со ссылкой/хештегом не уходит; happy-path шлёт ровно
два write-запроса (контейнер + publish) с правильными параметрами; отказ квоты Meta =
fail-closed. Запуск: python -m pytest.
"""
from __future__ import annotations

import json

import pytest

from connectors.threads import _guard, publish


@pytest.fixture()
def guard_sandbox(tmp_path, monkeypatch):
    """Изолированный _guard: файлы в tmp, паузы нулевые, счётчики сброшены."""
    monkeypatch.setattr(_guard, "UNLOCK_FILE", tmp_path / "threads_unlocked")
    monkeypatch.setattr(_guard, "WRITE_UNLOCK_FILE", tmp_path / "threads_write_unlocked")
    monkeypatch.setattr(_guard, "COOLDOWN_FILE", tmp_path / "threads_cooldown")
    monkeypatch.setattr(_guard, "LOG_FILE", tmp_path / "threads_api_log.jsonl")
    for name in ("GAP_MIN", "GAP_MAX", "WRITE_GAP_MIN", "WRITE_GAP_MAX"):
        monkeypatch.setattr(_guard, name, 0.0)
    monkeypatch.setattr(_guard, "_run_count", 0)
    monkeypatch.setattr(_guard, "_write_run_count", 0)
    monkeypatch.setattr(_guard, "_last_call_at", 0.0)
    monkeypatch.setattr(_guard, "_last_write_at", 0.0)
    return tmp_path


def _unlock_read(tmp_path):
    (tmp_path / "threads_unlocked").write_text("тест\nчтение", encoding="utf-8")


def _unlock_write(tmp_path):
    (tmp_path / "threads_write_unlocked").write_text("тест\nзапись", encoding="utf-8")


# --- _guard: полоса записи --------------------------------------------------------------------

def test_write_closed_by_default_even_when_read_open(guard_sandbox):
    _unlock_read(guard_sandbox)
    _guard.before("/x/threads")  # чтение проходит
    with pytest.raises(_guard.ThreadsBlocked, match="ЗАПИСЬ"):
        _guard.before("/x/threads", write=True)


def test_write_needs_both_keys(guard_sandbox):
    _unlock_write(guard_sandbox)  # только ключ записи, чтение закрыто
    with pytest.raises(_guard.ThreadsBlocked):
        _guard.before("/x/threads", write=True)
    _unlock_read(guard_sandbox)   # теперь оба
    t0 = _guard.before("/x/threads", write=True)
    assert t0 > 0
    assert _guard._write_run_count == 1


def test_write_run_budget_stops(guard_sandbox, monkeypatch):
    _unlock_read(guard_sandbox)
    _unlock_write(guard_sandbox)
    monkeypatch.setattr(_guard, "WRITE_RUN_BUDGET", 1)
    _guard.before("/x/threads", write=True)
    with pytest.raises(_guard.ThreadsBlocked, match="ЗАПИСИ за прогон"):
        _guard.before("/x/threads", write=True)


def test_write_day_budget_counts_only_writes(guard_sandbox, monkeypatch):
    _unlock_read(guard_sandbox)
    _unlock_write(guard_sandbox)
    monkeypatch.setattr(_guard, "WRITE_DAY_BUDGET", 1)
    # чтение НЕ ест бюджет записи
    t0 = _guard.before("/x/threads")
    _guard.after("/x/threads", t0, status=200)
    t0 = _guard.before("/x/threads", write=True)
    _guard.after("/x/threads", t0, status=200, write=True)
    with pytest.raises(_guard.ThreadsBlocked, match="ЗАПИСИ исчерпан"):
        _guard.before("/x/threads", write=True)


def test_journal_marks_writes(guard_sandbox):
    _unlock_read(guard_sandbox)
    _unlock_write(guard_sandbox)
    t0 = _guard.before("/x/threads", write=True)
    _guard.after("/x/threads", t0, status=200, write=True)
    t0 = _guard.before("/x/threads")
    _guard.after("/x/threads", t0, status=200)
    rows = [json.loads(s) for s in
            (guard_sandbox / "threads_api_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r.get("kind") for r in rows] == ["write", None]


def test_unlock_write_requires_reason(guard_sandbox):
    with pytest.raises(ValueError):
        _guard.unlock_write("  ")
    _guard.unlock_write("обкатка вехи E")
    assert "обкатка" in _guard.WRITE_UNLOCK_FILE.read_text(encoding="utf-8")
    _guard.lock_write()
    assert not _guard.WRITE_UNLOCK_FILE.exists()


# --- publish.lint: убийцы охвата не уходят в эфир ----------------------------------------------

@pytest.mark.parametrize("bad, marker", [
    ("Смотри https://example.com тут всё", "ссылка"),
    ("детали на www.site.ru", "ссылка"),
    ("канал t.me/xxx подпишись", "ссылка"),
    ("тренд #bitcoin живёт", "хештег"),
    ("#старт сразу с тега", "хештег"),
    ("", "пустой"),
    ("х" * 501, "длина"),
])
def test_lint_catches_reach_killers(bad, marker):
    problems = publish.lint(bad)
    assert problems and marker in " ".join(problems)


def test_lint_clean_text_passes():
    assert publish.lint("Биток за неделю сделал то, чего ждали год.\nИ это не предел.") == []


# --- publish.create_post ------------------------------------------------------------------------

def test_create_post_lint_fail_never_touches_network(monkeypatch):
    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("сеть тронута при линт-отказе")
    monkeypatch.setattr(publish._api, "post", boom)
    monkeypatch.setattr(publish._api, "get", boom)
    res = publish.create_post("пост со ссылкой https://x.com")
    assert res["ok"] is False and "линт" in res["error"]


def test_dry_run_no_network(guard_sandbox, monkeypatch):
    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("сеть тронута при dry-run")
    monkeypatch.setattr(publish._api, "post", boom)
    monkeypatch.setattr(publish._api, "get", boom)
    res = publish.create_post("чистый текст", dry_run=True)
    assert res["dry_run"] is True
    assert res["ok"] is False and "закрыта" in (res["error"] or "")   # ключей нет → честный отказ
    _unlock_read(guard_sandbox)   # только чтение — запись всё ещё закрыта
    res = publish.create_post("чистый текст", dry_run=True)
    assert res["ok"] is False and "ЗАПИСЬ" in (res["error"] or "")
    _unlock_write(guard_sandbox)  # оба ключа
    res = publish.create_post("чистый текст", dry_run=True)
    assert res["ok"] is True and res["dry_run"] is True


def test_create_post_happy_path_two_writes(monkeypatch):
    calls = []

    def fake_post(path, params, **kw):
        calls.append((path, dict(params)))
        return {"id": "C1"} if path.endswith("/threads") else {"id": "M1"}

    monkeypatch.setattr(publish._api, "post", fake_post)
    monkeypatch.setattr(publish._api, "get", lambda *a, **k: {"permalink": "https://threads.net/p/1"})
    monkeypatch.setattr(publish.auth, "valid_token", lambda: "tok")
    monkeypatch.setattr(publish.auth, "user_id", lambda: "42")
    monkeypatch.setattr(publish, "_meta_limit_reason", lambda is_reply: "")

    res = publish.create_post("нормальный пост")
    assert res == {"ok": True, "id": "M1", "permalink": "https://threads.net/p/1"}
    assert [c[0] for c in calls] == ["42/threads", "42/threads_publish"]
    assert calls[0][1] == {"media_type": "TEXT", "text": "нормальный пост"}
    assert calls[1][1] == {"creation_id": "C1"}


def test_reply_passes_reply_to_id(monkeypatch):
    calls = []

    def fake_post(path, params, **kw):
        calls.append((path, dict(params)))
        return {"id": "C2"} if path.endswith("/threads") else {"id": "M2"}

    monkeypatch.setattr(publish._api, "post", fake_post)
    monkeypatch.setattr(publish._api, "get", lambda *a, **k: {})
    monkeypatch.setattr(publish.auth, "valid_token", lambda: "tok")
    monkeypatch.setattr(publish.auth, "user_id", lambda: "42")
    monkeypatch.setattr(publish, "_meta_limit_reason", lambda is_reply: "")

    res = publish.reply("POST9", "ответ по делу")
    assert res["ok"] is True and res["id"] == "M2"
    assert calls[0][1]["reply_to_id"] == "POST9"


def test_meta_quota_stop_is_fail_closed(monkeypatch):
    monkeypatch.setattr(publish, "publishing_limits",
                        lambda: {"posts_used": 210, "posts_cap": 250, "posts_pct": 84.0,
                                 "replies_used": 0, "replies_cap": 1000, "replies_pct": 0.0})
    reason = publish._meta_limit_reason(is_reply=False)
    assert "84%" in reason
    assert publish._meta_limit_reason(is_reply=True) == ""  # ответы ещё можно


def test_meta_quota_check_failure_blocks_write(monkeypatch):
    def boom():
        raise publish.ThreadsError("сеть упала")
    monkeypatch.setattr(publish, "publishing_limits", boom)
    reason = publish._meta_limit_reason(is_reply=False)
    assert "НЕ пишем" in reason


def test_reply_without_id_refused():
    res = publish.reply("", "текст")
    assert res["ok"] is False


def test_bad_reply_control_refused():
    res = publish.create_post("текст", reply_control="everyone_and_dog")
    assert res["ok"] is False and "reply_control" in res["error"]
