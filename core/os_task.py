"""Будильник в ОС: Криейтор сам ставит и снимает задачу Планировщика Windows (schtasks).

Зачем: у пайплайна контракт «один запуск = готовый результат», и у автопилота должен быть такой же.
Владелец 11.08: «настройки как юзер, через Криейтора — я с ним договариваюсь, он записывает и
выполняет». Значит «включи автопилот» обязано включать ВСЁ: и разрешение (файл-выключатель), и того,
кто разбудит процесс в нужный час. Три ручки (файл + Планировщик + бот) — это наша внутренняя кухня,
владельцу она не нужна.

Почему Планировщик, а не вечный процесс: переживает перезагрузку и не требует следить, жив ли он.
Почему `pythonw.exe`: обычный python открывал бы консольное окно на КАЖДУЮ проверку (каждые 30 минут,
весь день) — это невыносимо. Вывод при этом уходит в никуда, поэтому автопилот и пишет свой лог в файл
(`data/autopilot.log`) — см. `run_autopilot._prepare_unattended`.
"""
from __future__ import annotations

import locale
import logging
import os
import subprocess  # noqa: S404 — фиксированный системный schtasks.exe, аргументы списком (не shell)
import sys
from pathlib import Path

from core import config

log = logging.getLogger(__name__)

TASK_NAME = "TG-Agents autopilot"   # ASCII: кириллица в /TN у schtasks капризна
SCRIPT = config.ROOT / "run_autopilot.py"

DEFAULT_START = "08:00"     # с какого часа будильник начинает проверять
DEFAULT_EVERY = 30          # раз в сколько минут
DEFAULT_HOURS = 12          # сколько часов продолжать (08:00 + 12ч = до 20:00)


def supported() -> bool:
    """Ставить задачу умеем только на Windows (у владельца именно он). Иначе — честный отказ."""
    return os.name == "nt"


def python_exe() -> str:
    """Каким интерпретатором запускать задачу: `pythonw.exe`, если есть — он БЕЗ консольного окна."""
    exe = Path(sys.executable)
    quiet = exe.with_name("pythonw.exe")
    return str(quiet if quiet.exists() else exe)


def _run(args: list[str]) -> tuple[int, str]:
    """Вызвать schtasks. Возвращает (код, вывод). Не бросает — решение принимает вызывающий."""
    try:
        p = subprocess.run(args, capture_output=True, timeout=30, check=False)  # noqa: S603
    except (OSError, subprocess.SubprocessError) as e:
        return 1, f"не смог вызвать schtasks: {e}"
    enc = locale.getpreferredencoding(False) or "utf-8"
    out = (p.stdout + p.stderr).decode(enc, errors="replace").strip()
    return p.returncode, out


def status() -> dict:
    """Стоит ли будильник: {'supported', 'exists', 'detail'}."""
    if not supported():
        return {"supported": False, "exists": False, "detail": "не Windows — задачу ставить нечем"}
    rc, out = _run(["schtasks", "/Query", "/TN", TASK_NAME])
    return {"supported": True, "exists": rc == 0,
            "detail": out if rc == 0 else "задачи нет"}


def install(*, start: str = DEFAULT_START, every: int = DEFAULT_EVERY,
            hours: int = DEFAULT_HOURS) -> dict:
    """Поставить (или переставить) будильник. {'ok', 'detail'}.

    Каждые `every` минут в течение `hours` часов, ЕЖЕДНЕВНО — а решение «пора или нет» принимает код
    (`core/schedule.due`). Так расписание канала не зависит от того, в каком поясе стоит машина: лишние
    срабатывания выходят за миллисекунды и в сеть не лезут. /F — перезаписать, если задача уже есть
    (идемпотентно: повторное «включи автопилот» не плодит дубли).
    """
    if not supported():
        return {"ok": False, "detail": "автозапуск по расписанию умею ставить только на Windows"}
    if not SCRIPT.exists():
        return {"ok": False, "detail": f"не нашёл {SCRIPT} — проект переехал?"}
    target = f'"{python_exe()}" "{SCRIPT}"'
    rc, out = _run(["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/TR", target,
                    "/SC", "DAILY", "/ST", start, "/RI", str(every), "/DU", f"{hours:04d}:00"])
    if rc != 0:
        log.error("[будильник] schtasks /Create вернул %s: %s", rc, out)
        return {"ok": False, "detail": out or f"schtasks вернул код {rc}"}
    log.info("[будильник] задача поставлена: каждые %s мин с %s, %s ч", every, start, hours)
    return {"ok": True, "detail": f"каждые {every} мин с {start} в течение {hours} ч, ежедневно"}


def remove() -> dict:
    """Снять будильник. {'ok', 'detail'}. Отсутствие задачи — тоже успех (нечего снимать)."""
    if not supported():
        return {"ok": True, "detail": "не Windows — задачи и не было"}
    if not status()["exists"]:
        return {"ok": True, "detail": "задачи и не было"}
    rc, out = _run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
    if rc != 0:
        log.error("[будильник] schtasks /Delete вернул %s: %s", rc, out)
        return {"ok": False, "detail": out or f"schtasks вернул код {rc}"}
    log.info("[будильник] задача снята")
    return {"ok": True, "detail": "задача снята"}
