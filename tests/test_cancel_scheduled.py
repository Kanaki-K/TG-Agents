"""Снятие отложки (publish.cancel_scheduled + tools/cancel_scheduled.py) — контракт предохранителей.

ЗАЧЕМ. Завод умел ставить пост в отложку, но не умел снимать: 12.09.2026 в отложку уехал пост,
который владелец забраковал целиком, и отменять свою же ошибку приходилось руками в клиенте. Удаление
необратимо, поэтому тесты держат именно предохранители: сухой прогон по умолчанию, показ цели до
удаления, правильный API (отложенное, а не опубликованное) и то, что пайплайн эту функцию не зовёт.
Запуск: python -m pytest tests/test_cancel_scheduled.py"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_pipeline_never_cancels_by_itself():
    """Снимать чужое решение — дело человека. Позовём когда-нибудь из автопилота — тест упадёт."""
    for f in ("run_pipeline.py", "run_autopilot.py", "core/creator_tools.py", "core/scope_writer.py"):
        assert "cancel_scheduled" not in (ROOT / f).read_text(encoding="utf-8"), f


def test_cli_is_dry_run_without_yes():
    src = (ROOT / "tools" / "cancel_scheduled.py").read_text(encoding="utf-8")
    assert "--yes" in src and "СУХОЙ ПРОГОН" in src
    assert src.index("Цель:") < src.index("publish.cancel_scheduled")   # цель видна ДО удаления


def test_connector_deletes_scheduled_not_published():
    """Удаляем именно ОТЛОЖЕННОЕ (DeleteScheduledMessages). Обычный delete_messages снёс бы
    опубликованный пост канала — не та операция и не тот риск."""
    src = (ROOT / "connectors" / "telegram_publish" / "publish.py").read_text(encoding="utf-8")
    body = src[src.index("async def _cancel_scheduled_async"):src.index("def cancel_scheduled")]
    assert "DeleteScheduledMessagesRequest" in body
    assert "delete_messages" not in body
    assert "gone = all(" in body          # результат перечитываем, а не верим на слово


def test_target_is_the_newest_scheduled():
    src = (ROOT / "connectors" / "telegram_publish" / "publish.py").read_text(encoding="utf-8")
    body = src[src.index("async def _cancel_scheduled_async"):src.index("def cancel_scheduled")]
    assert re.search(r"max\(msgs, key=lambda m: m\.id\)", body)   # «то, что только что поставил»
