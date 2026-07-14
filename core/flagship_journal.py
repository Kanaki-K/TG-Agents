"""🧵 Журнал вышедших флагманов — мост ТГ → Threads.

Когда ТГ-флагман реально уходит в отложку канала (run_pipeline, только боевая публикация — не
draft-only/тест), его ПОЛНЫЙ текст + тема + дата дописываются сюда одной строкой JSON. Это ВХОД
мини-флагмана Threads: `threads_creator` берёт последнюю запись и дистиллирует её в серию постов.

Почему отдельный журнал, а не «читать последний драфт»: драфты эфемерны (их перетирает scope и
следующие прогоны), а журнал — намеренная датированная история (архив + устойчивый вход Threads).
Файл в data/ (gitignored) — рантайм-состояние, не код. Append-only, один флагман = одна строка.
"""
import json
import logging
from datetime import date

from core import config

JOURNAL = config.ROOT / "data" / "published_flagships.jsonl"


def record(text: str, theme: str = "") -> None:
    """Дописать вышедший флагман (полный текст + тема + дата) в журнал. Мету после [[SPLIT]] отбрасываем
    (в Threads уходит только тело). Сбой записи НЕ роняет публикацию — журнал вторичен к самому посту."""
    body = (text or "").split("[[SPLIT]]")[0].strip()
    if not body:
        return
    try:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        entry = {"date": date.today().isoformat(), "theme": (theme or "").strip(), "text": body}
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        logging.exception("flagship_journal: не смог записать вышедший флагман (публикацию не роняю)")


def latest() -> dict | None:
    """Последняя запись журнала (dict: date/theme/text) или None (журнала нет/пуст/битый). Вход
    мини-флагмана: ЧТО дистиллировать. Битую строку не роняем в трейс — просто None."""
    if not JOURNAL.exists():
        return None
    try:
        lines = [l for l in JOURNAL.read_text(encoding="utf-8").splitlines() if l.strip()]
        return json.loads(lines[-1]) if lines else None
    except Exception:
        logging.exception("flagship_journal: журнал не читается — возвращаю None")
        return None
