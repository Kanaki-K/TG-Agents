"""Единая настройка логирования (AUDIT N-2).

Раньше `logging.basicConfig(level=INFO)` дублировался в трёх точках входа (run_pipeline, agent_runtime,
telegram_publish). basicConfig действует только на ПЕРВЫЙ вызов — остальные молча игнорировались, а формат
менять было негде. Сводим в один идемпотентный `setup()`: любая точка входа зовёт его, повторные вызовы
безвредны. Будущая наблюдаемость (request_id/agent_name в формате — P2-15) правится здесь одним местом.
"""
from __future__ import annotations

import logging

_configured = False

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup(level: int = logging.INFO) -> None:
    """Настроить корневой логгер один раз за процесс (идемпотентно)."""
    global _configured
    if _configured:
        return
    logging.basicConfig(level=level, format=_FORMAT)
    _configured = True
