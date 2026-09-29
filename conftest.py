"""Pytest: гарантируем, что корень репозитория в sys.path, чтобы `from core import ...`
работал при запуске `pytest` из любой папки. Сам факт conftest.py в корне делает корень
rootdir'ом; явная вставка — на случай нестандартного режима импорта."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


# ── СТРАЖ: тесты не ходят в Claude API и не пишут владельцу (аудит 29.09.2026) ─────────────────────
# Два теста гейта темы годами звали настоящий API с ключом-заглушкой: 401 глотался «пропускаю», и
# никто этого не видел. Как только llm начал слать владельцу алерт о ключе, pytest отправил ему в
# Telegram «Claude API отказал по ключу». Любой реальный вызов из теста теперь падает громко.
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_network_side_effects(monkeypatch):
    try:
        import anthropic.resources.messages as _m

        def _blocked(*a, **k):
            raise RuntimeError("тест пытался реально вызвать Claude API — подмени llm.reply/клиент")
        monkeypatch.setattr(_m.Messages, "create", _blocked)
    except Exception:
        pass
    try:
        from core import bot_alert
        monkeypatch.setattr(bot_alert, "notify_owner", lambda *a, **k: False)
    except Exception:
        pass
