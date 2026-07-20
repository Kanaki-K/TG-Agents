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


def resolve(boevoy_model: str, ceiling: str | None = None) -> str:
    """Какую модель реально использовать СЕЙЧАС.

    Приоритет: env MODEL_OVERRIDE (жёсткий — для скриптов/CI) → тест-режим (/test) →
    боевая модель из config.yaml. Вызывается на каждый ход — переключение живое.

    ceiling — потолок ТИРА для механических ролей (verify/scope/dedup/…): override и тест
    могут только УДЕШЕВИТЬ такую роль, не удорожить. Урок аудита расходов 15.07: MODEL_OVERRIDE,
    выставленный ради флагмана, молча утёк в scope+verify — 36 вызовов на Opus, $4.32 вместо
    $2.59, качеству это не дало ничего. Флагман ceiling НЕ передаёт — его тир решает владелец.
    """
    env = (os.getenv("MODEL_OVERRIDE") or "").strip()
    st = get()
    resolved = env or (st["model"] if st["mode"] == "test" else boevoy_model)
    if ceiling and resolved != ceiling:
        from core import cost  # локально: не тащить cost при импорте модуля
        price = lambda m: cost.RATES.get(m, cost._DEFAULT)[0]  # noqa: E731 — вход $/1M = ранг тира
        if price(resolved) > price(ceiling):
            logging.getLogger(__name__).warning(
                "runmode: %s дороже потолка %s для этой роли — режу до потолка", resolved, ceiling)
            return ceiling
    return resolved


def banner(boevoy_model: str) -> str:
    """Короткая строка статуса для чата/лога — чтобы режим был ВСЕГДА виден."""
    st = get()
    if st["mode"] == "test":
        return (f"🧪 ТЕСТ-режим (модель {resolve(boevoy_model)}, дёшево — НЕ для прода). "
                f"Боевой: /main")
    return f"🚀 БОЕВОЙ режим (модель {resolve(boevoy_model)}). Дешёвый тест: /test"
