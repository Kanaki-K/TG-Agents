"""Замок прогона: два пайплайна разом делят состояние на диске и портят друг другу работу.

ЗАЧЕМ (10.09.2026, живой случай). Владелец запустил флагман и скоуп параллельно. Оба пишут в одни
и те же места: папку драфтов, аутбокс обложки (creator_tools.MEDIA_OUTBOX удаляется в начале
прогона — второй прогон снёс бы картинку первому), последний формат публикации, файлы обложек
скоупа. Выбор драфта «самый свежий файл» мы починили фильтром по формату, но остальное общее
состояние так не лечится: его надо просто не трогать вдвоём.

ПОЧЕМУ ЗАМОК, А НЕ РАЗВЕДЕНИЕ СОСТОЯНИЯ. Развести всё — это переписать пол-пайплайна ради сценария
«запустил два разом», который нужен раз в месяц. Замок стоит десять строк и закрывает ВСЕ гонки
сразу, включая те, которых мы ещё не нашли.

ПОВЕДЕНИЕ: второй прогон не ждёт, а сразу говорит, кто занял и когда, и выходит. Ожидание в очереди
хуже отказа: владелец ушёл бы пить чай, а через полчаса получил бы два поста в отложке подряд.
Замок старше часа считается брошенным (упал процесс) и перехватывается — иначе один сбой запер бы
конвейер навсегда.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime

from core import config, content_plan

LOCK = config.ROOT / "data" / "pipeline.lock"
STALE_SECONDS = 3600


def _read() -> dict:
    try:
        return json.loads(LOCK.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — битый замок = замка нет
        return {}


def holder() -> dict:
    """Кто держит замок сейчас ({} — свободен либо замок протух)."""
    row = _read()
    if not row:
        return {}
    if time.time() - float(row.get("at_ts") or 0) > STALE_SECONDS:
        return {}
    return row


def acquire(what: str = "прогон") -> bool:
    """Занять замок. False — занят другим (вызывающий обязан сказать владельцу и выйти)."""
    if holder():
        return False
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps({
        "what": what, "pid": os.getpid(), "at_ts": time.time(),
        "at": datetime.now(content_plan.tz()).isoformat(timespec="seconds")}, ensure_ascii=False),
        encoding="utf-8")
    return True


def release() -> None:
    """Снять замок. Чужой не трогаем: если перехватили протухший, а старый процесс ожил — пусть
    дорабатывает, ломать ему конец прогона хуже, чем оставить лишний файл."""
    row = _read()
    if row and int(row.get("pid") or 0) == os.getpid():
        LOCK.unlink(missing_ok=True)


def busy_message() -> str:
    row = holder()
    if not row:
        return ""
    return (f"⏳ Уже идёт «{row.get('what', 'прогон')}» (запущен {str(row.get('at', ''))[11:16]}, "
            f"pid {row.get('pid')}). Два прогона разом портят друг другу драфты и обложку.\n"
            f"   Дождись окончания или, если тот прогон умер, удали {LOCK.name} в data/ "
            f"(замок сам протухает через час).")
