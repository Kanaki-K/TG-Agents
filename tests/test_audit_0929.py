"""Аудит 29.09.2026: молчаливые дыры «ответ есть — эффекта нет»."""
import inspect

import run_pipeline as rp
from core import creator_bot, verify


# ── Сбой фактчека ≠ «чисто» ─────────────────────────────────────────────────────────────────────

def test_failed_verdict_is_recognised():
    assert verify.failed("(фактчек не удался: 529 overloaded)")
    assert verify.failed("(пусто)") and verify.failed("")
    assert not verify.failed("ИТОГ: 5✅ / 0⚠️ / 0❓\nСТАТУС: ЧИСТО")


def test_verify_post_records_failure(monkeypatch):
    verify.reset_failures()
    def boom(*a, **k):
        raise RuntimeError("529 overloaded")
    monkeypatch.setattr(verify.llm, "reply", boom)
    v = verify.verify_post("пост", "", api_key="k", web=True)
    assert verify.failed(v) and verify.FAILURES and "529" in verify.FAILURES[0]


def test_schedule_does_not_say_clean_on_failure(monkeypatch):
    monkeypatch.setattr(creator_bot.runmode, "get", lambda: {"mode": "main"})
    monkeypatch.setattr(creator_bot, "_run_2fa", lambda: ("(фактчек не удался: 401)", False))
    called = []
    monkeypatch.setattr(creator_bot.creator_tools, "dispatch", lambda *a, **k: called.append(a) or "ok")
    out = creator_bot._schedule()
    assert "НЕ отработал" in out and not called, "при сбое 2FA пост ушёл в отложку с «чисто»"


def test_pipeline_panel_overrides_clean_on_failure():
    src = inspect.getsource(rp.run_cycle)
    assert "verify.reset_failures()" in src and "if verify.FAILURES:" in src


# ── Гигиена Threads не висит на выключенном автопилоте ─────────────────────────────────────────

def test_manual_run_does_threads_hygiene():
    assert "_threads_daily_hygiene()" in inspect.getsource(rp.main)


def test_token_expiry_alert(monkeypatch):
    import time
    import run_autopilot as ra
    from connectors.threads import auth
    sent = []
    monkeypatch.setattr(auth, "load_token", lambda: {"expires_at": time.time() + 3 * 86400})
    monkeypatch.setattr(ra.schedule, "warned_today", lambda k: False)
    monkeypatch.setattr(ra.schedule, "mark_warned", lambda k: None)
    monkeypatch.setattr(ra.bot_alert, "notify_owner", lambda t: sent.append(t))
    ra._threads_token_expiry_alert()
    assert sent and "истекает через 3" in sent[0]
    sent.clear()
    monkeypatch.setattr(auth, "load_token", lambda: {"expires_at": time.time() + 40 * 86400})
    ra._threads_token_expiry_alert()
    assert not sent


# ── Ключ/баланс — алерт владельцу, один раз ────────────────────────────────────────────────────

def test_account_problem_alerts_once(monkeypatch):
    from core import bot_alert, llm
    sent = []
    monkeypatch.setattr(bot_alert, "notify_owner", lambda t, *a, **k: sent.append(t) or True)
    monkeypatch.setattr(llm, "_ACCOUNT_ALERTED", False)
    llm._alert_if_account_problem(RuntimeError("Your credit balance is too low to access the Anthropic API"))
    llm._alert_if_account_problem(RuntimeError("Your credit balance is too low"))
    assert len(sent) == 1 and "балансу" in sent[0]


def test_overload_is_not_an_account_problem(monkeypatch):
    from core import bot_alert, llm
    sent = []
    monkeypatch.setattr(bot_alert, "notify_owner", lambda t, *a, **k: sent.append(t) or True)
    monkeypatch.setattr(llm, "_ACCOUNT_ALERTED", False)
    llm._alert_if_account_problem(RuntimeError("529 overloaded_error"))
    assert not sent


def test_cover_log_survives_a_broken_line(tmp_path, monkeypatch):
    from core import scope_cover_log as scl
    f = tmp_path / "log.jsonl"
    f.write_text('{"label": "фасад SEC"}\n{битая\n{"label": "вывеска BitMEX"}\n', encoding="utf-8")
    monkeypatch.setattr(scl, "LOG", f)
    assert scl.recent() == ["вывеска BitMEX", "фасад SEC"]


# ── Публикатор: повтор другим способом только на явный отказ Telegram ─────────────────────────────

def test_publisher_retries_only_on_telegram_rejection():
    """Сетевой таймаут после приёма сервером + повтор = второй пост в отложке. Ловим только 400."""
    from connectors.telegram_publish import publish as pub
    src = inspect.getsource(pub._publish_async) if hasattr(pub, "_publish_async") else inspect.getsource(pub)
    send_part = src.split("async def _msg", 1)[1].split("async def _scheduled_async", 1)[0]
    assert "except Exception" not in send_part, "повтор отправки на ЛЮБУЮ ошибку — путь к дублю"
    assert "except BadRequestError" in send_part


def test_scheduled_read_failure_is_not_empty_list():
    from connectors.telegram_publish import publish as pub
    src = inspect.getsource(pub._scheduled_async)
    assert "return []" in src and src.count("return []") == 1, "сбой чтения снова маскируется под «свободно»"


def test_write_text_atomic_replaces_whole_file(tmp_path):
    from core import io_safe
    f = tmp_path / "lessons.md"
    f.write_text("старое", encoding="utf-8")
    io_safe.write_text_atomic(f, "новое целиком\n")
    assert f.read_text(encoding="utf-8") == "новое целиком\n"
    assert not (tmp_path / "lessons.md.tmp").exists()
