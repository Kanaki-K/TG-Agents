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

from core import config, flagship_journal, llm, runmode

AGENT_NAME = "creator"                    # голос автора тот же — переиспользуем персону Криейтера
THREADS_MODEL = "claude-sonnet-4-6"       # короткий формат — Opus избыточен (как у scope); /test → Haiku
THREADS_THINKING = None                   # короткому дистилляту глубокое мышление не нужно (дёшево)

THREADS_DRAFTS_DIR = config.ROOT / "memory" / "threads_drafts"  # ОТДЕЛЬНО от ТГ-драфтов (изоляция)
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
    ctx = (
        "## 🧵 ТЫ ДЕЛАЕШЬ МИНИ-ФЛАГМАН ДЛЯ THREADS\n"
        "ОТДЕЛЬНЫЙ формат. Правила ТГ-флагмана (антитеза на весь пост, 2800–4096 знаков, разделы 💡/💭, "
        "обложка) и 🔭-скоупа к тебе НЕ применяются. Ты берёшь УЖЕ ВЫШЕДШИЙ ТГ-флагман и дистиллируешь "
        "его в 1–4 самостоятельных Threads-поста. Не репост и не пересказ — новая нарезка под площадку.\n\n"
        "## 📕 МАНУАЛ МИНИ-ФЛАГМАНА (правила механики) — следуй строго (memory/threads_manual.md)\n"
        f"{_read('memory/threads_manual.md')}\n\n"
        "## 🎯 ЭТАЛОНЫ ГОЛОСА И НАРЕЗКИ — режь В ЭТОМ голосе (memory/threads_flagman_anchors.md)\n"
        "Полный текст дистилляций владельца. Голос и приём нарезки переноси ОТСЮДА (как флагман с "
        "anchor_posts): payoff первой строкой, строки-биты, регистр «Вы», лишнее за борт.\n"
        f"{anchors}\n\n"
        "## Канон бренда — аудитория и КРАСНЫЕ ЛИНИИ (memory/brand.md)\n"
        "Соблюдай красные линии: BTC не проигравший, без политоты/России/торговых сигналов.\n"
        f"{_read('memory/brand.md')}\n"
    )
    return llm.build_system(persona, ctx)


TASK = (
    "Сделай МИНИ-ФЛАГМАН для Threads из вышедшего ТГ-флагмана (ниже). СТРОГО по мануалу "
    "(memory/threads_manual.md в контексте) и эталонам голоса. Главное:\n"
    "— Регистр «Вы» (как в эталонах).\n"
    "— 1–4 самостоятельных поста ≤500 символов КАЖДЫЙ. Количество — по материалу: богатый флагман → "
    "3–4, тонкий → 1. НЕ высасывай из пальца — качество важнее числа.\n"
    "— Дистилляция = выбери 1–2 сильнейших ЧЕЛОВЕЧЕСКИХ угла и слей их; НЕ покрывай весь флагман. "
    "Сухую крипто-механику (сети, тикеры, суммы, сделки) режь.\n"
    "— Первая строка поста = payoff-удар/афоризм, НЕ разгон. Строки-биты; без футера, без ссылок и "
    "хештегов в теле.\n"
    "— Концовка поста = вопрос под ответ ИЛИ сильная payoff-строка.\n"
    "ВЫВОД: ТОЛЬКО посты, разделённые ОТДЕЛЬНОЙ строкой «" + POST_SEP + "» между ними (без нумерации, "
    "без преамбулы и комментариев). Один пост — без разделителя.\n\n"
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
    model = runmode.resolve(THREADS_MODEL)
    task = TASK.format(flagship=src["text"])
    if hint:
        task += f"\n\nПОЖЕЛАНИЕ ВЛАДЕЛЬЦА: {hint}"
    text, _ = llm.reply(model, _system(), [], task, [], lambda _n, _a: "", key, THREADS_THINKING)
    text = (text or "").strip()
    if text:
        _save(text, src)
    return text
