"""Безопасное чтение JSON из data/memory (AUDIT N-10).

Отсутствует / пустой / битый файл → возвращаем default, НЕ роняем инструмент. Владелец правит
файлы в data/ и memory/ руками — один битый символ не должен ронять аналитику/задачи молча с трейсбеком.
Паттерн уже жил в connectors/threads/auth.py::load_token — выносим в общий хелпер.
"""
from __future__ import annotations

import json
import logging
import os
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


def dump_json(path, data: Any) -> None:
    """Записать JSON АТОМАРНО (через temp + os.replace). Бросает OSError — вызывающий решает, что делать.

    Зачем не write_text напрямую: пара с load_json выше. Прямая запись рвётся на середине (падение,
    выключение света, а на Windows — ещё и чужой процесс, держащий файл), и на диске остаётся ОБРЕЗАННЫЙ
    JSON. Дальше load_json честно вернёт default — и настройка молча превратится в «как будто не
    настраивали». Для настроек расписания это значит «канал тихо вернулся к дефолтному времени».
    os.replace на одном томе атомарен: либо старый файл целиком, либо новый целиком.
    Плюс читатель (другой процесс) никогда не увидит полуфабрикат — только целую версию.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
