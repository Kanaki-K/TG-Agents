"""Учёт расхода токенов и стоимости вызовов Claude (по моделям).

llm.reply на каждый вызов API зовёт record() — логирует стоимость в консоль ВСЕГДА, а копит
для итога — только между reset() и summary() (это включает run_pipeline, чтобы посчитать
полную цену «Скаут→пост в отложке»). Боты reset() не зовут — у них просто строка в лог на ход.

Цены $/1M токенов (вход, выход). Кэш: запись ~1.25× входной цены, чтение ~0.1× входной цены.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

RATES = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
_DEFAULT = (5.0, 25.0)  # незнакомая модель — считаем по Opus-тарифу (консервативно)

_log: list[tuple[str, dict]] = []
_tracking = False

# Постоянный лог расходов: одна JSON-строка на вызов API (дата/время, кто, токены, кэш, цена).
# Живёт в data/ (вне git). Позволяет сравнивать дни и видеть кэш-эффективность — см. run_cost_report.py.
_LEDGER = Path(__file__).resolve().parents[1] / "data" / "cost_log.jsonl"
_context = "?"  # кто сейчас расходует — ставит set_context перед действием (scout/creator/verify/…)


def set_context(label: str) -> None:
    """Пометить текущее действие для записи в лог расходов (напр. 'scout', 'creator', 'verify')."""
    global _context
    _context = label or "?"


def _append_ledger(model: str, u: dict, c: float) -> None:
    """Дописать строку в постоянный лог: дата/время + кто + токены (вкл. кэш) + цена."""
    try:
        _LEDGER.parent.mkdir(exist_ok=True)
        with _LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(timespec="seconds"), "who": _context, "model": model,
                "in": u["in"], "cache_w": u["cache_w"], "cache_r": u["cache_r"], "out": u["out"],
                "cost": round(c, 6),
            }, ensure_ascii=False) + "\n")
    except Exception:
        logging.exception("[cost] не смог записать в %s", _LEDGER)


def reset() -> None:
    """Начать новый замер (run_pipeline зовёт перед прогоном)."""
    global _tracking
    _log.clear()
    _tracking = True


def _usage_dict(usage) -> dict:
    g = lambda n: int(getattr(usage, n, 0) or 0)  # noqa: E731
    return {"in": g("input_tokens"), "out": g("output_tokens"),
            "cache_w": g("cache_creation_input_tokens"), "cache_r": g("cache_read_input_tokens")}


def _cost(model: str, u: dict) -> float:
    inp, out = RATES.get(model, _DEFAULT)
    return (u["in"] * inp + u["cache_w"] * inp * 1.25 + u["cache_r"] * inp * 0.1
            + u["out"] * out) / 1_000_000


def record(model, usage) -> None:
    """Записать расход одного вызова API: всегда лог в консоль, в итог — если идёт замер."""
    try:
        u = _usage_dict(usage)
    except Exception:
        logging.exception("[cost] не смог прочитать usage")
        return
    c = _cost(model, u)
    tok = u["in"] + u["out"] + u["cache_w"] + u["cache_r"]
    logging.info("[cost] %s: %d ток (вход %d, кэш-зап %d, кэш-чт %d, выход %d) → $%.4f",
                 model, tok, u["in"], u["cache_w"], u["cache_r"], u["out"], c)
    _append_ledger(model, u, c)  # постоянная запись (дата/время + кто + кэш + цена)
    if _tracking:
        _log.append((model, u))


def total() -> float:
    return sum(_cost(m, u) for m, u in _log)


def summary() -> str:
    """Итог замера: по моделям + общая цена в $ (для run_pipeline)."""
    global _tracking
    _tracking = False
    by: dict[str, dict] = {}
    for m, u in _log:
        a = by.setdefault(m, {"in": 0, "out": 0, "cache_w": 0, "cache_r": 0, "cost": 0.0, "calls": 0})
        for k in ("in", "out", "cache_w", "cache_r"):
            a[k] += u[k]
        a["cost"] += _cost(m, u)
        a["calls"] += 1
    lines = ["=== Расход Claude за прогон ==="]
    for m, a in by.items():
        tok = a["in"] + a["out"] + a["cache_w"] + a["cache_r"]
        lines.append(f"  {m}: {a['calls']} выз · {tok} ток "
                     f"(вход {a['in']}, кэш-зап {a['cache_w']}, кэш-чт {a['cache_r']}, выход {a['out']}) "
                     f"→ ${a['cost']:.3f}")
    lines.append(f"ИТОГО Скаут→пост: ${total():.3f}")
    return "\n".join(lines)
