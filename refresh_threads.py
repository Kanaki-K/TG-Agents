"""Полное обновление аналитики Threads одной командой (аналог refresh.py для Telegram).

Делает по очереди: сбор постов+метрик → обогащение тем (заголовок/тема/суть) → пересборка таблицы.
collect МЕРЖИТ: добавляет свежие посты и обновляет метрики, старые не теряет — так же «проверить все +
дозаполнить новыми». enrich по умолчанию трогает только НОВЫЕ посты (дёшево).

    python refresh_threads.py          # обновление в ЩАДЯЩЕМ режиме (по умолчанию)
    python refresh_threads.py --all    # пере-обогатить темы по ВСЕМ постам (дороже)
    python refresh_threads.py --normal # штатный темп защиты (быстрее, но заметнее)

ЩАДЯЩИЙ РЕЖИМ ПО УМОЛЧАНИЮ (решение владельца 09.09.2026: «чем безопаснее, тем лучше — Мета
нервная»). Он не отменяет предохранители `_guard`, а ужимает их сверху: паузы между запросами
вдвое длиннее, бюджет прогона ниже, а тормоз по КВОТЕ МЕТА срабатывает уже на 60% вместо 80%.
Цена — сбор идёт дольше; выигрыш — расход остаётся долей процента от лимита аккаунта, и ни один
запрос не идёт очередью. Нужен обычный темп (много данных, ждать некогда) — `--normal`.

Нужен живой Threads-токен (data/threads_token.json — авто-обновляется из seed в .env).
После — анализ (два объектива, качество+охват):  python -m connectors.threads.report
"""
from __future__ import annotations

import subprocess
import sys
from os import environ
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = "connectors.threads"


# Щадящий режим = те же ручки защиты, затянутые сильнее. Шаги сбора — отдельные процессы, поэтому
# передаём окружением: _guard читает эти же имена, второго набора настроек не заводим.
GENTLE = {
    "THREADS_GAP_MIN": "3.0",        # было 1.5 — пауза между запросами вдвое длиннее
    "THREADS_GAP_MAX": "8.0",        # было 4.0
    "THREADS_RUN_BUDGET": "140",     # было 200 — потолок против рунавея ниже
    "THREADS_USAGE_WARN": "35",      # было 50 — предупреждаем раньше
    "THREADS_USAGE_STOP": "60",      # было 80 — тормозим ЗАДОЛГО до лимита Меты
}


def _child_env(gentle: bool) -> dict:
    """Окружение шага сбора. Заданное владельцем НЕ перетираем — его настройка главнее нашей."""
    out = dict(environ)
    if gentle:
        for k, v in GENTLE.items():
            out.setdefault(k, v)
    return out


def run(module: str, *args: str, gentle: bool = True) -> bool:
    print(f"\n=== {module} {' '.join(args)} ===")
    r = subprocess.run([sys.executable, "-m", f"{PKG}.{module}", *args], cwd=ROOT,
                       env=_child_env(gentle))
    if r.returncode != 0:
        print(f"!! шаг {module} завершился с ошибкой (код {r.returncode})")
    return r.returncode == 0


def main() -> int:
    full = "--all" in sys.argv
    gentle = "--normal" not in sys.argv
    print("🐢 Щадящий режим: паузы 3-8с, бюджет прогона 140 запросов, стоп по квоте Меты на 60%."
          if gentle else "⚡ Штатный темп защиты (--normal): паузы 1.5-4с, стоп по квоте на 80%.")
    results = {
        "collect": run("collect", gentle=gentle),                     # посты + метрики + сводка аккаунта
        # обогащение тем — вызовы к Anthropic, не к Мете: щадящий режим на них не влияет
        "enrich_topics": run("enrich_topics", *(("--all",) if full else ())),
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
