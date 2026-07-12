"""Единая настройка логирования (AUDIT N-2, P2-15).

Раньше `logging.basicConfig(level=INFO)` дублировался в трёх точках входа (run_pipeline, agent_runtime,
telegram_publish). basicConfig действует только на ПЕРВЫЙ вызов — остальные молча игнорировались, а формат
менять было негде. Сводим в один идемпотентный `setup()`.

Наблюдаемость (P2-15): каждая строка лога несёт МЕТКУ агента и КОРОТКИЙ id запроса — при сбое сразу видно,
у какого агента и в рамках какого хода это случилось (а не «где-то в общем движке»). Метки живут в
contextvars (работают и в async aiogram, и не текут между запросами), инъекция — через logging-фильтр.
"""
from __future__ import annotations

import contextvars
import itertools
import logging

_configured = False

# «-» = вне запроса/агента (стартовый код, фоновые задачи). Заполняются set_agent()/set_request().
_agent_var: contextvars.ContextVar[str] = contextvars.ContextVar("agent", default="-")
_req_var: contextvars.ContextVar[str] = contextvars.ContextVar("req", default="-")

_req_counter = itertools.count(1)  # монотонный id запроса (без random/uuid — стабильно и дёшево)

# name — модуль-логгер; agent/req — наши метки. Пример: "... INFO core.dedup [creator/42]: ..."
_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(agent)s/%(req)s]: %(message)s"


class _ContextFilter(logging.Filter):
    """Подставляет agent/req из contextvars в каждую запись (иначе %(agent)s в формате упадёт)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.agent = _agent_var.get()
        record.req = _req_var.get()
        return True


def setup(level: int = logging.INFO) -> None:
    """Настроить корневой логгер один раз за процесс (идемпотентно)."""
    global _configured
    if _configured:
        return
    logging.basicConfig(level=level, format=_FORMAT)
    # Фильтр на ХЕНДЛЕР, не на логгер: фильтры логгера НЕ применяются к записям, всплывающим от
    # дочерних логгеров (core.dedup и т.п.) — а хендлер-фильтр видит КАЖДУЮ запись, что он форматирует.
    # Иначе %(agent)s/%(req)s в формате упали бы на логах из под-модулей.
    ctx_filter = _ContextFilter()
    for h in logging.getLogger().handlers:
        h.addFilter(ctx_filter)
    _configured = True


def set_agent(name: str) -> None:
    """Пометить текущий контекст именем агента (зовётся один раз на старте бота/этапа пайплайна)."""
    _agent_var.set(name or "-")


def new_request(tag: str = "") -> str:
    """Начать новый запрос: присвоить короткий id (опц. с меткой, напр. uid). Возвращает id для логов."""
    rid = f"{next(_req_counter)}{('-' + tag) if tag else ''}"
    _req_var.set(rid)
    return rid
