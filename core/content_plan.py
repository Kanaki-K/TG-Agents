"""Контент-план канала — КОГДА и ЧТО постим. Решает, на какой слот ставить готовый пост.

Зеркалит memory/post_standard.md §«Ритм недели» (решение 18.06.2026) — держать в синхроне с ним
(позже вынесем в отдельный структурированный файл-план и будем дополнять):
    Вт + Чт   → флагман (Ф1), окно 16–19:00
    Пн/Ср/Пт  → короткий (Ф5), окно 14–19:00
    Сб/Вс     → постов нет
Пост-стандарт задаёт ВРЕМЯ окном, не точкой, поэтому точное время и часовой пояс — в .env
(PUBLISH_UTC_OFFSET, PUBLISH_FLAGSHIP_TIME, PUBLISH_SHORT_TIME); тут — разумные значения по умолчанию.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from core import config

# weekday(): Пн=0, Вт=1, Ср=2, Чт=3, Пт=4, Сб=5, Вс=6
FLAGSHIP_DAYS = (1, 3)            # Вторник, Четверг
SHORT_DAYS = (0, 2, 4)           # Понедельник, Среда, Пятница
DEFAULT_FLAGSHIP_TIME = (17, 0)   # в окне 16–19:00
DEFAULT_SHORT_TIME = (15, 0)      # в окне 14–19:00
FLAGSHIP_MIN_CHARS = 1500        # длинный пост ⇒ флагман, короче ⇒ короткий (если формат не задан явно)

RU_DOW = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def tz() -> timezone:
    """Часовой пояс канала фиксированным смещением (PUBLISH_UTC_OFFSET, по умолч. +3 — Москва, без DST)."""
    try:
        off = float(config.get_optional("PUBLISH_UTC_OFFSET") or 3)
    except ValueError:
        off = 3.0
    return timezone(timedelta(hours=off))


def _slot_time(kind: str) -> time:
    raw = config.get_optional("PUBLISH_FLAGSHIP_TIME" if kind == "flagship" else "PUBLISH_SHORT_TIME")
    if raw and ":" in raw:
        try:
            h, m = raw.split(":")
            return time(int(h), int(m))
        except ValueError:
            pass
    h, m = DEFAULT_FLAGSHIP_TIME if kind == "flagship" else DEFAULT_SHORT_TIME
    return time(h, m)


def infer_kind(text: str) -> str:
    """Формат поста по длине: длинный ⇒ флагман (Ф1), короткий ⇒ короткий (Ф5)."""
    return "flagship" if len(text or "") >= FLAGSHIP_MIN_CHARS else "short"


def kind_label(kind: str) -> str:
    return "флагман (Ф1)" if kind == "flagship" else "короткий (Ф5)"


def next_slot(kind: str, *, now: datetime | None = None, busy_dates: set | None = None) -> datetime:
    """Ближайший подходящий слот для формата по ритму недели (tz-aware datetime).

    busy_dates — даты (date), на которые уже стоит отложенный пост: пропускаем (не сдваиваем день).
    Ищем вперёд до 3 недель; если ничего — фолбэк через неделю в тот же слот.
    """
    z = tz()
    now = (now or datetime.now(z)).astimezone(z)
    days = FLAGSHIP_DAYS if kind == "flagship" else SHORT_DAYS
    t = _slot_time(kind)
    busy_dates = busy_dates or set()
    for ahead in range(0, 21):
        d = (now + timedelta(days=ahead)).date()
        if d.weekday() not in days or d in busy_dates:
            continue
        cand = datetime.combine(d, t, z)
        if cand <= now + timedelta(minutes=5):   # в прошлом / слишком близко — берём следующий день
            continue
        return cand
    return datetime.combine((now + timedelta(days=7)).date(), t, z)


def human(dt: datetime) -> str:
    """Человекочитаемый слот: «Чт 26.06 17:00»."""
    return f"{RU_DOW[dt.weekday()]} {dt:%d.%m %H:%M}"
