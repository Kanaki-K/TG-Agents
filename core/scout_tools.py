"""Инструменты Скаута — разведка трендов/источников + сверка с историей канала.

- scan_sources — чтение известных фидов Тир-2 (connectors/web_sources).
- find_posts / by_theme / themes_overview / channel_summary — те же «руки» аналитика
  (core/analytics): дедуп «было ли уже» и привязка к реально заходящим темам.
- propose_source — кладёт кандидата-источник в memory/sources.pending.md (гейт: владелец одобряет).

Веб-поиск (Тир-1 / новые источники) — серверный инструмент Anthropic, подключается в
scout_bot отдельно: его выполняет Claude, здесь мы его не диспетчеризуем.
"""
from __future__ import annotations

import re
import time
from datetime import date

from connectors.telegram_scan import read as tg_read
from connectors.web_sources import feeds
from connectors.x_scan import read as x_read
from core import analytics_tools, config

PENDING = config.ROOT / "memory" / "sources.pending.md"
PENDING_X = config.ROOT / "memory" / "x_leaders.pending.md"
BRIEFS_DIR = config.ROOT / "memory" / "briefs"   # полные брифы разведки — рабочий материал Криейтора

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
                "max_accounts": {"type": "integer", "description": "сколько аккаунтов читать с верха "
                                 "списка (по умолч. 12 — самые сильные). Подними для глубокого захода "
                                 "по всей профессиональной скамейке; при заданном handle игнорируется."},
                "tier": {"type": "string", "description": "какие тиры читать: пусто = только 'эталон' "
                         "(по умолчанию); 'all' = эталон+тир2 (глубокий скан); либо конкретный тир."},
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
        "name": "propose_x_leader",
        "description": "Предложить НОВЫЙ X-аккаунт в leaders.yaml (заметил сильный, подходящий бренду — "
                       "в цитатах/упоминаниях лент или в поиске). НЕ добавляет сам — кладёт кандидата в "
                       "очередь на одобрение владельца. Предлагай только профессиональный сигнал по нише "
                       "(крипта/макро; AI с крипто-мостом), без инфлюенсеров/шиткоин-шума; обоснуй бренд-фит.",
        "input_schema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string", "description": "хэндл без @ (как в x.com/<handle>)"},
                "track": {"type": "string", "description": "трек: 'crypto' | 'ai'"},
                "why": {"type": "string", "description": "почему подходит бренду и чем ценен (сигнал, не шум)"},
            },
            "required": ["handle", "why"],
        },
    },
    {
        "name": "save_brief",
        "description": "Сохранить ПОЛНЫЙ бриф разведки в файл (memory/briefs/) — рабочий материал для "
                       "Криейтора и архив. В чат потом выдаёшь только сухую выжимку. Вызывай ОДИН раз в "
                       "конце /scan, передав весь развёрнутый бриф (5 направлений со всей глубиной + вердикт).",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "полный бриф в markdown: 5 направлений "
                            "(угол, нам заходит, опора 2-3 сильнейших источника + ссылки + тир, хук-цифры, "
                            "свежесть, caveat) + вывод + вердикт по каналам"},
                "slug": {"type": "string", "description": "короткий ярлык темы дня, напр. 'boj-btc' (необязательно)"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "read_recent_briefs",
        "description": "Прочитать брифы разведки за последние N дней (memory/briefs/, без недельных "
                       "срезов) — для НЕДЕЛЬНОГО среза: собрать всё найденное за неделю и сжать в "
                       "концентрат без дублей.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "за сколько дней (по умолч. 7)"}},
        },
    },
    {
        "name": "read_x_account",
        "description": "Прочитать свежие твиты ЛЮБОГО X-аккаунта по хэндлу (даже если его нет в "
                       "leaders.yaml) — для ГЛУБОКОЙ проверки кандидата на бренд-фит перед добавлением.",
        "input_schema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string", "description": "хэндл без @"},
                "limit": {"type": "integer", "description": "сколько твитов (по умолч. 8)"},
            },
            "required": ["handle"],
        },
    },
    {
        "name": "read_x_pending",
        "description": "Прочитать очередь накопленных кандидатов в X-лидеры (то, что Скаут предлагал "
                       "через propose_x_leader за неделю). С этого начинай еженедельную курацию.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_x_ledger",
        "description": "Леджер авторов X: у каждого тир (эталон/тир2/кандидат/отклонён), счётчик "
                       "проверок и история вердиктов. С него начинай курацию — видно, кого пора "
                       "перепроверить и у кого уже накопился чистый след для повышения.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "update_x_author",
        "description": "Записать вердикт проверки автора: выставить/изменить ТИР и добавить датированную "
                       "заметку (счётчик проверок растёт сам). Тиры: 'эталон' (чисто, читаем по умолчанию), "
                       "'тир2' (иногда ок, не эталон — только глубокий скан), 'кандидат' (на испытании, не "
                       "сканим), 'отклонён' (мусор). НЕ повышай до 'эталон' с одной проверки — нужен "
                       "стабильно чистый след за несколько недель (~5). 'Запахло' — понижай в 'тир2'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string", "description": "хэндл без @"},
                "track": {"type": "string", "description": "трек: 'crypto' | 'ai' (если новый)"},
                "tier": {"type": "string", "description": "эталон | тир2 | кандидат | отклонён"},
                "note": {"type": "string", "description": "вердикт этой проверки одной фразой (что увидел)"},
            },
            "required": ["handle", "note"],
        },
    },
    {
        "name": "clear_x_pending",
        "description": "Очистить очередь кандидатов — вызывай в КОНЦЕ еженедельной курации, после того "
                       "как разобрал всех (добавил подходящих через add_x_leader, остальных отклонил).",
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


def _save_brief(args: dict) -> str:
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9-]+", "-", str(args.get("slug", "") or "scan").lower()).strip("-") or "scan"
    fname = f"{date.today().isoformat()}-{slug}.md"
    (BRIEFS_DIR / fname).write_text(args.get("content", ""), encoding="utf-8", newline="\n")
    return (f"Полный бриф сохранён: memory/briefs/{fname}. "
            f"Теперь выдай в чат ТОЛЬКО сухую выжимку и укажи этот путь для Криейтора.")


def _read_recent_briefs(days: int = 7) -> str:
    if not BRIEFS_DIR.exists():
        return "Папки брифов ещё нет — за период ничего не накоплено."
    cutoff = time.time() - max(1, days) * 86400
    files = sorted(
        [p for p in BRIEFS_DIR.glob("*.md") if p.stat().st_mtime >= cutoff and "weekly" not in p.stem],
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        return f"За последние {days} дн. брифов разведки не найдено."
    parts, total = [], 0
    for p in files:
        chunk = f"=== {p.name} ===\n{p.read_text(encoding='utf-8')[:6000]}"
        if total + len(chunk) > 40000:  # кап на контекст
            parts.append("… (более старые брифы обрезаны)")
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)


def _read_x_pending() -> str:
    if not PENDING_X.exists() or not PENDING_X.read_text(encoding="utf-8").strip():
        return "Очередь кандидатов в X-лидеры пуста — за период новых предложений не накопилось."
    return PENDING_X.read_text(encoding="utf-8")


def _clear_x_pending() -> str:
    if PENDING_X.exists():
        PENDING_X.unlink()
    return "Очередь кандидатов очищена."


def _propose_x_leader(args: dict) -> str:
    PENDING_X.parent.mkdir(exist_ok=True)
    header = "" if PENDING_X.exists() else "# Кандидаты в X-лидеры (ожидают одобрения владельца)\n\n"
    handle = str(args.get("handle", "?")).lstrip("@")
    entry = (f"- **@{handle}** ({args.get('track', '?')}) — {args.get('why', '')} "
             f"— https://x.com/{handle}")
    with open(PENDING_X, "a", encoding="utf-8", newline="\n") as f:
        f.write(header + entry + "\n")
    return ("Кандидат записан в memory/x_leaders.pending.md — в leaders.yaml НЕ добавлен. "
            "Покажи владельцу; одобрит — впишем в leaders.yaml.")


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
    shared = analytics_tools.handle(name, args)  # общие read-only аналитич. инструменты (дедуп)
    if shared is not None:
        return shared
    if name == "scan_sources":
        return _render(feeds.fetch_recent(int(args.get("per_source", 4)),
                                          args.get("source", ""), args.get("track", "")))
    if name == "scan_telegram":
        return _render_tg(tg_read.recent(int(args.get("limit_per_channel", 5)),
                                         args.get("channel", ""), args.get("track", "")))
    if name == "scan_x":
        return _render_x(x_read.recent(int(args.get("limit_per_account", 6)),
                                       args.get("handle", ""), args.get("track", ""),
                                       int(args.get("max_accounts", 12)), args.get("tier", "")))
    if name == "fetch_url":
        return feeds.fetch_page(args["url"])
    if name == "save_brief":
        return _save_brief(args)
    if name == "read_recent_briefs":
        return _read_recent_briefs(int(args.get("days", 7)))
    if name == "read_x_account":
        return _render_x(x_read.account_tweets(args["handle"], int(args.get("limit", 8))))
    if name == "read_x_ledger":
        return x_read.read_ledger_text()
    if name == "read_x_pending":
        return _read_x_pending()
    if name == "update_x_author":
        return x_read.update_author(args["handle"], args.get("track", ""),
                                    args.get("tier", ""), args.get("note", ""))
    if name == "clear_x_pending":
        return _clear_x_pending()
    if name == "propose_x_leader":
        return _propose_x_leader(args)
    if name == "propose_source":
        return _propose_source(args)
    return f"Неизвестный инструмент: {name}"
