"""Режим работы завода: 'main' (боевой, модели из config.yaml) или 'test' (дёшево).

Переключается командами /test и /main в ЛЮБОМ боте — состояние в data/run_mode.txt,
поэтому действует на ВСЕХ агентов сразу и переживает перезапуск. Цель — «дёшево
тестируй, дорого публикуй» без правки конфигов руками (docs/PLAN.md «Дисциплина
стоимости», урок на ~$50). Модель резолвится НА КАЖДЫЙ ход, так что переключение
живое — работающего бота перезапускать не нужно.
"""
from __future__ import annotations

import logging
import os

from core import config

_FILE = config.ROOT / "data" / "run_mode.txt"

# Псевдонимы дешёвых моделей для /test. По умолчанию — самая дешёвая (Haiku):
# хватает на тесты механики/структуры/промпта; качество письма проверяем уже в /main.
TEST_MODELS = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
}
_DEFAULT_TEST = "claude-haiku-4-5"


def get() -> dict:
    """Текущий режим: {'mode': 'main'|'test', 'model': <тест-модель|None>}.
    Файла нет → боевой режим (least surprise: бот по умолчанию пишет боевым качеством)."""
    try:
        raw = (_FILE.read_text(encoding="utf-8") or "").strip()
    except Exception:
        raw = ""
    if raw.startswith("test"):
        parts = raw.split(maxsplit=1)              # формат: 'test' или 'test <модель>'
        model = parts[1].strip() if len(parts) > 1 and parts[1].strip() else _DEFAULT_TEST
        return {"mode": "test", "model": model}
    return {"mode": "main", "model": None}


def set_test(alias: str = "") -> str:
    """Включить тест-режим. alias: 'haiku'/'sonnet' или полный id модели; пусто = haiku.
    Возвращает выбранную тест-модель."""
    a = (alias or "").strip().lower()
    model = TEST_MODELS.get(a) or (a if a.startswith("claude-") else _DEFAULT_TEST)
    _write(f"test {model}")
    return model


def set_main() -> None:
    """Вернуть боевой режим — модели берутся из config.yaml каждого агента."""
    _write("main")


def _write(value: str) -> None:
    try:
        _FILE.parent.mkdir(exist_ok=True)
        _FILE.write_text(value, encoding="utf-8")
    except Exception:
        logging.exception("Не смог записать режим в %s", _FILE)


def resolve(boevoy_model: str) -> str:
    """Какую модель реально использовать СЕЙЧАС.

    Приоритет: env MODEL_OVERRIDE (жёсткий — для скриптов/CI) → тест-режим (/test) →
    боевая модель из config.yaml. Вызывается на каждый ход — переключение живое.
    """
    env = (os.getenv("MODEL_OVERRIDE") or "").strip()
    if env:
        return env
    st = get()
    return st["model"] if st["mode"] == "test" else boevoy_model


def banner(boevoy_model: str) -> str:
    """Короткая строка статуса для чата/лога — чтобы режим был ВСЕГДА виден."""
    st = get()
    if st["mode"] == "test":
        return (f"🧪 ТЕСТ-режим (модель {resolve(boevoy_model)}, дёшево — НЕ для прода). "
                f"Боевой: /main")
    return f"🚀 БОЕВОЙ режим (модель {resolve(boevoy_model)}). Дешёвый тест: /test"
