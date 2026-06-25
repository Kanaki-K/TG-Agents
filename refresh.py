"""Полное обновление аналитики канала одной командой.

Делает по очереди: сбор постов → сводная статистика → снапшот метрик →
обогащение новых постов (заголовок/тема) → пересборка таблицы Excel.

    python refresh.py          # обычное обновление (снапшот только свежих постов)
    python refresh.py --all    # «обновить»: свежий снимок по ВСЕМ постам

Вешается на расписание (раз в 24 ч) — см. README/инструкцию.
Нужен вход (data/evgeniyp.session уже создан) и ключи в .env.
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


def main() -> int:
    full = "--all" in sys.argv
    results = {
        "collect": run("collect", "collect"),
        "collect_stats": run("collect_stats"),
        "snapshot": run("snapshot", *(("--all",) if full else ())),
        "enrich_topics": run("enrich_topics"),   # обогащает только новые посты
        "build_table": run("build_table"),
    }
    failed = [name for name, ok in results.items() if not ok]
    if failed:
        # НЕ маскируем сбой нулевым кодом: иначе вызывающий (refresh_metrics) рапортует «всё ок»,
        # хотя шаг упал. collect/enrich критичны для анти-повтора, build_table — только Excel-артефакт.
        print(f"\n⚠️ Готово С ОШИБКАМИ: упали шаги — {', '.join(failed)}.")
        return 1
    print("\nГотово: data/posts_analytics.xlsx обновлён.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
