"""Полное обновление аналитики канала одной командой.

Делает по очереди: сбор постов → сводная статистика → снапшот метрик →
обогащение новых постов (заголовок/тема) → пересборка таблицы Excel.

    python refresh.py          # обычное обновление (снапшот только свежих постов)
    python refresh.py --all    # «обновить»: свежий снимок по ВСЕМ постам

Вешается на расписание (раз в 24 ч) — см. README/инструкцию.
Нужен вход (data/kanaki.session уже создан) и ключи в .env.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = "connectors.telegram_export"


def run(module: str, *args: str) -> bool:
    print(f"\n=== {module} {' '.join(args)} ===")
    r = subprocess.run([sys.executable, "-m", f"{PKG}.{module}", *args], cwd=ROOT)
    if r.returncode != 0:
        print(f"!! шаг {module} завершился с ошибкой (код {r.returncode})")
    return r.returncode == 0


def main() -> None:
    full = "--all" in sys.argv
    run("collect", "collect")
    run("collect_stats")
    run("snapshot", *(("--all",) if full else ()))
    run("enrich_topics")              # обогащает только новые посты
    run("build_table")
    print("\nГотово: data/posts_analytics.xlsx обновлён.")


if __name__ == "__main__":
    main()
