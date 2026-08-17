"""Учёт расхода токенов и стоимости вызовов Claude (по моделям).

llm.reply на каждый вызов API зовёт record() — логирует стоимость в консоль ВСЕГДА, а копит
для итога — только между reset() и summary() (это включает run_pipeline, чтобы посчитать
полную цену «Скаут→пост в отложке»). Боты reset() не зовут — у них просто строка в лог на ход.

Цены $/1M токенов (вход, выход). Кэш: запись 5m = 1.25×, запись 1h = 2× (!), чтение = 0.1×
входной цены. web_search — $10 за 1000 поисков ПОВЕРХ токенов.

⚠ Урок аудита расходов 15.07: считалка брала ВСЕ кэш-записи по 1.25×, хотя llm.py ставит
системному блоку ttl=1h (биллится 2×), а web_search не считала вовсе — лог занижал реальный
счёт Anthropic на ~$11-19/мес. Теперь 1h-записи считаются по 2× (разбивка из usage.cache_creation;
если API её не дал — консервативно считаем всё по 2×: завысить безопаснее, чем занизить),
поиски — по $0.01. После первого инвойса сверить: python run_cost_report.py vs счёт.
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


def get_context() -> str:
    """Текущая метка расхода — чтобы вложенный вызов (напр. воронка) мог ВЕРНУТЬ её после себя
    и не утащить расход вызывающего под свою метку (аудит Скаута 20.07)."""
    return _context


def _append_ledger(model: str, u: dict, c: float) -> None:
    """Дописать строку в постоянный лог: дата/время + кто + токены (вкл. кэш) + цена."""
    try:
        _LEDGER.parent.mkdir(exist_ok=True)
        with _LEDGER.open("a", encoding="utf-8") as f:
            row = {
                "ts": datetime.now().isoformat(timespec="seconds"), "who": _context, "model": model,
                "in": u["in"], "cache_w": u["cache_w"], "cache_r": u["cache_r"], "out": u["out"],
                "cost": round(c, 6),
            }
            # новые поля пишем только ненулевыми — старые строки лога остаются сравнимыми
            if u.get("cache_w_1h"):
                row["cache_w_1h"] = u["cache_w_1h"]
            if u.get("search"):
                row["search"] = u["search"]
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        logging.exception("[cost] не смог записать в %s", _LEDGER)


def reset() -> None:
    """Начать новый замер (run_pipeline зовёт перед прогоном)."""
    global _tracking
    _log.clear()
    _tracking = True


SEARCH_RATE = 0.01  # $ за один web_search (тариф Anthropic: $10/1000 поисков)


def _usage_dict(usage) -> dict:
    g = lambda n: int(getattr(usage, n, 0) or 0)  # noqa: E731
    cache_w = g("cache_creation_input_tokens")
    # Разбивка записей кэша по TTL: 1h биллится 2×, 5m — 1.25×. Если API разбивку не дал —
    # консервативно считаем всё по 2× (завысить копейки безопаснее, чем снова занижать счёт).
    # ⚠️ С 17.08 боевой прогон пишет системный блок меткой 5m (llm._system_cache_control), 1h
    # остался только в /test — то есть этот запасной путь стал ХУДШИМ случаем, а не типичным.
    # На практике API разбивку отдаёт всегда, и в журнале боевые строки идут без cache_w_1h.
    cc = getattr(usage, "cache_creation", None)
    w1h = int(getattr(cc, "ephemeral_1h_input_tokens", 0) or 0) if cc else 0
    w5m = int(getattr(cc, "ephemeral_5m_input_tokens", 0) or 0) if cc else 0
    if not (w1h or w5m):
        w1h = cache_w
    stu = getattr(usage, "server_tool_use", None)
    searches = int(getattr(stu, "web_search_requests", 0) or 0) if stu else 0
    return {"in": g("input_tokens"), "out": g("output_tokens"),
            "cache_w": cache_w, "cache_w_1h": w1h, "cache_r": g("cache_read_input_tokens"),
            "search": searches}


def _cost(model: str, u: dict) -> float:
    inp, out = RATES.get(model, _DEFAULT)
    w1h = u.get("cache_w_1h", 0)
    w5m = max(u["cache_w"] - w1h, 0)
    return (u["in"] * inp + w5m * inp * 1.25 + w1h * inp * 2.0 + u["cache_r"] * inp * 0.1
            + u["out"] * out) / 1_000_000 + u.get("search", 0) * SEARCH_RATE


def record(model, usage) -> None:
    """Записать расход одного вызова API: всегда лог в консоль, в итог — если идёт замер."""
    try:
        u = _usage_dict(usage)
    except Exception:
        logging.exception("[cost] не смог прочитать usage")
        return
    c = _cost(model, u)
    tok = u["in"] + u["out"] + u["cache_w"] + u["cache_r"]
    logging.info("[cost] %s: %d ток (вход %d, кэш-зап %d, кэш-чт %d, выход %d%s) → $%.4f",
                 model, tok, u["in"], u["cache_w"], u["cache_r"], u["out"],
                 f", поисков {u['search']}" if u.get("search") else "", c)
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
        a = by.setdefault(m, {"in": 0, "out": 0, "cache_w": 0, "cache_r": 0, "search": 0,
                              "cost": 0.0, "calls": 0})
        for k in ("in", "out", "cache_w", "cache_r", "search"):
            a[k] += u.get(k, 0)
        a["cost"] += _cost(m, u)
        a["calls"] += 1
    lines = ["=== Расход Claude за прогон ==="]
    for m, a in by.items():
        tok = a["in"] + a["out"] + a["cache_w"] + a["cache_r"]
        hit = (100 * a["cache_r"] / (a["cache_r"] + a["in"])) if (a["cache_r"] + a["in"]) else 0
        lines.append(f"  {m}: {a['calls']} выз · {tok} ток "
                     f"(вход {a['in']}, кэш-зап {a['cache_w']}, кэш-чт {a['cache_r']}, выход {a['out']}) "
                     f"→ ${a['cost']:.3f} · кэш-хит {hit:.0f}%")
    tot_in = sum(a["in"] for a in by.values())
    tot_r = sum(a["cache_r"] for a in by.values())
    calls = sum(a["calls"] for a in by.values())
    hit = (100 * tot_r / (tot_r + tot_in)) if (tot_r + tot_in) else 0
    lines.append(f"ИТОГО Скаут→пост: ${total():.3f} · кэш-хит {hit:.0f}%")
    # АВТО-КОНТРОЛЬ КЭША: если на серии вызовов хит низкий — кэш молча не экономит, кричим сразу.
    if calls >= 3 and hit < 40:
        lines.append("⚠️ КЭШ-ХИТ НИЗКИЙ — кэш почти не экономит (протух TTL / сменился системный промпт / "
                     "изолированный прогон). Норма на серии — ≥60%. Тренд: python run_cost_report.py")
    return "\n".join(lines)
