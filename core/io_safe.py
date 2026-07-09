"""Безопасное чтение JSON из data/memory (AUDIT N-10).

Отсутствует / пустой / битый файл → возвращаем default, НЕ роняем инструмент. Владелец правит
файлы в data/ и memory/ руками — один битый символ не должен ронять аналитику/задачи молча с трейсбеком.
Паттерн уже жил в connectors/threads/auth.py::load_token — выносим в общий хелпер.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any


def load_json(path, default: Any) -> Any:
    """JSON из path. Нет файла / пусто / битый JSON / ошибка чтения → default (никогда не бросает).
    На СУЩЕСТВУЮЩЕМ, но нечитаемом файле логирует INFO (тихая потеря данных заметна в логе)."""
    p = Path(path)
    try:
        if not p.exists():
            return default
        text = p.read_text(encoding="utf-8").strip()
        if not text:
            return default
        return json.loads(text)
    except (OSError, ValueError) as e:  # ValueError покрывает json.JSONDecodeError и UnicodeDecodeError
        logging.info("[io_safe] %s нечитаем (%s) → default", p, type(e).__name__)
        return default
