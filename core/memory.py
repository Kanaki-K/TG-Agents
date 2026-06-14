"""Общий слой памяти: профиль (канон), задачи (живой ТуДу), журнал сессий.

Файлы лежат в /memory и их можно открыть и проверить руками.
Источник правды по задачам — tasks.json; tasks.md генерируется из него для чтения.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEM = ROOT / "memory"
PROFILE = MEM / "profile.md"
TASKS_JSON = MEM / "tasks.json"
TASKS_MD = MEM / "tasks.md"
JOURNAL = MEM / "journal"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# --- Профиль (канон о владельце) ---
def read_profile() -> str:
    return PROFILE.read_text(encoding="utf-8") if PROFILE.exists() else ""


def remember_fact(fact: str) -> str:
    with open(PROFILE, "a", encoding="utf-8") as f:
        f.write(f"- ({_today()}) {fact}\n")
    return "Записал в профиль."


# --- Задачи (живой ТуДу) ---
def _load_tasks() -> list[dict]:
    if TASKS_JSON.exists():
        return json.loads(TASKS_JSON.read_text(encoding="utf-8"))
    return []


def _save_tasks(tasks: list[dict]) -> None:
    TASKS_JSON.write_text(
        json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _render_tasks_md(tasks)


def _render_tasks_md(tasks: list[dict]) -> None:
    lines = ["# Задачи (живой ТуДу)", "",
             "_Файл генерируется автоматически из tasks.json._", "", "## Открытые"]
    for t in (t for t in tasks if not t.get("done")):
        meta = ", ".join(x for x in (t.get("priority"), t.get("due")) if x)
        meta = f" ({meta})" if meta else ""
        lines.append(f"- [ ] #{t['id']} {t['text']}{meta}")
    lines += ["", "## Сделано"]
    for t in (t for t in tasks if t.get("done")):
        lines.append(f"- [x] #{t['id']} {t['text']}")
    TASKS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def add_task(text: str, priority: str = "", due: str = "") -> str:
    tasks = _load_tasks()
    new_id = max((t["id"] for t in tasks), default=0) + 1
    tasks.append({"id": new_id, "text": text, "priority": priority,
                  "due": due, "done": False, "created": _now()})
    _save_tasks(tasks)
    return f"Добавил задачу #{new_id}: {text}"


def complete_task(task_id: int) -> str:
    tasks = _load_tasks()
    for t in tasks:
        if t["id"] == task_id:
            t["done"] = True
            _save_tasks(tasks)
            return f"Задача #{task_id} отмечена сделанной."
    return f"Задача #{task_id} не найдена."


def list_tasks() -> str:
    tasks = [t for t in _load_tasks() if not t.get("done")]
    if not tasks:
        return "Открытых задач нет."
    out = []
    for t in tasks:
        meta = ", ".join(x for x in (t.get("priority"), t.get("due")) if x)
        meta = f" ({meta})" if meta else ""
        out.append(f"#{t['id']} {t['text']}{meta}")
    return "\n".join(out)


# --- Журнал / саммари сессий ---
def append_journal(text: str) -> str:
    JOURNAL.mkdir(exist_ok=True)
    with open(JOURNAL / f"{_today()}.md", "a", encoding="utf-8") as f:
        f.write(f"\n### {_now()}\n{text}\n")
    return "Записал в журнал."
