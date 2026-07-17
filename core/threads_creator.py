"""🧵 Мини-флагман (Threads) — дистилляция вышедшего ТГ-флагмана в 1–4 нативных поста.

ОТДЕЛЬНАЯ ветка (как scope отделён от флагмана): свой лёгкий контекст (threads_manual + эталоны
голоса), своя модель, БЕЗ Скаута / web_search / 2FA / GPT-обложки.

Почему без 2FA: факты берутся из УЖЕ вышедшего флагмана — он прошёл фактчек при своей публикации.
Дистилляция не вводит новых цифр, поэтому заново не верифицируем (дёшево + не тянем флагман-обвязку).
Медиа опционально: в Фазе 1 владелец ставит серию в отложку Threads руками и картинку цепляет сам.

Вход — последняя запись `core.flagship_journal` (журнал вышедших флагманов). Выход — текст серии:
посты, разделённые строкой POST_SEP. Изоляция: свои драфты в memory/threads_drafts/ (ТГ-публикатор
их НЕ видит — не перепутает с флагман/scope-драфтом).
"""
import logging
import re
from datetime import date

from core import config, cost, flagship_journal, llm, runmode, threads_distill_journal

AGENT_NAME = "creator"                    # голос автора тот же — переиспользуем персону Криейтера
THREADS_MODEL = "claude-sonnet-4-6"       # короткий формат — Opus избыточен (как у scope); /test → Haiku
THREADS_THINKING = None                   # короткому дистилляту глубокое мышление не нужно (дёшево)

THREADS_DRAFTS_DIR = config.ROOT / "memory" / "threads_drafts"  # ОТДЕЛЬНО от ТГ-драфтов (изоляция)
THREADS_LESSONS = config.ROOT / "memory" / "threads_lessons.md"  # уроки из правок владельца (петля)
POST_SEP = "[[POST]]"                      # разделитель постов серии в выводе модели


def _read(rel: str) -> str:
    p = config.ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _system() -> str:
    """Лёгкий контекст мини-флагмана: персона + Threads-мануал + эталоны голоса + красные линии бренда.
    БЕЗ флагман-мануала (content_manual), БЕЗ scope-мануала, БЕЗ voice_core — у Threads СВОЙ голос,
    он переносится с эталонов (threads_flagman_anchors), а не с ТГ-мозгов. Изоляция форматов."""
    persona = config.load_agent(AGENT_NAME)["persona"]
    anchors = _read("memory/threads_flagman_anchors.md") or "(эталонов пока нет — держись мануала)"
    lessons = _read("memory/threads_lessons.md") or "(пока пусто — учусь на твоих правках Threads-серий)"
    ctx = (
        "## 🧵 ТЫ ДЕЛАЕШЬ МИНИ-ФЛАГМАН ДЛЯ THREADS\n"
        "ОТДЕЛЬНЫЙ формат. Правила ТГ-флагмана (антитеза на весь пост, 2800–4096 знаков, разделы 💡/💭, "
        "обложка) и 🔭-скоупа к тебе НЕ применяются. Ты берёшь УЖЕ ВЫШЕДШИЙ ТГ-флагман и дистиллируешь "
        "его в 1–4 самостоятельных Threads-поста. Не репост и не пересказ — новая нарезка под площадку.\n\n"
        "## 📕 МАНУАЛ МИНИ-ФЛАГМАНА (правила механики) — следуй строго (memory/threads_manual.md)\n"
        f"{_read('memory/threads_manual.md')}\n\n"
        "## 🎯 ЭТАЛОНЫ ГОЛОСА И НАРЕЗКИ — режь В ЭТОМ голосе (memory/threads_flagman_anchors.md)\n"
        "Полный текст дистилляций владельца. Голос и приём нарезки переноси ОТСЮДА (как флагман с "
        "anchor_posts): payoff первой строкой, строки-биты, регистр «ты», лишнее за борт.\n"
        f"{anchors}\n\n"
        "## Канон бренда — аудитория и КРАСНЫЕ ЛИНИИ (memory/brand.md)\n"
        "Соблюдай красные линии: BTC не проигравший, без политоты/России/торговых сигналов.\n"
        f"{_read('memory/brand.md')}\n\n"
        "## Уроки из ТВОИХ правок Threads-серий — ПРИМЕНЯЙ (memory/threads_lessons.md)\n"
        f"{lessons}\n"
    )
    return llm.build_system(persona, ctx)


TASK = (
    "Сделай МИНИ-ФЛАГМАН для Threads из вышедшего ТГ-флагмана (ниже). СТРОГО по мануалу "
    "(memory/threads_manual.md в контексте — там ПОЛНАЯ логика отбора) и эталонам голоса. Главное:\n"
    "— НЕ «нарезать», а НАЙТИ то, что живёт само. Тест каждого кандидата: «если человек прочитает "
    "ТОЛЬКО это и больше ничего не знает — получит ли законченную мысль?». Плюс reply-потенциал: есть "
    "что ответить (вопрос-себе / удивление / несогласие)? Нет — пост мёртв.\n"
    "— «Думающий, не знающий»: режь TG-«знающее» (сухая механика, тикеры/суммы/сделки, регуляторы). "
    "Тест: перестаёт работать для того, кто про крипту слышать не хочет → это TG-контент, не Threads.\n"
    "— 1–4 поста ≤500 (цель 440–495). Число — по материалу; «лучше два, чем четыре»: слабый пост ПОРТИТ "
    "сильные, отсекай без жалости (хороший факт ≠ хороший тред).\n"
    "— НЕПЕРЕСЕЧЕНИЕ постов (три слоя): не совпадать ни фактами, ни ПРИЁМОМ (узнавание / удивление / "
    "зеркало…), ни финалом. Совпал хотя бы приём → второй лишний.\n"
    "— Первая строка = payoff-удар/афоризм, не разгон. Строки-биты, регистр «ты» / безличное (кухня, не "
    "кафедра), без футера/ссылок/хештегов.\n"
    "— Финал = УДАР: вопрос-зеркало ИЛИ формула-афоризм. НЕ пересказ тезиса, не «время покажет», не «а "
    "что думаете вы?» в лоб.\n"
    "— ПОРЯДОК: первым тот, что СИЛЬНЕЕ провоцирует ответ (не «важнее по смыслу»).\n"
    "ВЫВОД: ТОЛЬКО посты, разделённые ОТДЕЛЬНОЙ строкой «" + POST_SEP + "» между ними, В ПОРЯДКЕ "
    "ПУБЛИКАЦИИ (без нумерации / преамбулы / комментариев). Один пост — без разделителя.\n\n"
    "ВЫШЕДШИЙ ФЛАГМАН (источник для дистилляции):\n{flagship}"
)


def _save(series: str, src: dict) -> None:
    """Сохранить серию в свой архив (memory/threads_drafts/). Не критично — сбой не роняет выдачу."""
    try:
        THREADS_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        raw = (src.get("theme") or "flagman").lower()
        slug = re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")[:40] or "flagman"
        fname = f"{date.today().isoformat()}-{slug}-threads.md"
        (THREADS_DRAFTS_DIR / fname).write_text(series, encoding="utf-8", newline="\n")
    except Exception:
        logging.exception("threads_creator: не смог сохранить серию (не критично, выдаю в чат)")


def write(hint: str = "") -> str:
    """Дистиллировать ПОСЛЕДНИЙ вышедший флагман (journal) в мини-серию Threads. Возвращает текст серии
    (посты через POST_SEP) или сообщение об отказе (журнал пуст). hint — пожелание владельца (необязательно)."""
    src = flagship_journal.latest()
    if not src or not src.get("text"):
        return ("⚠️ В журнале вышедших флагманов пусто — дистиллировать нечего. Сначала опубликуй "
                "флагман в ТГ (он запишется в журнал), потом запускай мини-флагман.")
    cfg = config.load_agent(AGENT_NAME)
    key = config.agent_api_key(cfg)
    model = runmode.resolve(THREADS_MODEL, ceiling=THREADS_MODEL)
    task = TASK.format(flagship=src["text"])
    if hint:
        task += f"\n\nПОЖЕЛАНИЕ ВЛАДЕЛЬЦА: {hint}"
    cost.set_context("threads")  # иначе расход пишется who='?' — аудит 15.07 не смог его атрибутировать
    # one-shot без инструментов → кэш системы не окупается (запись 1h = 2× без перечтений)
    text, _ = llm.reply(model, _system(), [], task, [], lambda _n, _a: "", key, THREADS_THINKING,
                        cache_system=False)
    text = (text or "").strip()
    if text:
        _save(text, src)
        # Журнал дистилляций: связь «флагман → серия» + категория (вход петли само-обучения).
        threads_distill_journal.record(src, text, POST_SEP)
    return text


# --- Петля обучения на ПРАВКАХ владельца (token-независимо: учимся на редактуре, не на метриках) ---
RECORD_THREADS_LESSON_TOOL = {
    "name": "record_threads_lesson",
    "description": "Усвоить УРОК из правки владельца к Threads-серии — добавить в memory/threads_lessons.md "
                   "(грузится тебе к каждой дистилляции, ОТДЕЛЬНО от ТГ-уроков). Только устойчивые "
                   "переносимые правила, не разовую косметику; один вызов — один урок. ПЕРЕД записью "
                   "сверься: правило уже в мануале/эталонах/уроках — НЕ дублируй. После записи отчитайся.",
    "input_schema": {
        "type": "object",
        "properties": {
            "lesson": {"type": "string", "description": "устойчивое правило на будущее, одной фразой"},
            "evidence": {"type": "string", "description": "что в правке навело (коротко, необязательно)"},
        },
        "required": ["lesson"],
    },
}


def _record_lesson(lesson: str, evidence: str = "") -> str:
    """Дописать урок в memory/threads_lessons.md с простым анти-дублем (не пишем, если уже есть)."""
    lesson = (lesson or "").strip()
    if not lesson:
        return "пустой урок — не записал"
    try:
        existing = THREADS_LESSONS.read_text(encoding="utf-8") if THREADS_LESSONS.exists() else ""
        if lesson.lower() in existing.lower():
            return "похоже, такой урок уже есть — не дублирую"
        THREADS_LESSONS.parent.mkdir(parents=True, exist_ok=True)
        with THREADS_LESSONS.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(f"- {lesson}" + (f"  _(повод: {evidence.strip()})_" if evidence.strip() else "") + "\n")
        return f"усвоил: {lesson}"
    except Exception:
        logging.exception("threads_creator: не смог записать урок")
        return "не смог записать урок (см. лог)"


def _dispatch(name: str, args: dict) -> str:
    if name == "record_threads_lesson":
        return _record_lesson(args.get("lesson", ""), args.get("evidence", ""))
    return ""


def _latest_threads_draft() -> str:
    """Текст самой свежей Threads-серии из своего архива (для сравнения с финалом владельца)."""
    try:
        files = sorted(THREADS_DRAFTS_DIR.glob("*.md"), key=lambda p: -p.stat().st_mtime)
        return files[0].read_text(encoding="utf-8") if files else ""
    except Exception:
        logging.warning("Не смог прочитать последний Threads-драфт для сравнения", exc_info=True)
        return ""


FEEDBACK = (
    "ОБУЧЕНИЕ НА ПРАВКЕ (Threads мини-флагман). Владелец прислал свой ФИНАЛЬНЫЙ отредактированный "
    "вариант Threads-серии. 1) Сравни свой драфт ↔ финал: что владелец вырезал/добавил/переформулировал, "
    "как сдвинул нарезку/длину/тон/крючок/концовку/число постов. 2) Выдели УСТОЙЧИВЫЕ переносимые правила "
    "(а не разовую косметику под эту тему) и запиши КАЖДОЕ через record_threads_lesson (один вызов — один "
    "урок), при возможности с коротким evidence. Правило, которое уже в мануале/эталонах — НЕ дублируй. "
    "3) Отчитайся 2-4 строки «усвоил: …» — что изменю в будущих сериях. Правок мало / косметика — так и "
    "скажи, урок не плоди ради записи.\n\nТВОЙ ДРАФТ:\n{draft}\n\nФИНАЛ ВЛАДЕЛЬЦА:\n{final}"
)


def write_feedback(final_text: str) -> str:
    """Петля обучения мини-флагмана: сравнить свою серию с финалом владельца → устойчивые уроки в
    memory/threads_lessons.md. Учимся на ПРАВКАХ (не на метриках) — работает независимо от сбора данных.
    Метрики-петля — отдельно; заводится прогоном refresh_threads (токен Threads живой, не блокер)."""
    final_text = (final_text or "").strip()
    if not final_text:
        return "Пришли отредактированный финал Threads-серии в том же сообщении после команды."
    cfg = config.load_agent(AGENT_NAME)
    key = config.agent_api_key(cfg)
    model = runmode.resolve(THREADS_MODEL, ceiling=THREADS_MODEL)
    draft = _latest_threads_draft() or "(своего драфта не нашёл — опирайся на эталоны/мануал при сравнении)"
    cost.set_context("threads")
    # здесь кэш ОСТАВЛЕН: есть инструмент (запись урока) → несколько API-раундов перечитывают систему
    text, _ = llm.reply(model, _system(), [], FEEDBACK.format(draft=draft, final=final_text),
                        [RECORD_THREADS_LESSON_TOOL], _dispatch, key, THREADS_THINKING)
    return text or "(пусто)"
