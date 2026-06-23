"""Общий dispatch read-only аналитических инструментов (дедуп P2-13).

Один бэкенд (core/analytics.py) дёргают Скаут/Аналитик/Криейтор ОДИНАКОВО для ряда инструментов —
держим маппинг «имя инструмента → вызов» в ОДНОМ месте, чтобы ветки `if name == ...` не копировались
по `*_tools.py`. Каждый агент в своём dispatch сначала зовёт handle(), и если имя не наше — обрабатывает
сам.

Что СОЗНАТЕЛЬНО НЕ объединяем:
- СХЕМЫ инструментов (их описания в TOOLS у каждого агента) — они сформулированы под роль агента
  (Скаут: find_posts = «дедуп»; Криейтор: «анти-повтор»; Аналитик: «сравнение тематик»). Это не дубль,
  а полезная ролевая подсказка модели — оставляем в `*_tools.py`.
- top_posts — у Аналитика дефолт metric='views' (+ post_format), у Криейтора 'er'. Расхождение реальное,
  ветка остаётся в их собственных dispatch.
"""
from __future__ import annotations

from core import analytics

# Только инструменты с ИДЕНТИЧНЫМ вызовом во всех агентах, которые их используют.
_SHARED = {
    "channel_summary": lambda a: analytics.summary(),
    "find_posts": lambda a: analytics.find_posts(a["query"], int(a.get("n", 8))),
    "by_theme": lambda a: analytics.by_theme(a["theme"]),
    "themes_overview": lambda a: analytics.themes_overview(),
    "by_dimension": lambda a: analytics.by_dimension(a.get("dim", "weekday")),
    "recent_posts": lambda a: analytics.recent_posts(int(a.get("n", 5)), a.get("post_format", "")),
}


def handle(name: str, args: dict):
    """Результат общего аналитического инструмента, либо None если имя не наше
    (тогда агент обрабатывает инструмент в своём dispatch)."""
    fn = _SHARED.get(name)
    return fn(args) if fn else None
