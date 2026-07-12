"""Полное обновление аналитики Threads одной командой (аналог refresh.py для Telegram).

Делает по очереди: сбор постов+метрик → обогащение тем (заголовок/тема/суть) → пересборка таблицы.
collect МЕРЖИТ: добавляет свежие посты и обновляет метрики, старые не теряет — так же «проверить все +
дозаполнить новыми». enrich по умолчанию трогает только НОВЫЕ посты (дёшево).

    python refresh_threads.py          # обычное обновление
    python refresh_threads.py --all    # пере-обогатить темы по ВСЕМ постам (дороже)

Нужен живой Threads-токен (data/threads_token.json — авто-обновляется из seed в .env).
После — анализ (два объектива, качество+охват):  python -m connectors.threads.report
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = "connectors.threads"


def run(module: str, *args: str) -> bool:
    print(f"\n=== {module} {' '.join(args)} ===")
    r = subprocess.run([sys.executable, "-m", f"{PKG}.{module}", *args], cwd=ROOT)
    if r.returncode != 0:
        print(f"!! шаг {module} завершился с ошибкой (код {r.returncode})")
    return r.returncode == 0


def main() -> int:
    full = "--all" in sys.argv
    results = {
        "collect": run("collect"),                                    # посты + метрики + сводка аккаунта
        "enrich_topics": run("enrich_topics", *(("--all",) if full else ())),  # темы (только новые / все)
        "build_table": run("build_table"),                            # data/threads_analytics.xlsx
    }
    failed = [name for name, ok in results.items() if not ok]
    if failed:
        # НЕ маскируем сбой нулевым кодом (как в refresh.py): collect критичен, build_table — только Excel.
        print(f"\n⚠️ Готово С ОШИБКАМИ: упали шаги — {', '.join(failed)}.")
        return 1
    print("\nГотово: data/threads_analytics.xlsx обновлён.")
    print("Анализ (качество + охват): python -m connectors.threads.report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
