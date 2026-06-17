"""Инструменты Криейтора — забрать материал Скаута, свериться с каналом, сохранить драфт.

Криейтор ПИШЕТ; «руки» у него минимальны и служат письму (навыки — по мере боли, не впрок):
- list_briefs / read_brief — забирают рабочий материал Скаута (memory/briefs/) НАПРЯМУЮ;
  это и есть стык «ресёрч → пост»: владельцу больше не нужно копировать бриф в чат.
- find_posts / by_theme — сверка с историей канала (core/analytics): не повторить угол,
  сослаться на прошлый пост, опереться на личный опыт автора.
- save_draft — положить готовый драфт в архив (memory/drafts/) для правки и недельного отчёта.

Публикации тут нет намеренно: драфт — автомат, публикует владелец (см. PLAN §6, чек-лист безопасности).
"""
from __future__ import annotations

import re
from datetime import date

from core import analytics, config

BRIEFS_DIR = config.ROOT / "memory" / "briefs"   # продукт Скаута — вход Криейтора
DRAFTS_DIR = config.ROOT / "memory" / "drafts"   # архив драфтов — выход Криейтора

TOOLS = [
    {
        "name": "list_briefs",
        "description": "Список брифов разведки Скаута (memory/briefs/), свежие сверху: имя файла, "
                       "дата, первая строка-заголовок. С него начинай, когда владелец говорит «пиши "
                       "по последнему брифу» / «бриф про BoJ» — чтобы понять, какой именно читать.",
        "input_schema": {
            "type": "object",
            "properties": {"n": {"type": "integer", "description": "сколько последних показать (по умолч. 8)"}},
        },
    },
    {
        "name": "read_brief",
        "description": "Прочитать ПОЛНЫЙ бриф Скаута — рабочий материал для поста (5 направлений: угол, "
                       "«нам заходит», опора-источники со ссылками и тирами, хук-цифры, caveat). Это "
                       "стык «ресёрч → пост»: бери цифры/факты/ссылки отсюда, не копируй из чата. "
                       "which: 'latest' (по умолч. — самый свежий) либо часть имени/даты/слага "
                       "(напр. 'boj' или '2026-06-16').",
        "input_schema": {
            "type": "object",
            "properties": {"which": {"type": "string", "description": "'latest' | часть имени/даты/слага"}},
        },
    },
    {
        "name": "find_posts",
        "description": "Искать посты канала по слову/теме — проверить, выходило ли уже похожее (не "
                       "повторить угол) и на что сослаться («как я писал ранее»). Опирай пост на "
                       "реальную историю канала, а не на догадки.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "n": {"type": "integer"}},
            "required": ["query"],
        },
    },
    {
        "name": "by_theme",
        "description": "Все посты канала по теме — какие углы уже освещались (анти-повтор и отсылки).",
        "input_schema": {
            "type": "object",
            "properties": {"theme": {"type": "string", "description": "название темы, напр. 'Новости рынка'"}},
            "required": ["theme"],
        },
    },
    {
        "name": "save_draft",
        "description": "Сохранить готовый драфт поста в архив (memory/drafts/). Вызывай ОДИН раз в конце, "
                       "передав ПОЛНЫЙ текст поста (как пойдёт в чат, без служебных пометок). После — "
                       "выдай пост в чат владельцу. Это драфт на правку: публикует владелец, не ты.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "полный текст драфта поста (markdown)"},
                "slug": {"type": "string", "description": "короткий ярлык темы, напр. 'ai-stablecoins' (необязательно)"},
                "kind": {"type": "string", "description": "'flagman' | 'light' (необязательно, для имени файла)"},
            },
            "required": ["content"],
        },
    },
]


def _brief_files() -> list:
    if not BRIEFS_DIR.exists():
        return []
    return sorted(BRIEFS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:120]
    return "(пусто)"


def _list_briefs(n: int = 8) -> str:
    files = _brief_files()
    if not files:
        return ("Брифов Скаута пока нет (memory/briefs/ пуст). Напиши пост из присланного "
                "владельцем направления или попроси Скаута сделать /scan.")
    out = ["Брифы Скаута (свежие сверху):"]
    for p in files[:max(1, n)]:
        head = _first_heading(p.read_text(encoding="utf-8"))
        out.append(f"- {p.name} — {head}")
    return "\n".join(out)


def _read_brief(which: str = "latest") -> str:
    files = _brief_files()
    if not files:
        return ("Брифов Скаута нет (memory/briefs/ пуст). Пиши из присланного направления "
                "или попроси Скаута /scan.")
    q = (which or "latest").strip().lower()
    if q in ("", "latest", "последний", "свежий"):
        target = files[0]
    else:
        matches = [p for p in files if q in p.name.lower()]
        if not matches:
            avail = "\n".join(f"- {p.name}" for p in files[:8])
            return f"Бриф по запросу «{which}» не найден. Доступны:\n{avail}"
        target = matches[0]  # самый свежий из совпавших (files уже отсортирован)
    text = target.read_text(encoding="utf-8")
    cap = 40000  # кап на контекст: бриф большой, но всё в одну сессию не тащим
    body = text[:cap] + ("\n\n… (бриф обрезан)" if len(text) > cap else "")
    return f"=== {target.name} ===\n{body}"


def _save_draft(args: dict) -> str:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    kind = str(args.get("kind", "") or "").strip().lower()
    base = "-".join(x for x in (args.get("slug", "") or "post", kind) if x)
    slug = re.sub(r"[^a-z0-9-]+", "-", base.lower()).strip("-") or "post"
    fname = f"{date.today().isoformat()}-{slug}.md"
    (DRAFTS_DIR / fname).write_text(args.get("content", ""), encoding="utf-8", newline="\n")
    return (f"Драфт сохранён: memory/drafts/{fname}. Теперь выдай пост в чат владельцу — "
            f"это драфт на правку, публикует он.")


def dispatch(name: str, args: dict) -> str:
    if name == "list_briefs":
        return _list_briefs(int(args.get("n", 8)))
    if name == "read_brief":
        return _read_brief(args.get("which", "latest"))
    if name == "find_posts":
        return analytics.find_posts(args["query"], int(args.get("n", 8)))
    if name == "by_theme":
        return analytics.by_theme(args["theme"])
    if name == "save_draft":
        return _save_draft(args)
    return f"Неизвестный инструмент: {name}"
