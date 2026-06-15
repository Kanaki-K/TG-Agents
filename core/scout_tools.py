"""Инструменты Скаута — разведка трендов/источников + сверка с историей канала.

- scan_sources — чтение известных фидов Тир-2 (connectors/web_sources).
- find_posts / by_theme / themes_overview / channel_summary — те же «руки» аналитика
  (core/analytics): дедуп «было ли уже» и привязка к реально заходящим темам.
- propose_source — кладёт кандидата-источник в memory/sources.pending.md (гейт: владелец одобряет).

Веб-поиск (Тир-1 / новые источники) — серверный инструмент Anthropic, подключается в
scout_bot отдельно: его выполняет Claude, здесь мы его не диспетчеризуем.
"""
from __future__ import annotations

from connectors.web_sources import feeds
from core import analytics, config

PENDING = config.ROOT / "memory" / "sources.pending.md"

TOOLS = [
    {
        "name": "scan_sources",
        "description": "Свежие записи из проверенных источников Тир-2 (Lyn Alden, Arthur Hayes, "
                       "Glassnode Research). Начинай разведку с него. Можно сузить параметром source.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "фильтр по имени источника (необязательно)"},
                "per_source": {"type": "integer", "description": "сколько записей с источника (по умолч. 4)"},
            },
        },
    },
    {
        "name": "find_posts",
        "description": "Искать посты канала по слову/теме — проверить, выходило ли уже похожее (дедуп).",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "n": {"type": "integer"}},
            "required": ["query"],
        },
    },
    {
        "name": "by_theme",
        "description": "Все посты канала по теме — что уже освещалось (для отсылок и анти-повтора).",
        "input_schema": {
            "type": "object",
            "properties": {"theme": {"type": "string", "description": "название темы, напр. 'Новости рынка'"}},
            "required": ["theme"],
        },
    },
    {
        "name": "themes_overview",
        "description": "Темы канала со средними метриками: ЧТО исторически заходит. Используй, чтобы "
                       "ранжировать находки по реальной пользе, а не только по нише.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "channel_summary",
        "description": "Общая сводка канала (период, средние метрики) — контекст для оценки релевантности.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "propose_source",
        "description": "Предложить НОВЫЙ источник в реестр (нашёл стоящий в веб-разведке). Не добавляет "
                       "сам — кладёт кандидата в очередь на одобрение владельца.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "имя источника"},
                "url": {"type": "string", "description": "ссылка/RSS"},
                "tier": {"type": "string", "description": "тир: 1 / 2 / 3"},
                "why": {"type": "string", "description": "почему ему можно доверять и чем полезен нише"},
            },
            "required": ["name", "why"],
        },
    },
]


def _render(items: list[dict]) -> str:
    if not items:
        return "Свежих записей не найдено."
    out = []
    for it in items:
        if it.get("error"):
            out.append(f"⚠ {it['name']}: фид не прочитан ({it['error']})")
            continue
        line = f"[{it['name']}] {it['title']}"
        if it.get("published"):
            line += f" ({it['published']})"
        if it.get("summary"):
            line += f"\n{it['summary']}"
        if it.get("link"):
            line += f"\n{it['link']}"
        out.append(line)
    return "\n\n".join(out)


def _propose_source(args: dict) -> str:
    PENDING.parent.mkdir(exist_ok=True)
    header = "" if PENDING.exists() else "# Кандидаты в источники (ожидают одобрения владельца)\n\n"
    entry = f"- **{args.get('name', '?')}** (тир {args.get('tier', '?')}) — {args.get('why', '')}"
    if args.get("url"):
        entry += f" — {args['url']}"
    with open(PENDING, "a", encoding="utf-8", newline="\n") as f:
        f.write(header + entry + "\n")
    return ("Кандидат записан в memory/sources.pending.md — в ядро НЕ добавлен. "
            "Покажи владельцу и дождись одобрения, прежде чем считать его доверенным источником.")


def dispatch(name: str, args: dict) -> str:
    if name == "scan_sources":
        return _render(feeds.fetch_recent(int(args.get("per_source", 4)), args.get("source", "")))
    if name == "find_posts":
        return analytics.find_posts(args["query"], int(args.get("n", 8)))
    if name == "by_theme":
        return analytics.by_theme(args["theme"])
    if name == "themes_overview":
        return analytics.themes_overview()
    if name == "channel_summary":
        return analytics.summary()
    if name == "propose_source":
        return _propose_source(args)
    return f"Неизвестный инструмент: {name}"
