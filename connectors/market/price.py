"""Живая рыночная цена (CoinMarketCap) — «руки» для ТОЧНОЙ сверки чисел.

Зачем: и Криейтор («цена сегодня $X»), и 2FA-фактчек живут на web_search, а он по цене лагает и
приблизителен. Реальный кейс: пост говорил $61 000, фактчек «не подтверждено», а спот был $58 804 —
верное число никто дать не мог. Прямой ценовой API возвращает ТОЧНЫЙ спот «прямо сейчас» одним
вызовом; модель вписывает/сверяет уже выверенной цифрой. Отдаёт готовый ТЕКСТ — как analytics.*.

Источник: CoinMarketCap Pro API. Нужен COINMARKETCAP_API_KEY в .env (бесплатный тир ~10k/мес); нет
ключа → понятное сообщение, конвейер не падает. HTTP — stdlib urllib (без новых зависимостей).
Хост URL фиксирован (не из ввода) — SSRF неприменим; из ввода только тикеры, их санитизируем до [A-Z0-9].
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from core import config

API_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
DEFAULT_SYMBOLS = "BTC,ETH"
_SYMBOL_RE = re.compile(r"[^A-Z0-9]")
_MAX_SYMBOLS = 15          # кап на размер запроса (бережём лимит ключа)
_CACHE_TTL = 60.0          # сек: один прогон не дёргает API на каждый вызов
_cache: dict[str, tuple[float, str]] = {}


def _norm_symbols(symbols) -> list[str]:
    parts = symbols if isinstance(symbols, (list, tuple)) else re.split(r"[,\s]+", str(symbols or ""))
    out: list[str] = []
    for p in parts:
        s = _SYMBOL_RE.sub("", str(p).upper())
        if s and s not in out:
            out.append(s)
    return out[:_MAX_SYMBOLS]


def _fmt_price(v: float) -> str:
    if v >= 100:
        return f"${v:,.0f}"
    if v >= 1:
        return f"${v:,.2f}"
    return ("$" + f"{v:.6f}".rstrip("0").rstrip("."))   # дешёвые альты — больше знаков


def _fmt_cap(v: float) -> str:
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if v >= div:
            return f"${v / div:.2f}{unit}"
    return f"${v:,.0f}"


def spot(symbols=DEFAULT_SYMBOLS) -> str:
    """Текущая цена монет (USD) + изменение 24ч/7д + капитализация. Готовый текст для модели."""
    syms = _norm_symbols(symbols) or _norm_symbols(DEFAULT_SYMBOLS)
    cache_key = ",".join(syms)
    now = time.monotonic()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    api_key = config.get_optional("COINMARKETCAP_API_KEY")
    if not api_key:
        return ("(живая цена недоступна: не задан COINMARKETCAP_API_KEY в .env — впиши ключ "
                "CoinMarketCap. Пока сверяй цену через web_search.)")
    url = f"{API_URL}?symbol={urllib.parse.quote(cache_key)}&convert=USD"
    req = urllib.request.Request(url, headers={
        "X-CMC_PRO_API_KEY": api_key, "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:   # noqa: S310 — хост фиксирован (CMC)
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg = ""
        try:
            msg = (json.loads(e.read().decode("utf-8")).get("status") or {}).get("error_message") or ""
        except Exception:
            pass
        hint = " (проверь ключ/лимит)" if e.code in (401, 403, 429) else ""
        return f"(CoinMarketCap: ошибка {e.code}{hint}{': ' + msg if msg else ''} — пока сверь цену web_search.)"
    except Exception as e:  # noqa: BLE001 — сеть/таймаут не должны ронять агента
        return f"(не удалось получить живую цену: {type(e).__name__} — сверь цену через web_search.)"

    data = payload.get("data") or {}
    lines = ["Рыночная цена СЕЙЧАС (CoinMarketCap, спот в реальном времени):"]
    for s in syms:
        d = data.get(s)
        if isinstance(d, list):
            d = d[0] if d else None
        q = ((d or {}).get("quote") or {}).get("USD") or {}
        price = q.get("price")
        if price is None:
            lines.append(f"  {s}: не найдено (проверь тикер)")
            continue
        line = f"  {s} {_fmt_price(price)}"
        moves = []
        if q.get("percent_change_24h") is not None:
            moves.append(f"24ч {q['percent_change_24h']:+.1f}%")
        if q.get("percent_change_7d") is not None:
            moves.append(f"7д {q['percent_change_7d']:+.1f}%")
        if moves:
            line += " (" + ", ".join(moves) + ")"
        if q.get("market_cap"):
            line += f" | капа {_fmt_cap(q['market_cap'])}"
        lines.append(line)
    text = "\n".join(lines)
    _cache[cache_key] = (now, text)   # кэшируем только успех (ошибку не залипляем на TTL)
    return text
