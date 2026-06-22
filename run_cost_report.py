"""Отчёт по расходам Claude из data/cost_log.jsonl — по дням и по агентам, с кэш-эффективностью.

Каждый вызов API пишется в лог (core/cost.py → _append_ledger): дата/время, кто (scout/creator/
verify/…), модель, токены (вход/кэш-чтение/кэш-запись/выход), цена. Этот скрипт сворачивает лог
в читаемый вид, чтобы сравнивать дни и видеть, реально ли работает кэш (кэш-хит %).

Запуск:
    python run_cost_report.py        # все дни
    python run_cost_report.py 7      # последние 7 дней
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

LEDGER = Path(__file__).resolve().parent / "data" / "cost_log.jsonl"


def _blank() -> dict:
    return {"cost": 0.0, "in": 0, "cache_r": 0, "cache_w": 0, "out": 0, "calls": 0}


def main() -> None:
    if not LEDGER.exists():
        print("Лога расходов пока нет (data/cost_log.jsonl). Сделай прогон/ход бота — он начнёт писаться.")
        return
    rows = [json.loads(ln) for ln in LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()]
    by_day: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(_blank))
    for r in rows:
        a = by_day[r["ts"][:10]][r.get("who", "?")]
        a["cost"] += r.get("cost", 0.0)
        a["calls"] += 1
        for k in ("in", "cache_r", "cache_w", "out"):
            a[k] += r.get(k, 0)

    days = sorted(by_day)
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else len(days)
    grand = 0.0
    for day in days[-n:]:
        day_total = sum(a["cost"] for a in by_day[day].values())
        grand += day_total
        print(f"\n=== {day} — ${day_total:.3f} ===")
        for who, a in sorted(by_day[day].items(), key=lambda x: -x[1]["cost"]):
            cached, full = a["cache_r"], a["in"] + a["cache_w"]
            hit = (100 * cached / (cached + full)) if (cached + full) else 0
            print(f"  {who:<13} ${a['cost']:.3f}  · {a['calls']} выз · вход {a['in']} · "
                  f"кэш-чт {a['cache_r']} · кэш-зап {a['cache_w']} · выход {a['out']} · кэш-хит {hit:.0f}%")
    print(f"\nИТОГО за {min(n, len(days))} дн.: ${grand:.3f}")
    print("(кэш-хит % = доля входа, прочитанная из кэша за 0.1×; чем выше — тем больше экономия)")


if __name__ == "__main__":
    main()
