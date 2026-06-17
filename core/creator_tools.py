"""Инструменты Криейтора — забрать материал Скаута, свериться с каналом, сохранить драфт, учиться.

Криейтор ПИШЕТ; «руки» у него минимальны и служат письму (навыки — по мере боли, не впрок):
- list_briefs / read_brief — забирают рабочий материал Скаута (memory/briefs/) НАПРЯМУЮ;
  это и есть стык «ресёрч → пост»: владельцу больше не нужно копировать бриф в чат.
- find_posts / by_theme — сверка с историей канала (core/analytics): не повторить угол,
  сослаться на прошлый пост, опереться на личный опыт автора.
- save_draft — положить готовый драфт в архив (memory/drafts/) для правки и недельного отчёта.
- list_drafts / read_draft — поднять СВОЙ прошлый драфт, чтобы сравнить с финалом владельца.
- record_lesson — петля обучения: усвоить урок из правки владельца в memory/post_lessons.md.
- top_posts / by_dimension / themes_overview — СВЕРКА с данными Аналитика (что реально заходит:
  ER по формату/времени/теме). Прямое чтение общего слоя (PLAN §11 «данные, не суждение»).
- propose_standard / apply_standard — вывод/обновление стандарта постов через ГЕЙТ: предлагаешь в
  .proposed-файл, применяет владелец (с бэкапом). Живой стандарт молча не мутируешь.

Публикации тут нет намеренно: драфт — автомат, публикует владелец (см. PLAN §6, чек-лист безопасности).

ГРАНИЦА самообучения: уроки идут в СЛОЙ ПАМЯТИ (post_lessons.md), который грузится в контекст —
это безопасное «обучение из фидбэка». Личность (SKILL.md) Криейтор НЕ трогает: это определение
агента под гейтом Девелопера (PLAN §5.1 «не мутируем живого»). Устоявшийся урок Девелопер позже
поднимет в SKILL.md через propose→ок→apply.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from core import analytics, config

MEM = config.ROOT / "memory"
BRIEFS_DIR = MEM / "briefs"            # продукт Скаута — вход Криейтора
DRAFTS_DIR = MEM / "drafts"            # архив драфтов — выход Криейтора
LESSONS = MEM / "post_lessons.md"      # уроки из правок владельца (живое состояние)
PLAYBOOK = MEM / "format_playbook.md"  # плейбук форматов — ведёт Аналитик, читает Криейтор
STANDARD = MEM / "post_standard.md"    # живой стандарт постов (Telegram)
STANDARD_PROPOSED = MEM / "post_standard.proposed.md"  # предложение стандарта (gate: на одобрение)
HISTORY = MEM / ".history"             # бэкапы стандарта перед применением (откат)

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
    {
        "name": "list_drafts",
        "description": "Список ТВОИХ прошлых драфтов (memory/drafts/), свежие сверху. Нужен, чтобы найти "
                       "свой драфт под финал, который прислал владелец (для обучения на правке).",
        "input_schema": {
            "type": "object",
            "properties": {"n": {"type": "integer", "description": "сколько последних показать (по умолч. 8)"}},
        },
    },
    {
        "name": "read_draft",
        "description": "Прочитать ТВОЙ прошлый драфт — чтобы СРАВНИТЬ его с финальной версией, которую "
                       "владелец доредактировал и публикует. Из разницы извлекаешь уроки (record_lesson). "
                       "which: 'latest' (по умолч.) либо часть имени/даты/слага.",
        "input_schema": {
            "type": "object",
            "properties": {"which": {"type": "string", "description": "'latest' | часть имени/даты/слага"}},
        },
    },
    {
        "name": "record_lesson",
        "description": "Усвоить УРОК из правки владельца (петля обучения) — добавить в memory/post_lessons.md, "
                       "который грузится тебе в контекст к каждому посту. Записывай ТОЛЬКО устойчивые, "
                       "переносимые правила («владелец режет вступление до ~40 слов», «убирает слово X», "
                       "«добавляет личный кейс перед выводом»), не разовую косметику. Один вызов — один урок. "
                       "После записи отчитайся владельцу, что усвоил. Личность (SKILL.md) НЕ трогаешь — уроки "
                       "живут в памяти.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lesson": {"type": "string", "description": "устойчивое правило на будущее, одной фразой"},
                "evidence": {"type": "string", "description": "что в правке навело (коротко, необязательно)"},
            },
            "required": ["lesson"],
        },
    },
    {
        "name": "top_posts",
        "description": "Лучшие посты канала по метрике (данные Аналитика) — СВЕРКА с тем, что реально "
                       "заходит, и материал для вывода стандарта из практики. metric: er|forwards|"
                       "views|reactions|comments; content_type: 'Текст'|'Медиа' (необязательно).",
        "input_schema": {"type": "object", "properties": {
            "metric": {"type": "string"}, "n": {"type": "integer"},
            "content_type": {"type": "string"}}},
    },
    {
        "name": "by_dimension",
        "description": "Средние метрики в разрезе weekday|hour|type (текст/медиа) — данные Аналитика "
                       "о времени и формате. Для выбора формата под тему и для вывода стандарта.",
        "input_schema": {"type": "object", "properties": {
            "dim": {"type": "string", "description": "weekday | hour | type"}}, "required": ["dim"]},
    },
    {
        "name": "themes_overview",
        "description": "Темы канала со средними метриками — что исторически заходит (данные Аналитика). "
                       "Для выбора формата/угла и сверки.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "propose_standard",
        "description": "ПРЕДЛОЖИТЬ обновлённый стандарт постов платформы (gate: живой файл НЕ трогает). "
                       "Пишет в memory/post_standard.proposed.md на проверку владельцу. Сюда кладёшь "
                       "выведенный из топ-постов + плейбука редакторский стандарт (архетипы, структура, "
                       "ритм, ✅/❌). Применит владелец командой /apply_standard. platform по умолч. telegram.",
        "input_schema": {"type": "object", "properties": {
            "content": {"type": "string", "description": "полный предлагаемый стандарт (markdown)"},
            "platform": {"type": "string", "description": "telegram (по умолч.)"}}, "required": ["content"]},
    },
    {
        "name": "apply_standard",
        "description": "Применить предложенный стандарт: копирует post_standard.proposed.md в живой "
                       "post_standard.md с бэкапом старого в memory/.history/. Вызывай ТОЛЬКО по команде "
                       "владельца /apply_standard (его явное «ок»). Сам по себе, в /derive, не вызывай.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _md_files(d) -> list:
    if not d.exists():
        return []
    return sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:120]
    return "(пусто)"


def _list_md(d, label: str, empty: str, n: int = 8) -> str:
    files = _md_files(d)
    if not files:
        return empty
    out = [label]
    for p in files[:max(1, n)]:
        out.append(f"- {p.name} — {_first_heading(p.read_text(encoding='utf-8'))}")
    return "\n".join(out)


def _read_md(d, which: str, empty: str, not_found: str) -> str:
    files = _md_files(d)
    if not files:
        return empty
    q = (which or "latest").strip().lower()
    if q in ("", "latest", "последний", "свежий"):
        target = files[0]
    else:
        matches = [p for p in files if q in p.name.lower()]
        if not matches:
            avail = "\n".join(f"- {p.name}" for p in files[:8])
            return f"{not_found}\n{avail}"
        target = matches[0]  # самый свежий из совпавших (files уже отсортирован)
    text = target.read_text(encoding="utf-8")
    cap = 40000  # кап на контекст: файл большой, всё в одну сессию не тащим
    body = text[:cap] + ("\n\n… (обрезано)" if len(text) > cap else "")
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


def _record_lesson(args: dict) -> str:
    lesson = str(args.get("lesson", "") or "").strip()
    if not lesson:
        return "Пустой урок — нечего записывать."
    LESSONS.parent.mkdir(parents=True, exist_ok=True)
    if not LESSONS.exists():
        LESSONS.write_text(
            "# Уроки Криейтора из правок владельца\n\n"
            "> Живое состояние: устойчивые правила письма, извлечённые из того, как владелец\n"
            "> доредактирует посты перед публикацией. Грузится в контекст Криейтора к каждому посту.\n"
            "> Новое перекрывает старое; неудачный урок владелец удаляет руками. Личность (SKILL.md)\n"
            "> правит только Девелопер через гейт — устоявшийся урок поднимают туда отдельно.\n\n",
            encoding="utf-8", newline="\n")
    ev = str(args.get("evidence", "") or "").strip()
    line = f"- ({date.today().isoformat()}) {lesson}" + (f" — _из правки: {ev}_" if ev else "") + "\n"
    with open(LESSONS, "a", encoding="utf-8", newline="\n") as f:
        f.write(line)
    return ("Урок записан в memory/post_lessons.md — учту в следующих постах. "
            "Отчитайся владельцу одной строкой, что усвоил.")


def _propose_standard(args: dict) -> str:
    content = str(args.get("content", "") or "").strip()
    if not content:
        return "Пустой стандарт — нечего предлагать."
    STANDARD_PROPOSED.parent.mkdir(parents=True, exist_ok=True)
    STANDARD_PROPOSED.write_text(content, encoding="utf-8", newline="\n")
    return ("Предложение записано: memory/post_standard.proposed.md (живой стандарт НЕ тронут). "
            "Покажи владельцу суть изменений; одобрит — применит командой /apply_standard.")


def _apply_standard() -> str:
    # Гейт в коде: применяем ТОЛЬКО ранее предложенный .proposed-файл (не произвольный текст).
    if not STANDARD_PROPOSED.exists():
        return "Нет предложенного стандарта (post_standard.proposed.md). Сначала /derive."
    HISTORY.mkdir(parents=True, exist_ok=True)
    if STANDARD.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (HISTORY / f"post_standard-{stamp}.md").write_text(
            STANDARD.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    STANDARD.write_text(STANDARD_PROPOSED.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    STANDARD_PROPOSED.unlink()
    return ("Стандарт обновлён: memory/post_standard.md (старый — в memory/.history/ для отката). "
            "Предложение очищено.")


def dispatch(name: str, args: dict) -> str:
    if name == "list_briefs":
        return _list_md(BRIEFS_DIR, "Брифы Скаута (свежие сверху):",
                        "Брифов Скаута пока нет (memory/briefs/ пуст). Напиши из присланного "
                        "направления или попроси Скаута /scan.", int(args.get("n", 8)))
    if name == "read_brief":
        return _read_md(BRIEFS_DIR, args.get("which", "latest"),
                        "Брифов Скаута нет (memory/briefs/ пуст). Пиши из присланного направления "
                        "или попроси Скаута /scan.",
                        f"Бриф по запросу «{args.get('which', '')}» не найден. Доступны:")
    if name == "list_drafts":
        return _list_md(DRAFTS_DIR, "Твои драфты (свежие сверху):",
                        "Драфтов пока нет (memory/drafts/ пуст).", int(args.get("n", 8)))
    if name == "read_draft":
        return _read_md(DRAFTS_DIR, args.get("which", "latest"),
                        "Драфтов пока нет (memory/drafts/ пуст).",
                        f"Драфт по запросу «{args.get('which', '')}» не найден. Доступны:")
    if name == "find_posts":
        return analytics.find_posts(args["query"], int(args.get("n", 8)))
    if name == "by_theme":
        return analytics.by_theme(args["theme"])
    if name == "save_draft":
        return _save_draft(args)
    if name == "record_lesson":
        return _record_lesson(args)
    if name == "top_posts":
        return analytics.top_posts(args.get("metric", "er"),
                                   int(args.get("n", 10)), args.get("content_type", ""))
    if name == "by_dimension":
        return analytics.by_dimension(args.get("dim", "weekday"))
    if name == "themes_overview":
        return analytics.themes_overview()
    if name == "propose_standard":
        return _propose_standard(args)
    if name == "apply_standard":
        return _apply_standard()
    return f"Неизвестный инструмент: {name}"
