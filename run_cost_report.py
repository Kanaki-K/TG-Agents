"""Отчёт по расходам Claude из data/cost_log.jsonl — ПО ПРОГОНАМ (итерациям) и по дням.

Прогон (итерация) = серия вызовов API подряд с паузой между ними ≤ RUN_GAP_MIN минут;
большая пауза = новый прогон. По каждому прогону видно: дата, время, агент (кто запустил —
creator/scout/verify/…), модель, цена, токены и кэш-хит.

Каждый вызов API пишется в лог (core/cost.py → _append_ledger): ts, who, model,
токены (вход/кэш-чтение/кэш-запись/выход), цена. Этот скрипт сворачивает лог в читаемый вид.

Запуск:
    python run_cost_report.py        # все прогоны + дни
    python run_cost_report.py 7      # прогоны/дни за последние 7 дней
    python run_cost_report.py last   # только последний прогон
"""
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

LEDGER = Path(__file__).resolve().parent / "data" / "cost_log.jsonl"
RUN_GAP_MIN = 20   # пауза > 20 мин между вызовами = новый прогон


def _blank() -> dict:
    return {"cost": 0.0, "in": 0, "cache_r": 0, "cache_w": 0, "out": 0, "calls": 0}


def _acc(a: dict, r: dict) -> None:
    a["cost"] += r.get("cost", 0.0)
    a["calls"] += 1
    for k in ("in", "cache_r", "cache_w", "out"):
        a[k] += r.get(k, 0)


def _hit(a: dict) -> float:
    cached, full = a["cache_r"], a["in"] + a["cache_w"]
    return (100 * cached / (cached + full)) if (cached + full) else 0


def _line(label: str, a: dict) -> str:
    return (f"    {label:<22} ${a['cost']:.3f} · {a['calls']} выз · вход {a['in']} · "
            f"кэш-чт {a['cache_r']} · кэш-зап {a['cache_w']} · выход {a['out']} · кэш-хит {_hit(a):.0f}%")


def _runs(rows: list) -> list:
    """Сгруппировать вызовы в прогоны: пауза между соседними > RUN_GAP_MIN мин = новый прогон."""
    runs: list = []
    for r in rows:
        ts = datetime.fromisoformat(r["ts"])
        if runs and (ts - runs[-1]["end"]).total_seconds() <= RUN_GAP_MIN * 60:
            runs[-1]["rows"].append(r)
            runs[-1]["end"] = ts
        else:
            runs.append({"start": ts, "end": ts, "rows": [r]})
    return runs


def main() -> None:
    if not LEDGER.exists():
        print("Лога расходов пока нет (data/cost_log.jsonl). Сделай прогон/ход бота — он начнёт писаться.")
        return
    rows = [json.loads(ln) for ln in LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not rows:
        print("Лог пуст.")
        return
    rows.sort(key=lambda r: r["ts"])

    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    runs = _runs(rows)
    if arg == "last":
        runs = runs[-1:]
    elif arg.isdigit():
        keep = sorted({r["ts"][:10] for r in rows})[-int(arg):]
        runs = [run for run in runs if run["start"].date().isoformat() in keep]

    sel = [r for run in runs for r in run["rows"]]   # выбранные вызовы (для дневных итогов)

    # 1) ПО ПРОГОНАМ (итерациям)
    print(f"=== ПО ПРОГОНАМ (прогон = вызовы с паузой ≤ {RUN_GAP_MIN} мин) ===")
    for run in runs:
        by_wm: dict = defaultdict(_blank)   # (who, model) -> агрегат
        tot = _blank()
        for r in run["rows"]:
            _acc(by_wm[(r.get("who", "?"), r.get("model", "?"))], r)
            _acc(tot, r)
        d = run["start"].strftime("%Y-%m-%d")
        span = f"{run['start'].strftime('%H:%M')}–{run['end'].strftime('%H:%M')}"
        print(f"\n• {d} {span} — ${tot['cost']:.3f} ({tot['calls']} выз)")
        for (who, model), a in sorted(by_wm.items(), key=lambda x: -x[1]["cost"]):
            print(_line(f"{who}/{model.replace('claude-', '')}", a))

    # 2) ПО ДНЯМ (итог)
    by_day: dict = defaultdict(_blank)
    for r in sel:
        _acc(by_day[r["ts"][:10]], r)
    print("\n=== ПО ДНЯМ ===")
    grand = 0.0
    for day in sorted(by_day):
        grand += by_day[day]["cost"]
        print(_line(day, by_day[day]))
    print(f"\nИТОГО: ${grand:.3f}  ·  прогонов: {len(runs)}")
    print("(кэш-хит % = доля входа, прочитанная из кэша за 0.1×; чем выше — тем больше экономия)")


if __name__ == "__main__":
    main()
