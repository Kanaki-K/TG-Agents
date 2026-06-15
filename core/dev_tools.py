"""Инструменты Разработчика — его «руки» над определениями других агентов.

Все операции идут через core/workshop.py, который гарантирует безопасность:
правка живого SKILL.md возможна только после явного предложения (diff) и
с автоматическим бэкапом для отката.
"""
from __future__ import annotations

from core import workshop

TOOLS = [
    {
        "name": "list_agents",
        "description": "Показать список агентов команды: роль, модель, есть ли неприменённое предложение.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_agent",
        "description": "Прочитать текущее определение агента (config.yaml + SKILL.md). "
                       "Делай это ПЕРЕД тем, как предлагать улучшение.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Имя папки агента, напр. channel-analyst"}},
            "required": ["name"],
        },
    },
    {
        "name": "propose_improvement",
        "description": "Предложить новую версию личности агента (SKILL.md). Живой файл НЕ меняется — "
                       "сохраняется предложение и возвращается diff для показа владельцу.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Имя папки агента"},
                "new_skill": {"type": "string", "description": "ПОЛНЫЙ текст нового SKILL.md"},
                "rationale": {"type": "string", "description": "Коротко: что меняем и зачем"},
            },
            "required": ["name", "new_skill"],
        },
    },
    {
        "name": "show_proposal",
        "description": "Показать diff неприменённого предложения по агенту.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "apply_improvement",
        "description": "Применить предложение в боевой SKILL.md. ВЫЗЫВАЙ ТОЛЬКО после явного одобрения "
                       "владельца в чате. Делает бэкап прежней версии для отката.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "discard_proposal",
        "description": "Отбросить неприменённое предложение по агенту.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "rollback_agent",
        "description": "Откатить агента к последней сохранённой версии SKILL.md (если улучшение оказалось хуже).",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
]


def dispatch(name: str, args: dict) -> str:
    try:
        if name == "list_agents":
            return workshop.list_agents()
        if name == "read_agent":
            return workshop.read_agent(args["name"])
        if name == "propose_improvement":
            return workshop.propose(args["name"], args["new_skill"], args.get("rationale", ""))
        if name == "show_proposal":
            return workshop.show_proposal(args["name"])
        if name == "apply_improvement":
            return workshop.apply(args["name"])
        if name == "discard_proposal":
            return workshop.discard(args["name"])
        if name == "rollback_agent":
            return workshop.rollback(args["name"])
        return f"Неизвестный инструмент: {name}"
    except Exception as e:  # ошибку отдаём модели как текст, чтобы она объяснила владельцу
        return f"Ошибка инструмента {name}: {e}"
