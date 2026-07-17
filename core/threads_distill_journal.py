"""Журнал дистилляций Threads — связь «вышедший флагман → его Threads-серия» + категория.

Зачем: чтобы позже привязать перформанс Threads-постов к ТЕМЕ/КАТЕГОРИИ флагмана (единица
замера петли само-обучения = флагман + его дистилляция). Публикация в Threads ручная → ID
постов на момент генерации неизвестны; поэтому здесь фиксируем ТЕКСТ серии + дату/тему/категорию
флагмана, а линкер (следующий шаг) сматчит собранные посты с этим текстом по дате+совпадению.

Append-only, одна дистилляция = одна строка JSON, в data/ (gitignored рантайм-состояние).
Сбой записи НЕ роняет генерацию — журнал вторичен к самой серии.
"""
from __future__ import annotations

import json
import logging
from datetime import date

from core import config, topic_category

JOURNAL = config.ROOT / "data" / "threads_distillations.jsonl"


def record(flagship: dict, series_text: str, sep: str) -> None:
    """Зафиксировать дистилляцию: посты серии + дата/тема/категория исходного флагмана.

    flagship — запись из flagship_journal (date/theme/text). series_text — вывод дистиллятора
    (посты через sep). Категория выводится из темы флагмана по банку (core/topic_category)."""
    posts = [p.strip() for p in (series_text or "").split(sep) if p.strip()]
    if not posts:
        return
    theme = (flagship or {}).get("theme", "")
    try:
        entry = {
            "created": date.today().isoformat(),
            "flagship_date": (flagship or {}).get("date", ""),
            "theme": theme,
            "category": topic_category.category_of(theme),
            "posts": posts,
        }
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        logging.exception("threads_distill_journal: не смог записать дистилляцию (генерацию не роняю)")


def entries() -> list[dict]:
    """Все записи журнала (старые→новые). Битый файл/строка → пропускаем, не роняем трейс."""
    if not JOURNAL.exists():
        return []
    out: list[dict] = []
    try:
        for ln in JOURNAL.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
    except Exception:
        logging.exception("threads_distill_journal: журнал не читается — возвращаю, что успел")
    return out
