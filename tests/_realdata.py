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


# Приватный репо памяти (memory/ — свой .git, в публичный репо не входит, на GitHub-раннере его нет).
# Тесты, которые проверяют живые своды/уроки/мануалы, без него пропускаются с причиной. Локально и в
# контейнере память на диске — они работают как раньше. Аудит 29.09: из-за них CI был красным с момента
# выноса памяти в отдельный репо, а не только из-за data/.
needs_memory = pytest.mark.skipif(not (config.ROOT / "memory" / "scope_manual.md").exists(),
                                  reason="приватный репо памяти не подключён (CI-раннер)")
