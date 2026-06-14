"""Инструменты агента-аналитика — «руки» для чтения метрик канала.

Схемы отдаём в Claude; dispatch() выполняет функции из core/analytics.py.
"""
from __future__ import annotations

from core import analytics

TOOLS = [
    {
        "name": "channel_summary",
        "description": "Общая сводка: число постов, период, средние метрики и "
                       "ключевые цифры канала (подписчики, просмотры/пост и динамика).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "top_posts",
        "description": "Лучшие посты по метрике. Используй, когда спрашивают «что зашло».",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string",
                           "description": "views | reactions | comments | forwards | er"},
                "n": {"type": "integer", "description": "сколько постов (по умолч. 10)"},
                "content_type": {"type": "string",
                                 "description": "фильтр: 'Текст' или 'Медиа' (необязательно)"},
            },
        },
    },
    {
        "name": "bottom_posts",
        "description": "Худшие посты по метрике — что не зашло.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "views | reactions | comments | forwards | er"},
                "n": {"type": "integer"},
            },
        },
    },
    {
        "name": "by_dimension",
        "description": "Средние метрики в разрезе: weekday (дни недели), hour (часы суток) "
                       "или type (текст/медиа). Для выводов о лучшем времени/формате.",
        "input_schema": {
            "type": "object",
            "properties": {"dim": {"type": "string", "description": "weekday | hour | type"}},
            "required": ["dim"],
        },
    },
    {
        "name": "post_details",
        "description": "Полная карточка одного поста по его id (метрики + текст).",
        "input_schema": {
            "type": "object",
            "properties": {"post_id": {"type": "integer"}},
            "required": ["post_id"],
        },
    },
    {
        "name": "find_posts",
        "description": "Найти посты по слову/теме в тексте — чтобы сравнить тематики.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "n": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "themes_overview",
        "description": "Темы канала со средними метриками: какие темы заходят лучше/хуже. "
                       "Главный инструмент для совета «с чем работать, а с чем нет».",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "by_theme",
        "description": "Все посты по заданной теме — что уже выходило (чтобы не повторяться "
                       "и делать отсылки к прошлому контенту).",
        "input_schema": {
            "type": "object",
            "properties": {"theme": {"type": "string", "description": "название темы, напр. 'DeFi'"}},
            "required": ["theme"],
        },
    },
    {
        "name": "audience",
        "description": "Сводка по аудитории: источники просмотров и подписок, языки.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "update_metrics",
        "description": "«Обновить»: пересобрать свежие метрики канала и таблицу. "
                       "Вызывай, когда просят обновить данные/сделать свежий снимок.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def dispatch(name: str, args: dict) -> str:
    if name == "channel_summary":
        return analytics.summary()
    if name == "top_posts":
        return analytics.top_posts(args.get("metric", "views"),
                                   int(args.get("n", 10)), args.get("content_type", ""))
    if name == "bottom_posts":
        return analytics.bottom_posts(args.get("metric", "views"), int(args.get("n", 10)))
    if name == "by_dimension":
        return analytics.by_dimension(args.get("dim", "weekday"))
    if name == "post_details":
        return analytics.post_details(int(args["post_id"]))
    if name == "find_posts":
        return analytics.find_posts(args["query"], int(args.get("n", 8)))
    if name == "themes_overview":
        return analytics.themes_overview()
    if name == "by_theme":
        return analytics.by_theme(args["theme"])
    if name == "audience":
        return analytics.audience()
    if name == "update_metrics":
        return analytics.refresh_metrics(full=True)
    return f"Неизвестный инструмент: {name}"
