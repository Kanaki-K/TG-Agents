"""Инструменты ассистента — его «руки» внутри памяти.

Схемы передаём в Claude; когда модель решает вызвать инструмент,
dispatch() выполняет соответствующую функцию из memory.py.
"""
from __future__ import annotations

from core import memory

TOOLS = [
    {
        "name": "add_task",
        "description": "Добавить задачу в живой ТуДу владельца.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Суть задачи"},
                "priority": {"type": "string", "description": "P1/P2/P3, необязательно"},
                "due": {"type": "string", "description": "Срок ГГГГ-ММ-ДД, необязательно"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "complete_task",
        "description": "Отметить задачу выполненной по её числовому id.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "list_tasks",
        "description": "Показать список открытых задач.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "remember_fact",
        "description": "Сохранить стабильный факт о владельце в профиль (канон).",
        "input_schema": {
            "type": "object",
            "properties": {"fact": {"type": "string"}},
            "required": ["fact"],
        },
    },
    {
        "name": "append_journal",
        "description": "Записать заметку или итог в журнал сегодняшней сессии.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
]


def dispatch(name: str, args: dict) -> str:
    if name == "add_task":
        return memory.add_task(args["text"], args.get("priority", ""), args.get("due", ""))
    if name == "complete_task":
        return memory.complete_task(int(args["task_id"]))
    if name == "list_tasks":
        return memory.list_tasks()
    if name == "remember_fact":
        return memory.remember_fact(args["fact"])
    if name == "append_journal":
        return memory.append_journal(args["text"])
    return f"Неизвестный инструмент: {name}"
