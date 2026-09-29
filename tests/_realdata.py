"""Замеры на ЖИВЫХ данных канала (data/ в .gitignore — на GitHub-раннере их нет).

Аудит 29.09.2026: 8 тестов-«замков» читали data/*.json напрямую и на CI падали FileNotFoundError, а
красный крест CI никто не смотрел. Локально замер работает как раньше; без данных тест честно
пропускается с причиной, а не роняет весь прогон."""
import json

import pytest

from core import config


def load_real(name: str):
    path = config.ROOT / "data" / name
    if not path.exists():
        pytest.skip(f"нет живых данных data/{name} (CI-раннер) — замер только локально")
    return json.load(open(path, encoding="utf-8"))
