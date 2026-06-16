"""Инструменты Скаута — разведка трендов/источников + сверка с историей канала.

- scan_sources — чтение известных фидов Тир-2 (connectors/web_sources).
- find_posts / by_theme / themes_overview / channel_summary — те же «руки» аналитика
  (core/analytics): дедуп «было ли уже» и привязка к реально заходящим темам.
- propose_source — кладёт кандидата-источник в memory/sources.pending.md (гейт: владелец одобряет).

Веб-поиск (Тир-1 / новые источники) — серверный инструмент Anthropic, подключается в
scout_bot отдельно: его выполняет Claude, здесь мы его не диспетчеризуем.
"""
from __future__ import annotations

from connectors.telegram_scan import read as tg_read
from connectors.web_sources import feeds
from connectors.x_scan import read as x_read
from core import analytics, config

PENDING = config.ROOT / "memory" / "sources.pending.md"

TOOLS = [
    {
        "name": "scan_sources",
        "description": "Свежие записи из проверенных RSS-источников Тир-2 по трекам: "
                       "crypto (Lyn Alden, Arthur Hayes, Glassnode) и ai (Stratechery, Import AI). "
                       "Начинай разведку с него. Фильтры: track ('crypto'|'ai') и source (имя).",
        "input_schema": {
            "type": "object",
            "properties": {
                "track": {"type": "string", "description": "трек: 'crypto' | 'ai' (пусто = оба)"},
                "source": {"type": "string", "description": "фильтр по имени источника (необязательно)"},
                "per_source": {"type": "integer", "description": "сколько записей с источника (по умолч. 4)"},
            },
        },
    },
    {
        "name": "scan_telegram",
        "description": "Свежие сообщения из ТГ-каналов Тир-3 по трекам crypto/ai — что разгоняется "
                       "СЕЙЧАС (скорость/хайп). Источники НЕ авторитетные: всё отсюда обязательно "
                       "проверяй на достоверность и прослеживание к Тир-1/2, не выдавай за факт.",
        "input_schema": {
            "type": "object",
            "properties": {
                "track": {"type": "string", "description": "трек: 'crypto' | 'ai' (пусто = оба)"},
                "channel": {"type": "string", "description": "фильтр по имени канала (необязательно)"},
                "limit_per_channel": {"type": "integer", "description": "сообщений с канала (по умолч. 5)"},
            },
        },
    },
    {
        "name": "scan_x",
        "description": "Свежие твиты КУРИРУЕМЫХ лидеров мнений в X/Twitter (Arthur Hayes, Lyn Alden, "
                       "Glassnode, Raoul Pal, Saylor, Balaji ...) по трекам crypto/ai. ЭДЖ Скаута: "
                       "X не индексируется веб-поиском, дип-ресёрч его НЕ видит — а первичные голоса "
                       "появляются тут РАНЬШЕ блога/RSS (Тир-1/2 по скорости). Доступ read-only через "
                       "бёрнер-сессию, объём малый. Цифры из твита без первоисточника → «не подтверждено». "
                       "Фильтры: track ('crypto'|'ai'), handle (имя аккаунта), limit_per_account.",
        "input_schema": {
            "type": "object",
            "properties": {
                "track": {"type": "string", "description": "трек: 'crypto' | 'ai' (пусто = оба)"},
                "handle": {"type": "string", "description": "фильтр по имени аккаунта (необязательно)"},
                "limit_per_account": {"type": "integer", "description": "твитов с аккаунта (по умолч. 6)"},
            },
        },
    },
    {
        "name": "fetch_url",
        "description": "Открыть страницу по ссылке и прочитать её текст — чтобы вытащить ТОЧНЫЕ "
                       "цифры/цитаты из источника (индекс страха, корреляции, ETF-потоки, даты), а не "
                       "только сниппет из поиска. Открывай найденные ссылки ПЕРЕД тем, как ставить цифру "
                       "в направление.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "ссылка на статью/источник"}},
            "required": ["url"],
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
        line = f"[{it.get('track', '?')} | {it['name']}] {it['title']}"
        if it.get("published"):
            line += f" ({it['published']})"
        if it.get("summary"):
            line += f"\n{it['summary']}"
        if it.get("link"):
            line += f"\n{it['link']}"
        out.append(line)
    return "\n\n".join(out)


def _render_tg(items: list[dict]) -> str:
    if not items:
        return "Свежих сообщений в ТГ-каналах не найдено."
    out = []
    for it in items:
        if it.get("error"):
            out.append(f"⚠ {it.get('channel', 'TG')}: {it['error']}")
            continue
        line = f"[{it.get('track', '?')} | {it['channel']}]"
        if it.get("date"):
            line += f" {it['date']}"
        if it.get("text"):
            line += f"\n{it['text']}"
        out.append(line)
    return "\n\n".join(out)


def _render_x(items: list[dict]) -> str:
    if not items:
        return "Свежих твитов у лидеров X не найдено."
    out = []
    for it in items:
        if it.get("error"):
            out.append(f"⚠ @{it.get('handle', 'X')}: {it['error']}")
            continue
        line = f"[{it.get('track', '?')} | @{it['handle']}]"
        if it.get("date"):
            line += f" {it['date']}"
        metrics = []
        for label, key in (("♥", "likes"), ("RT", "retweets"), ("👁", "views")):
            if it.get(key) is not None:
                metrics.append(f"{label}{it[key]}")
        if metrics:
            line += f"  ({' '.join(metrics)})"
        if it.get("text"):
            line += f"\n{it['text']}"
        if it.get("url"):
            line += f"\n{it['url']}"
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
        return _render(feeds.fetch_recent(int(args.get("per_source", 4)),
                                          args.get("source", ""), args.get("track", "")))
    if name == "scan_telegram":
        return _render_tg(tg_read.recent(int(args.get("limit_per_channel", 5)),
                                         args.get("channel", ""), args.get("track", "")))
    if name == "scan_x":
        return _render_x(x_read.recent(int(args.get("limit_per_account", 6)),
                                       args.get("handle", ""), args.get("track", "")))
    if name == "fetch_url":
        return feeds.fetch_page(args["url"])
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
