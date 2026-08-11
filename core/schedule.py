"""Автопилот: КОГДА завод запускается сам — и когда НЕ запускается.

Зачем отдельным модулем: «пора или нет» — чистая функция от времени и состояния на диске, поэтому
покрывается тестами БЕЗ реального прогона (прогон = деньги + публикация в канал). `run_autopilot.py`
только исполняет вердикт и умеет о нём рассказать.

Ритм недели тут НЕ дублируется: дни и время выхода берём из `core/content_plan` (Вт/Чт,
`PUBLISH_FLAGSHIP_TIME`, `PUBLISH_TZ`). Здесь — только окно старта, метка «сегодня уже гоняли»
и предохранители. Полное объяснение для владельца — в `docs/AUTOPILOT.md`.

ГЛАВНЫЙ предохранитель — файл-выключатель `data/autopilot_on` (по образцу `data/threads_unlocked`):
нет файла → автопилот НИЧЕГО не делает. Удалить файл = мгновенно всё остановить, .env не трогая.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

from core import config, content_plan, io_safe

log = logging.getLogger(__name__)

STATE_FILE = config.ROOT / "data" / "autopilot_state.json"   # что и когда гоняли (переживает перезапуск)
ON_FILE = config.ROOT / "data" / "autopilot_on"              # файл-выключатель: нет → автопилот спит

DEFAULT_LEAD_HOURS = 4.0       # за сколько часов до слота стартуем (флагману повод не нужен — можно с утра)
DEFAULT_MARGIN_MINUTES = 60    # ближе этого к слоту не начинаем: прогон (~10-20 мин) должен успеть
DEFAULT_CHECK_EVERY = 600      # пауза между проверками в режиме --daemon, сек

_UNSET = object()               # «параметр не передан» ≠ «передан None» (None значит «неизвестно»)


def _num(name: str, default: float) -> float:
    raw = config.get_optional(name)
    if not raw:
        return default
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        log.warning("[автопилот] %s='%s' не число — беру %s", name, raw, default)
        return default


def lead_hours() -> float:
    return _num("AUTOPILOT_LEAD_HOURS", DEFAULT_LEAD_HOURS)


def margin_minutes() -> float:
    return _num("AUTOPILOT_MARGIN_MINUTES", DEFAULT_MARGIN_MINUTES)


def check_every() -> float:
    return _num("AUTOPILOT_CHECK_EVERY", DEFAULT_CHECK_EVERY)


def enabled() -> bool:
    """Включён ли автопилот. Один выключатель — ФАЙЛ (не .env): убирается одним движением."""
    return ON_FILE.exists()


def turn_on(reason: str = "") -> None:
    """Включить автопилот (создать файл-выключатель). Причина остаётся в файле — как у Threads."""
    ON_FILE.parent.mkdir(exist_ok=True)
    stamp = datetime.now(content_plan.tz()).isoformat(timespec="seconds")
    ON_FILE.write_text(f"{stamp} {reason}".strip() + "\n", encoding="utf-8")


def turn_off() -> None:
    """Выключить автопилот (удалить файл). Прогон, который уже идёт, не трогает."""
    ON_FILE.unlink(missing_ok=True)


def _state() -> dict:
    data = io_safe.load_json(STATE_FILE, {})
    return data if isinstance(data, dict) else {}


def last_run(kind: str = "flagship") -> date | None:
    """Дата последнего АВТО-прогона формата (None — ни разу / файл битый)."""
    raw = _state().get(kind)
    try:
        return date.fromisoformat(raw) if raw else None
    except (TypeError, ValueError):
        log.info("[автопилот] в состоянии кривая дата для '%s': %r", kind, raw)
        return None


def mark_run(kind: str, d: date | None = None) -> None:
    """Пометить, что формат сегодня уже запускался.

    Ставим метку ДО прогона (заявка, не отчёт): если прогон упадёт на середине, автопилот не станет
    перезапускать его каждые 10 минут и жечь деньги. Владелец увидит алерт о падении и решит сам.
    """
    d = d or datetime.now(content_plan.tz()).date()
    data = _state()
    data[kind] = d.isoformat()
    try:
        STATE_FILE.parent.mkdir(exist_ok=True)
        STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        log.exception("[автопилот] не смог записать состояние в %s", STATE_FILE)


def window(kind: str, d: date) -> tuple[datetime, datetime] | None:
    """Окно старта в конкретный день: (когда можно начинать, крайний срок). None — не день формата.

    Начало = слот − AUTOPILOT_LEAD_HOURS (по умолч. 4ч: пост в 16:00 ⇒ старт в 12:00).
    Конец = слот − AUTOPILOT_MARGIN_MINUTES. Это ОКНО, а не точка: если машина спала и Планировщик
    дёрнул нас в 13:20 вместо 12:00 — прогон всё равно состоится, пост всё равно успеет к 16:00.
    """
    slot = content_plan.slot_on(d, kind)
    if slot is None:
        return None
    return slot - timedelta(hours=lead_hours()), slot - timedelta(minutes=margin_minutes())


def due(kind: str = "flagship", *, now: datetime | None = None,
        busy_dates: set | None = None, last=_UNSET) -> dict:
    """Вердикт: {'go': bool, 'why': причина человеческим языком, 'slot': слот сегодня | None}.

    Чистая: всё внешнее (время, отложка канала, дата прошлого прогона) можно передать параметрами —
    отсюда тесты. `busy_dates=None` значит «проверить отложку не удалось» (нет сессии/сети): НЕ
    блокируем прогон, но пишем это в причину — предохранителем тут выступает сам content_plan
    (next_slot пропускает занятые дни), а молчаливый пропуск выхода хуже.
    """
    z = content_plan.tz()
    now = (now or datetime.now(z)).astimezone(z)
    today = now.date()
    slot = content_plan.slot_on(today, kind)
    label = content_plan.kind_label(kind)
    if slot is None:
        days = "/".join(content_plan.RU_DOW[i] for i in content_plan.days_for(kind))
        return {"go": False, "slot": None,
                "why": f"сегодня {content_plan.RU_DOW[today.weekday()]} — не день формата «{label}» ({days})"}
    start, deadline = window(kind, today)
    if now < start:
        return {"go": False, "slot": slot,
                "why": f"рано: окно старта с {start:%H:%M} (выход в {slot:%H:%M})"}
    if now > deadline:
        return {"go": False, "slot": slot,
                "why": f"поздно: до выхода в {slot:%H:%M} меньше {margin_minutes():.0f} мин — "
                       f"прогон не успеет, сегодня пропускаю"}
    prev = last_run(kind) if last is _UNSET else last
    if prev == today:
        return {"go": False, "slot": slot, "why": "сегодня уже запускался (метка в autopilot_state.json)"}
    if busy_dates and today in busy_dates:
        return {"go": False, "slot": slot,
                "why": "на сегодня в «Отложенных» канала пост уже стоит — второй не нужен"}
    note = "" if busy_dates is not None else " (отложку канала проверить не удалось — иду по плану)"
    return {"go": True, "slot": slot,
            "why": f"пора: «{label}» выходит сегодня в {slot:%H:%M}, окно старта "
                   f"{start:%H:%M}–{deadline:%H:%M}{note}"}
