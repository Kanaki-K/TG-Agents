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
from pathlib import Path

from connectors.telegram_publish import publish
from core import analytics, analytics_tools, config, content_plan, market_tools

MEM = config.ROOT / "memory"
BRIEFS_DIR = MEM / "briefs"            # продукт Скаута — вход Криейтора
DRAFTS_DIR = MEM / "drafts"            # архив драфтов — выход Криейтора
LESSONS = MEM / "post_lessons.md"      # уроки из правок владельца (живое состояние)
PLAYBOOK = MEM / "format_playbook.md"  # плейбук форматов — ведёт Аналитик, читает Криейтор
STANDARD = MEM / "post_standard.md"    # живой стандарт постов (Telegram)
STANDARD_PROPOSED = MEM / "post_standard.proposed.md"  # предложение стандарта (gate: на одобрение)
HISTORY = MEM / ".history"             # бэкапы стандарта перед применением (откат)
IMAGE_PROMPT = MEM / "image_prompt.md"  # шаблон стиля обложки (канон визуала; правит владелец)
# Аутбокс картинок: make_image кладёт сюда путь к готовому PNG, рантайм после хода шлёт его
# фото в чат (инструмент сам фото слать не умеет — только текст). data/ = вне git.
MEDIA_OUTBOX = config.ROOT / "data" / "creator_pending_media.txt"
# Последняя обложка от make_image (персистентно, в отличие от аутбокса, который рантайм чистит каждый
# ход): её берёт publish_now, когда планирует пост в канал. data/ = вне git.
LAST_COVER = config.ROOT / "data" / "creator_last_cover.txt"
# Формат последнего сохранённого драфта (флагман/короткий/scope/…): его читает publish_now, чтобы
# НЕ угадывать формат по длине текста и не цеплять обложку к короткому посту. data/ = вне git.
LAST_KIND = config.ROOT / "data" / "creator_last_kind.txt"

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
        "name": "read_post",
        "description": "Прочитать ПОЛНЫЙ текст утверждённого поста канала по id — ЭТАЛОН для калибровки. "
                       "Перед флагманом прочти 1–2 эталона (мануал §4: #434 «Смена рук», #432 «17 лет», "
                       "#426 «Минус 90%», #422 «Недвижка/Биток») и СВЕРЬ свой драфт: плотность фактов на "
                       "знак, лаконичность без эссе-воды, голос, и что весь пост влезает в ОДНО сообщение "
                       "(≤4096). Текст НЕ обрезается (в отличие от recent_posts).",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "номер поста, напр. 434"}},
            "required": ["id"],
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
        "description": "Сохранить готовый драфт поста (memory/drafts/) + ПРОГНАТЬ КОД-ЛИНТЕР. Вызывай ОДИН "
                       "раз в конце, передав ПОЛНЫЙ текст и kind=формат (флагман/…). Линтер сам чинит "
                       "типографику (тире/кавычки) и возвращает: (1) предупреждения, что исправить вручную "
                       "(валюта перед числом, размер флагмана, футер, «является»); (2) ВЫЧИЩЕННУЮ версию "
                       "поста. Исправь предупреждения и выдай в чат ИМЕННО возвращённую версию (с правками). "
                       "Это драфт на правку: публикует владелец, не ты.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "полный текст драфта поста (markdown)"},
                "slug": {"type": "string", "description": "короткий ярлык темы, напр. 'ai-stablecoins' (необязательно)"},
                "kind": {"type": "string", "description": "формат для линтера/имени: флагман|обучающий|психология|личный|короткий|light"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "make_image",
        "description": "Сделать обложку к посту и прислать её владельцу. Вызывай ВСЕГДА, когда владелец "
                       "просит картинку/обложку к посту — в т.ч. «сделай обложку», «пришли пост с картинкой», "
                       "«картинку и пост вместе». Без этого вызова картинки в ответе НЕ будет (бот не помнит "
                       "прошлые). Рендер идёт через бёрнер ChatGPT (веб, «руки»). "
                       "Вызывай ОДИН раз, когда чистый текст драфта готов. Передай title (заголовок поста ТОЧНО "
                       "как в посте) и post_text (полный финальный текст). Промпт по стилю канала соберётся сам "
                       "из шаблона (memory/image_prompt.md) — сам стиль НЕ пиши. Картинка уйдёт владельцу в чат "
                       "отдельным фото. Это «руки», связь живая не всегда: если ChatGPT недоступен/сессия "
                       "протухла/лимит — инструмент вернёт ПОНЯТНУЮ причину и что владельцу сделать; тогда "
                       "проговори это ДОСЛОВНО и ВСЁ РАВНО выдай текст поста — картинка бонус, не блокер.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "заголовок поста ТОЧНО как в тексте (язык/орфографию не меняй)"},
                "post_text": {"type": "string", "description": "полный финальный текст поста (по нему ГПТ выбирает метафору)"},
                "palette": {"type": "string", "description": "палитра (необязательно): нейтральная|светлая|тёплая золотая|тёмная. "
                                                             "Пусто = нейтральная по умолчанию. Указывай, только если владелец попросил."},
            },
            "required": ["title", "post_text"],
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
                       "ПЕРЕД записью СВЕРЬСЯ С КОНТЕКСТОМ (мануал §0–§11 и сами post_lessons у тебя перед "
                       "глазами): если правило УЖЕ есть в мануале/линтере или среди уроков — НЕ дублируй "
                       "(код-страж развернёт near-дубль). Пиши, только если это НОВОЕ правило или уточнение — "
                       "тогда сформулируй, ЧЕМ оно отличается. После записи отчитайся владельцу, что усвоил. "
                       "Личность (SKILL.md) НЕ трогаешь — уроки живут в памяти.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lesson": {"type": "string", "description": "устойчивое правило на будущее, одной фразой"},
                "evidence": {"type": "string", "description": "что в правке навело (коротко, необязательно)"},
                "confirm_new": {"type": "boolean", "description": "true — подтверждаю, что это НОВОЕ правило "
                                "(не дубль мануала/уроков); ставить только после страж-предупреждения о дубле"},
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
        "name": "recent_posts",
        "description": "Последние N постов (что читатели видели недавно) — заголовок + начало/конец текста. "
                       "СВЕРКА СВЕЖЕСТИ ПРИЁМОВ (анти-самоповтор): перед сдачей проверь, что твой заголовок, "
                       "тип хука, главная мысль-антитеза и закрывающий вопрос НЕ повторяют последние ~5 "
                       "постов по смыслу. Окно скользящее (~5), не весь канал. post_format — сверять внутри "
                       "формата (напр. последние флагманы).",
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "description": "сколько последних (по умолч. 5)"},
                "post_format": {"type": "string", "description": "сверять внутри формата (необязательно)"},
            },
        },
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
    market_tools.PRICE_TOOL,   # market_price — точный спот для сверки живых цен (см. шаг 3.5 /post)
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


# Набор кастом-эмодзи (data/custom_emoji.json): заголовки берут эмодзи ТОЛЬКО отсюда, иначе Telegram
# рендерит обычный эмодзи вместо кастомного. Нормализуем (снимаем variation-selector/ZWJ/тон кожи).
_EMOJI_VS = re.compile(r"[️‍\U0001F3FB-\U0001F3FF]")
_EMOJI_LEAD = re.compile(
    r"^([©®™ℹ←-⇿⌀-➿⬀-⯿"
    r"️‍\U0001F000-\U0001FAFF\U0001F3FB-\U0001F3FF]+)")
_allowed_emoji_cache: set | None = None


def _emoji_norm(s: str) -> str:
    return _EMOJI_VS.sub("", s)


def _allowed_emoji() -> set:
    global _allowed_emoji_cache
    if _allowed_emoji_cache is None:
        try:
            import json
            data = json.loads((config.ROOT / "data" / "custom_emoji.json").read_text(encoding="utf-8"))
            _allowed_emoji_cache = {_emoji_norm(k) for k in data}
        except Exception:
            _allowed_emoji_cache = set()
    return _allowed_emoji_cache


def _lint(content: str, kind: str = "") -> tuple:
    """Код-гейт типографики/размера (детерминированно, не на доверии к модели).

    Авто-чинит механику (тире/кавычки к канону мануала §5). Возвращает (чистый_текст, список
    предупреждений) для того, что нельзя править вслепую (валюта, размер, футер, «является»).
    """
    clean = content or ""
    # Разметка цитат веб-поиска (<cite index="1-4">…</cite>) протекает в текст у слабых моделей —
    # срезаем теги, сохраняя содержимое (это служебная аннотация поиска, не часть поста).
    clean = re.sub(r"</?cite[^>]*>", "", clean)
    for d in ("—", "–", "―"):          # длинные тире → обычный дефис
        clean = clean.replace(d, "-")
    for q in ("«", "»", "“", "”", "„", "‟"):  # ёлочки/фигурные кавычки → прямые
        clean = clean.replace(q, '"')
    # Заголовок поста (1-я непустая строка) ДОЛЖЕН быть жирным (§5). Модель регулярно забывает разметку
    # (см. §5-детектор ниже) — чиним ДЕТЕРМИНИРОВАННО, а не только предупреждаем: короткую титульную
    # строку без ** оборачиваем в **…** (эмодзи-якорь остаётся ВНУТРИ жирного, как в эталонах канала).
    # 'light' (Ф3, чистый текст) пропускаем — у него заголовка-строки может не быть, а длинную (>80
    # знаков) первую строку не трогаем (это не заголовок, а абзац-хук).
    if "light" not in (kind or "").lower():
        _ls = clean.split("\n")
        for _i, _ln in enumerate(_ls):
            if not _ln.strip():
                continue
            _vis = re.sub(r"^[^\wА-Яа-яЁё]+", "", _ln.replace("**", "")).strip()
            if "**" not in _ln and 0 < len(_vis) <= 80:
                _ind = _ln[:len(_ln) - len(_ln.lstrip())]
                _ls[_i] = f"{_ind}**{_ln.strip()}**"
            break
        clean = "\n".join(_ls)
    warns = []
    cur = len(re.findall(r"\$\s?\d", clean))
    if cur:
        warns.append(f"валюта ПЕРЕД числом — {cur} шт (нужно ПОСЛЕ: 73 млн$, не $73 млн)")
    yav = len(re.findall(r"явля[ею]", clean, re.IGNORECASE))
    if yav:
        warns.append(f"«является/являются» — {yav} шт (убрать, §7)")
    # Англицизмы-маркеры «писала ИИшка» — авто-warn (высокий сигнал, мало ложных; §7)
    angl = {"фрейм": "каркас/рамка", "юзер": "пользователь", "сетап": "расклад",
            "кейс": "пример/случай", "b2b": "между компаниями"}  # «хайп» — фирменное, не трогаем
    found_angl = [f"«{w}»→{repl}" for w, repl in angl.items()
                  if re.search(rf"\b{re.escape(w)}", clean, re.IGNORECASE)]
    if found_angl:
        warns.append("англицизмы (§7): " + ", ".join(found_angl))
    # Стаккато-триады (manufactured staccato drama, §11.5): 3+ УТВЕРДИТЕЛЬНЫХ обрубка ≤3 слов подряд =
    # след ИИ-редактора. Считаем только фрагменты НА ТОЧКЕ (вопросы-списки «Монополия LINK?» — приём, не
    # сюда) и делим по пунктуация+пробел, чтобы НЕ резать десятичные «0.31$».
    run = mx = 0
    for s in re.split(r"(?<=[.!?])\s+", clean):
        s = s.strip()
        if s.endswith(".") and len(re.sub(r"[^\w\s]", " ", s).split()) <= 3:
            run += 1
            mx = max(mx, run)
        else:
            run = 0
    if mx >= 3:
        warns.append(f"стаккато-ритм: {mx} обрубка-утверждения ≤3 слов подряд (ИИ-подача, §11.5) — "
                     f"слей в живую фразу")
    # «Это не X. Это Y» — ИИ-пул-квота (§11.5, владелец требует убирать насовсем). Ловим парную форму.
    eto = re.findall(r"Это не [^.!?\n]{1,60}[.!?]+\s+Это\b", clean)
    if eto:
        warns.append(f"«Это не X. Это Y» — {len(eto)} шт (ИИ-пул-квота §11.5, скажи Y прямо с фактом)")
    # --- AI-ритм: детерминированные детекторы (модель СЛЕПА к своему стаккато — ловим КОДОМ, не доверием) ---
    low = clean.lower()
    # Передоз антитезы «не X, а Y» (и обратной «X, а не Y»): ОДНА центральная ок, 3+ = ИИ-ритм (§11.10).
    anti = (len(re.findall(r"\bне\s+[^,.!?\n]{1,45},\s*а\s+", low))
            + len(re.findall(r",\s*а\s+не\s+\w", low)))
    if anti >= 3:
        warns.append(f"передоз антитезы «не X, а Y» — ~{anti} шт: оставь МАКС 1 центральную (в 💡), "
                     f"остальные перепиши ПРЯМЫМ утверждением (§11.5)")
    # Триплет-двойное отрицание «не А, не Б …» (типа «не торговал, не спекулировал») — ИИ-симметрия (§11.10).
    dbl = re.findall(r"\bне\s+\w+[^.!?\n]{0,30},\s*не\s+\w+", low)
    if dbl:
        warns.append(f"триплет «не А, не Б — В» — {len(dbl)} шт: один сильный образ, не три параллельных (§11.5)")
    # Фразы-анонсы важности — не объявляй словами, покажи позицией/жирным (урок 22.06).
    announce = [p for p in ("вот это и есть", "важно другое", "а теперь главное", "вот в чём",
                            "самое интересное", "вот что важно") if p in low]
    if announce:
        warns.append("фраза-анонс важности (резать): " + ", ".join(f"«{p}»" for p in announce))
    # Бан-клише заголовков (вечный бан + анти-самоповтор флагманов).
    if "розов" in low and "очк" in low:
        warns.append("БАН-фраза «розовые очки» (клише+самоповтор) — назови раздел по СУТИ блока")
    # Недоказуемые суперлативы — слабые слова (урок 22.06).
    sup = re.findall(r"сам[ыио]\w*\b[^.!?\n]{0,40}\bв мире|крупнейш\w+|перв\w+ в истории|беспрецедент\w*", low)
    if sup:
        warns.append(f"недоказуемый суперлатив — {len(sup)} шт («самые…в мире»/«крупнейший»/«первый в "
                     f"истории»): смягчи или убери")
    # «хедж» как англицизм-страховка (но «хедж-фонд» как организация — оставляем).
    if re.search(r"\bхедж(?![- ]?фонд)", low):
        warns.append("«хедж» → «страховка» (англицизм §7; «хедж-фонд» как организацию — оставь)")
    # --- Заголовок (1-я непустая строка): олицетворение неживого + длина (учим на реальных заголовках) ---
    head = next((s.strip() for s in clean.split("\n") if s.strip()), "")
    if re.search(r"\b(что|как|кого|чего|куда|зачем)\s+(увид|поня|реши|дума|почувств|захот|боит|смотр)\w+"
                 r"\s+(?:[^\s]+\s+){0,2}(пенси\w+|фонд\w*|рынок|рынк\w+|экономик\w+|биткоин\w*|доллар\w*|капитал\w*)\b",
                 head, re.IGNORECASE):
        warns.append("заголовок: олицетворение неживого («что увидела пенсия/фонд» — предметы не видят/думают) "
                     "— переформулируй от живого субъекта или утверждением")
    hvis = re.sub(r"^[^\wА-Яа-яЁё]+", "", head.replace("*", "")).strip()  # без ведущих эмодзи и жирного
    if len(hvis) > 80:
        warns.append(f"заголовок длинный (~{len(hvis)}зн): сильные заголовки канала короткие (~4–9 слов) — подожми")
    # Заголовок поста ДОЛЖЕН быть жирным (§5: все заголовки/подзаголовки жирные).
    if head and "**" not in head:
        warns.append("заголовок поста НЕ жирный — оберни в **…** (ВСЕ заголовки и подзаголовки жирные, §5)")
    # Ссылки/бренд-домены в ТЕЛЕ (кроме футера) — запрещены (в тексте ссылок нет, только футер).
    _footmark = ("🖥", "▶️", "🥸", "📱", "t.me/", "linktr", "notion.so")
    body_nf = "\n".join(ln for ln in clean.split("\n") if not any(m in ln for m in _footmark))
    if re.search(r"https?://", body_nf):
        warns.append("ссылка (http) в ТЕЛЕ поста — в тексте ссылок НЕ ставим, только в футере")
    dom = re.findall(r"\b[\w-]+\.(?:com|io|org|net|app|xyz|finance|exchange)\b", body_nf, re.IGNORECASE)
    if dom:
        warns.append(f"бренд-домен в теле — {dom[:3]}: Telegram авто-линкует в ссылку (в тело ссылок нельзя) — "
                     f"переформулируй (напр. «биржа Crypto…»)")
    # Эмодзи ЗАГОЛОВКОВ — ТОЛЬКО из набора (data/custom_emoji.json): чужой (🤖) рендерится обычным, не кастом.
    allowed = _allowed_emoji()
    if allowed:
        bad = []
        for ln in clean.split("\n"):
            mm = _EMOJI_LEAD.match(ln.replace("**", "").lstrip())
            if mm:
                lead = _emoji_norm(mm.group(1))
                if lead and lead not in allowed and lead not in bad:
                    bad.append(lead)
        if bad:
            warns.append("эмодзи-заголовок НЕ из набора (рендерится обычным, не кастом): "
                         + " ".join(bad) + " — возьми из data/custom_emoji.json (93 шт)")
    # Якорный жирный (§5): плотность 10–15%. Считаем долю символов внутри **…** от видимого текста.
    # >18% = «выделил слишком много» (жирное обесценивается); <4% или <2 выделений = «жирного НЕТ»
    # (пост не сканируется — частый промах: модель забывает разметку, хотя §5 этого требует).
    k = (kind or "").lower()
    bold_spans = re.findall(r"\*\*(.+?)\*\*", clean, re.DOTALL)
    bold_chars = sum(len(b) for b in bold_spans)
    vis = len(clean.replace("**", "")) or 1
    dens = bold_chars / vis
    if dens > 0.18:
        warns.append(f"жирного слишком много: ~{round(100 * dens)}% текста (норма 10–15%, §5) — "
                     f"сними лишнее (skim-тест: только несущие слова), иначе жирное перестаёт работать")
    elif "light" not in k and (dens < 0.04 or len(bold_spans) < 2):
        warns.append("НЕТ якорного жирного (§5): размечай через **…** ЗАГОЛОВКИ-разделы и несущие слова "
                     "(имена, ключевые цифры, повороты, развязку) — плотность 10–15%, skim-слой. Сейчас "
                     "пост не сканируется (это обязательный приём, а не опция)")
    if "флагман" in k or "flagman" in k:
        n = len(clean.encode("utf-16-le")) // 2  # точный счёт Telegram (UTF-16 units = лимит 4096), не байты
        if n < 2800:
            warns.append(f"флагман КОРОТКИЙ: {n} знаков (норма 2800–4096) — добери плотности фактов")
        elif n > 4096:
            warns.append(f"⛔ флагман НЕ ВЛЕЗАЕТ в одно сообщение Telegram: {n} знаков > 4096 — "
                         f"режь до ≤4096 (Telegram порвёт на 2 сообщения, хвост читается как «дописала ИИ»)")
        elif n > 3900:
            warns.append(f"флагман у СТЕНЫ: {n} знаков (лимит 4096, идеал 3000–3800) — подожми, "
                         f"оставь запас под футер")
        if "notion" not in clean.lower() and "🖥" not in clean:
            warns.append("нет футера (🖥 Медиа | 🥸 Мемы | 📱 Notion)")
    if "scope" in k or "коротк" in k:
        n = len(clean.encode("utf-16-le")) // 2
        if n > 1000:
            warns.append(f"⛔ scope РАЗДУЛСЯ: {n} знаков — это недофлагман. Норма ~400–900 (потолок 1000): "
                         f"оставь триггер → суть/цифры → угол долгосрочнику → честный риск, всё лишнее режь")
        if "💭" in clean or "Вопрос к Вам" in clean:
            warns.append("scope: УБЕРИ флагман-закрытие 💭 «Вопрос к Вам» — в коротком финал это обычная "
                         "строка-вывод, а не отдельный раздел-вопрос")
        if "💡" in clean:
            warns.append("scope: УБЕРИ 💡-раздел с афоризмом (флагман-фурнитура) — встрой мысль в текст "
                         "обычным предложением")
    return clean, warns


def _save_draft(args: dict) -> str:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    kind = str(args.get("kind", "") or "").strip().lower()
    clean, warns = _lint(args.get("content", ""), kind)
    base = "-".join(x for x in (args.get("slug", "") or "post", kind) if x)
    slug = re.sub(r"[^a-z0-9-]+", "-", base.lower()).strip("-") or "post"
    fname = f"{date.today().isoformat()}-{slug}.md"
    (DRAFTS_DIR / fname).write_text(clean, encoding="utf-8", newline="\n")
    try:  # запоминаем формат — publish_now возьмёт его, а не будет гадать по длине текста
        LAST_KIND.parent.mkdir(parents=True, exist_ok=True)
        LAST_KIND.write_text(kind, encoding="utf-8")
    except Exception:
        pass
    msg = f"Драфт сохранён: memory/drafts/{fname}. Типографику привёл к канону (тире/кавычки)."
    if warns:
        msg += " ⚠ ИСПРАВЬ перед выдачей: " + "; ".join(warns) + "."
    else:
        msg += " Линтер чистый."
    msg += ("\n\n--- ВЫДАЙ В ЧАТ ИМЕННО ЭТУ ВЕРСИЮ (с учётом правок выше; это драфт, публикует владелец) ---\n"
            + clean)
    return msg


_DEFAULT_IMAGE_PROMPT = (  # запасной шаблон, если memory/image_prompt.md вдруг удалили
    "Ты — арт-директор Telegram-канала про крипту и финансы. Сгенерируй ОДНО изображение-"
    "обложку к посту ниже: горизонтальный баннер 3:2, кинематографичный 3D-рендер, тёмный "
    "полночно-синий фон + золотое свечение. Заголовок строго сверху по центру, крупный жирный, "
    "ТОЧНО как дан; кроме заголовка — НИКАКОГО текста/цифр/логотипов.\n\n"
    "ЗАГОЛОВОК: [ВСТАВЬ ЗАГОЛОВОК]\nТЕКСТ ПОСТА: [ВСТАВЬ ТЕКСТ ПОСТА]"
)


# Эмодзи/декоративные символы и пиктограммы — на баннере не нужны (правило владельца). Чистим
# заголовок ПЕРЕД подстановкой, чтобы ChatGPT не вывел свечку/стрелки в тексте обложки.
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "←-⇿⬀-⯿⌀-⏿️‍]+"
)


def _clean_title(title: str) -> str:
    """Заголовок для обложки: без эмодзи и ведущих/висячих разделителей (- – — • |)."""
    return _EMOJI.sub("", title).strip(" -–—•|").strip()


def _build_image_prompt(title: str, post_text: str, palette: str = "") -> str:
    """Собрать промпт картинки: шаблон стиля (memory/image_prompt.md) + заголовок, текст, палитра.

    palette необязательна: пусто → шаблон сам берёт НЕЙТРАЛЬНУЮ по умолчанию.
    """
    try:
        tpl = IMAGE_PROMPT.read_text(encoding="utf-8") if IMAGE_PROMPT.exists() else _DEFAULT_IMAGE_PROMPT
    except Exception:
        tpl = _DEFAULT_IMAGE_PROMPT
    title = _clean_title(title)  # эмодзи в заголовке баннера не нужны
    if "[ВСТАВЬ ЗАГОЛОВОК]" in tpl or "[ВСТАВЬ ТЕКСТ ПОСТА]" in tpl:
        out = (tpl.replace("[ВСТАВЬ ЗАГОЛОВОК]", title)
                  .replace("[ВСТАВЬ ТЕКСТ ПОСТА]", post_text))
    else:
        out = f"{tpl}\n\nЗАГОЛОВОК: {title}\nТЕКСТ ПОСТА: {post_text}"  # плейсхолдеров нет — добавим явно
    palette = (palette or "").strip()
    if palette:  # явный выбор владельца перекрывает строку ПАЛИТРА в шаблоне
        out = re.sub(r"(?m)^ПАЛИТРА:.*$", f"ПАЛИТРА: {palette}", out, count=1)
    return out


def _make_image(args: dict) -> str:
    """Сгенерировать обложку через бёрнер ChatGPT и положить в аутбокс (рантайм отправит фото).

    МЯГКАЯ ДЕГРАДАЦИЯ: при любом отказе связи возвращаем понятную причину + что владельцу
    сделать, и велим всё равно отдать текст поста — картинка бонус, не блокер.
    Блокирующий вызов (браузер) безопасен: dispatch крутится в рабочем потоке (agent_runtime:
    llm.reply под asyncio.to_thread), event-loop бота не морозим.
    """
    title = str(args.get("title", "") or "").strip()
    post_text = str(args.get("post_text", "") or "").strip()
    if not title or not post_text:
        return "Для обложки нужны и заголовок (title), и полный текст поста (post_text)."
    prompt = _build_image_prompt(title, post_text, str(args.get("palette", "") or ""))
    try:
        from connectors.gpt_image import generate as gpt_image
    except Exception as e:  # коннектор/зависимости не на месте — не валим пост
        return (f"⚠️ Картинку не сделал: коннектор ChatGPT недоступен ({e}). "
                "Выдай владельцу текст поста без обложки.")
    try:
        path = gpt_image.generate(prompt)
    except RuntimeError as e:
        # generate() бросает понятные русские причины: нет сессии / протухла / лимит / сменилась вёрстка
        return ("⚠️ Обложку сделать не вышло — связь с ChatGPT-бёрнером не сработала.\n"
                f"Причина: {e}\n"
                "Проговори это владельцу ДОСЛОВНО и ВСЁ РАВНО выдай текст поста (картинка — бонус). "
                "Если нужно перелогиниться, владелец делает у себя: python -m connectors.gpt_image.login")
    except Exception as e:  # неожиданный сбой (краш браузера, сеть) — тоже не валим пост
        return (f"⚠️ Обложку сделать не вышло — неожиданный сбой связи с ChatGPT ({e}).\n"
                "Выдай владельцу текст поста без обложки. При повторе пусть проверит вход: "
                "python -m connectors.gpt_image.login check")
    try:  # кладём путь в аутбокс — рантайм отправит фото в чат после этого хода
        MEDIA_OUTBOX.parent.mkdir(parents=True, exist_ok=True)
        with open(MEDIA_OUTBOX, "a", encoding="utf-8") as f:
            f.write(str(path) + "\n")
        LAST_COVER.write_text(str(path), encoding="utf-8")  # персистентно — для publish_now (/schedule)
    except Exception:
        return (f"✅ Обложка готова ({path}), но не смог поставить её в очередь отправки. "
                "Скажи владельцу — файл лежит в data/gpt_images/.")
    return (
        "✅ Обложка готова — СИСТЕМА сама отправит её картинкой ПЕРЕД твоим сообщением.\n"
        "Выведи финальный пост, готовый к публикации. Формат вывода СТРОГО такой:\n"
        "• ПЕРВАЯ строка ответа = ПЕРВАЯ строка ПОСТА. НИКАКОЙ преамбулы («Готово», «Финальная версия», "
        "«Поправил линтер…») и упоминания картинки — её шлёт система;\n"
        "• мелкие правки (типографика, канон-футер) внеси МОЛЧА прямо в текст; пост не повторяй;\n"
        "• ПОСЛЕ поста — отдельная строка `[[SPLIT]]`, затем ОТДЕЛЬНЫМ сообщением КОРОТКАЯ заметка для "
        "проверки КАЧЕСТВА (это владельцу нужно): формат (почему, 1 строка) + что проверить перед "
        "публикацией (факты/цифры под вопросом, [ПРОВЕРИТЬ], если есть). Без баллов X/10, без советов, "
        "без вопросов.\n"
        "Итог: пост (картинка выше) + `[[SPLIT]]` + короткая заметка качества. Больше ничего."
    )


_LESSON_STOP = set("это что как уже его её для так но или из от до при над под чтобы перед "
                   "если когда чем тоже надо нужно есть быть всё все вот этот эта эти том".split())


def _lesson_keywords(s: str) -> set:
    """Значимые слова урока (для сверки на дубль): без хвоста-эвиденса, стоп-слов и коротышей."""
    s = re.sub(r"—\s*_из правки.*$|—\s*_.*_$", "", s.lower())   # отрезать эвиденс/курсив-хвост
    s = re.sub(r"^\-?\s*\(\d{4}-\d\d-\d\d\)\s*", "", s)          # отрезать дату-префикс строки
    return {w for w in re.findall(r"[а-яёa-z0-9]{4,}", s) if w not in _LESSON_STOP}


def _lesson_duplicate(new: str) -> str | None:
    """Near-дубль среди уже записанных уроков? Вернёт похожую строку или None.
    Сверяем по доле общих значимых слов (Жаккар к новому уроку); порог 0.6."""
    nw = _lesson_keywords(new)
    if len(nw) < 3 or not LESSONS.exists():
        return None
    for ln in LESSONS.read_text(encoding="utf-8").splitlines():
        if not ln.lstrip().startswith("- ("):
            continue
        ow = _lesson_keywords(ln)
        if ow and len(nw & ow) / len(nw) >= 0.6:
            return ln.strip()
    return None


def _record_lesson(args: dict) -> str:
    lesson = str(args.get("lesson", "") or "").strip()
    if not lesson:
        return "Пустой урок — нечего записывать."
    dup = _lesson_duplicate(lesson)
    if dup and not args.get("confirm_new"):
        return ("⚠ Похоже на ДУБЛЬ уже записанного урока:\n  " + dup + "\n\n"
                "Если это ТО ЖЕ правило — НЕ дублируй (оно уже есть; правило, которое уже в "
                "мануале/линтере, в post_lessons тоже не нужно). Если урок правда НОВЫЙ или "
                "уточняет старый — переформулируй так, чтобы было видно ЧЕМ отличается, и вызови "
                "снова с confirm_new=true.")
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


def _publish_now(args: dict | None = None) -> str:
    """Поставить ПОСЛЕДНИЙ готовый пост (последний драфт + обложка) в отложенные канала на слот
    контент-плана и уведомить мейн владельца. Детерминированно: текст берётся ДОСЛОВНО из сохранённого
    драфта, не переписывается. Формат берём из сохранённого kind драфта (или явного args['kind']), НЕ
    угадываем по длине. Обложку цепляем ТОЛЬКО флагману — короткий/scope уходит ТЕКСТОМ. /schedule."""
    args = args or {}
    channel = config.get_optional("PUBLISH_CHANNEL")
    if not channel:
        return "PUBLISH_CHANNEL не задан в .env — некуда планировать."
    drafts = _md_files(DRAFTS_DIR)
    if not drafts:
        return "Нет сохранённого драфта (memory/drafts/ пуст) — сначала напиши пост (/post)."
    text = drafts[0].read_text(encoding="utf-8").strip()
    if not text:
        return "Последний драфт пустой — нечего планировать."
    # Формат: явный аргумент → сохранённый kind драфта → фолбэк-эвристика по длине.
    raw = str(args.get("kind", "") or "").strip().lower()
    if not raw and LAST_KIND.exists():
        raw = LAST_KIND.read_text(encoding="utf-8").strip().lower()
    if raw:
        kind = "flagship" if any(s in raw for s in ("флагман", "flagman", "flagship")) else "short"
    else:
        kind = content_plan.infer_kind(text)
    # Обложка — ТОЛЬКО для флагмана. Короткий/scope = текст-онли, даже если LAST_COVER от прошлого
    # флагмана висит в data/ (иначе короткий пост уйдёт с чужой картинкой «из сохранёнок»).
    # И для флагмана обложка должна принадлежать ИМЕННО этому драфту: cover не старше драфта. Иначе
    # make_image в этом прогоне упал/не вызывался, LAST_COVER хранит картинку ПРОШЛОГО флагмана —
    # лучше уйти ТЕКСТОМ (владелец увидит в «Отложенных» и перегенерит), чем прицепить чужую обложку.
    cover = ""
    cover_note = ""
    if kind == "flagship":
        c = LAST_COVER.read_text(encoding="utf-8").strip() if LAST_COVER.exists() else ""
        if c and Path(c).exists() and LAST_COVER.stat().st_mtime + 2 >= drafts[0].stat().st_mtime:
            cover = c
        else:
            cover_note = (" ⚠️ Обложку НЕ прицепил: актуальной картинки для ЭТОГО поста нет "
                          "(make_image не сработал в этом прогоне / LAST_COVER от прошлого флагмана). "
                          "Флагман ушёл ТЕКСТОМ — сгенерь обложку и поставь заново, если нужна.")
    try:
        busy = {dt.astimezone(content_plan.tz()).date() for dt in publish.scheduled_times(channel)}
    except Exception:
        busy = set()
    slot = content_plan.next_slot(kind, busy_dates=busy)
    res = publish.publish(channel, text, cover or None, slot)
    if not res.get("ok"):
        return f"❌ Не поставил в отложенные: {res.get('error', '?')}. Драфт цел — поправь причину и снова /schedule."
    when = content_plan.human(slot)
    note = ""
    target = config.get_optional("PUBLISH_NOTIFY")
    if target:
        n = publish.notify(target, f"✅ Пост запланирован в канал на {when} "
                                   f"({content_plan.kind_label(kind)}). Проверь в «Отложенных» канала.")
        note = " Уведомил мейн владельца." if n.get("ok") else f" (уведомление на мейн не ушло: {n.get('error', '?')})"
    # ПРОВЕРКА: читаем отложенные обратно — подтвердить, что пост реально лёг (а не «ok» вхолостую).
    try:
        n_sched = len(publish.scheduled_times(channel))
        check = f" Проверка: в «Отложенных» канала сейчас {n_sched} сообщ."
    except Exception:
        check = " (проверку отложенных сделать не вышло)"
    return (f"✅ Поставил в отложенные канала: {content_plan.kind_label(kind)} на {when} "
            f"(режим: {res.get('mode', '?')}).{note}{check}{cover_note}\n"
            f"Сообщи владельцу слот; проверить/поправить/отменить — в нативных «Отложенных» канала.")


def dispatch(name: str, args: dict) -> str:
    shared = analytics_tools.handle(name, args)  # общие read-only аналитич. инструменты (дедуп)
    if shared is not None:
        return shared
    priced = market_tools.handle(name, args)     # живая цена (market_price) — общий ценовой бэкенд
    if priced is not None:
        return priced
    if name == "publish_now":
        return _publish_now(args)
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
    if name == "read_post":
        return analytics.read_post(int(args["id"]))
    if name == "save_draft":
        return _save_draft(args)
    if name == "make_image":
        return _make_image(args)
    if name == "record_lesson":
        return _record_lesson(args)
    if name == "top_posts":
        return analytics.top_posts(args.get("metric", "er"),
                                   int(args.get("n", 10)), args.get("content_type", ""))
    if name == "propose_standard":
        return _propose_standard(args)
    if name == "apply_standard":
        return _apply_standard()
    return f"Неизвестный инструмент: {name}"
