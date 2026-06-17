"""Инструменты агента-аналитика — «руки» для чтения метрик канала.

Схемы отдаём в Claude; dispatch() выполняет функции из core/analytics.py.
save_playbook — Аналитик ведёт плейбук форматов (memory/format_playbook.md): какой формат
под что заходит (ER/репосты), рекомендации помимо флагмана. Этот файл читает Криейтор —
так Аналитик «консультирует» через общий слой памяти, без живого диалога (PLAN §11).
"""
from __future__ import annotations

from datetime import date

from core import analytics, config

PLAYBOOK = config.ROOT / "memory" / "format_playbook.md"

TOOLS = [
    {
        "name": "channel_summary",
        "description": "Общая сводка: число постов, период, средние метрики и "
                       "ключевые цифры канала (подписчики, просмотры/пост и динамика).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "top_posts",
        "description": "Лучшие посты по метрике. Используй, когда спрашивают «что зашло». "
                       "Можно отфильтровать по формату (напр. вытащить топ флагманов).",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string",
                           "description": "views | reactions | comments | forwards | er"},
                "n": {"type": "integer", "description": "сколько постов (по умолч. 10)"},
                "content_type": {"type": "string",
                                 "description": "фильтр: 'Текст' или 'Медиа' (необязательно)"},
                "post_format": {"type": "string",
                                "description": "фильтр по формату: флагман|обучающий|психология|"
                                               "личный|короткий|медиа|служебное (необязательно)"},
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
        "description": "Средние метрики в разрезе: weekday (дни недели), hour (часы суток), "
                       "type (текст/медиа) или format (флагман/обучающий/…). Для выводов о времени "
                       "и о том, какой ФОРМАТ заходит.",
        "input_schema": {
            "type": "object",
            "properties": {"dim": {"type": "string", "description": "weekday | hour | type | format"}},
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
    {
        "name": "save_playbook",
        "description": "Сохранить/обновить ПЛЕЙБУК ФОРМАТОВ (memory/format_playbook.md) — меню форматов "
                       "поста с их эффективностью и рекомендациями (что заходит помимо длинного флагмана). "
                       "Его читает Криейтор при выборе формата. Вызывай в конце /playbook, передав полный "
                       "плейбук: по каждому формату — что это, метрики (ER/репосты/просмотры), когда/кому "
                       "заходит, рекомендация (делать чаще/реже); отдельно — форматы-кандидаты под пробу.",
        "input_schema": {
            "type": "object",
            "properties": {"content": {"type": "string", "description": "полный плейбук форматов (markdown)"}},
            "required": ["content"],
        },
    },
    {
        "name": "formats_overview",
        "description": "Средние метрики по ФОРМАТАМ постов (флагман/обучающий/психология/личный/"
                       "короткий/медиа/служебное) — что заходит по формату. Главное для плейбука и "
                       "вопросов «какой формат сильнее». Требует размеченных форматов (classify_formats).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "by_format",
        "description": "Все посты заданного формата (напр. 'флагман'), сильные сверху — вытащить "
                       "примеры/историю формата. Удобно достать все флагманы канала.",
        "input_schema": {
            "type": "object",
            "properties": {"format": {"type": "string", "description": "флагман|обучающий|психология|личный|короткий|медиа|служебное"}},
            "required": ["format"],
        },
    },
    {
        "name": "classify_formats",
        "description": "Разметить ФОРМАТ всех постов (колонка формата). Эвристика: медиа без текста → "
                       "медиа; розыгрыши → служебное; МЕДИА + длинный текст (>=450 слов) → флагман; иначе "
                       "по теме (психология/обучающий/личный) либо короткий. По умолчанию дозаполняет "
                       "только НОВЫЕ посты и бережёт ручные правки; force=true — переразметить весь канал "
                       "заново. После — покажи распределение и предупреди, что спорные посты стоит "
                       "доразметить set_format.",
        "input_schema": {
            "type": "object",
            "properties": {"force": {"type": "boolean", "description": "переразметить весь канал заново (по умолч. false)"}},
        },
    },
    {
        "name": "set_format",
        "description": "Поправить формат ОДНОГО поста вручную (перекрывает авторазметку) — для спорных "
                       "случаев. Формат: флагман|обучающий|психология|личный|короткий|медиа|служебное.",
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {"type": "integer"},
                "format": {"type": "string"},
            },
            "required": ["post_id", "format"],
        },
    },
]


def dispatch(name: str, args: dict) -> str:
    if name == "channel_summary":
        return analytics.summary()
    if name == "top_posts":
        return analytics.top_posts(args.get("metric", "views"),
                                   int(args.get("n", 10)), args.get("content_type", ""),
                                   args.get("post_format", ""))
    if name == "formats_overview":
        return analytics.formats_overview()
    if name == "by_format":
        return analytics.by_format(args["format"])
    if name == "classify_formats":
        return analytics.auto_classify_formats(bool(args.get("force", False)))
    if name == "set_format":
        return analytics.set_format(int(args["post_id"]), args.get("format", ""))
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
    if name == "save_playbook":
        return _save_playbook(args)
    return f"Неизвестный инструмент: {name}"


def _save_playbook(args: dict) -> str:
    content = str(args.get("content", "") or "").strip()
    if not content:
        return "Пустой плейбук — нечего сохранять."
    header = f"# Плейбук форматов — KANAKI CRYPTO (обновлён {date.today().isoformat()})\n\n"
    PLAYBOOK.parent.mkdir(parents=True, exist_ok=True)
    PLAYBOOK.write_text(header + content + "\n", encoding="utf-8", newline="\n")
    return ("Плейбук форматов сохранён: memory/format_playbook.md. Его подхватит Криейтор "
            "при выборе формата. Дай владельцу краткую выжимку, что в нём.")
