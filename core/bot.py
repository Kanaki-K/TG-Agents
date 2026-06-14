"""Бот личного ассистента — тонкая обвязка над общим рантаймом (core/agent_runtime).

Запуск: python main.py  (нужны SECRETARY_BOT_TOKEN и ANTHROPIC_API_KEY в .env)
"""
from __future__ import annotations

from core import agent_runtime, config, llm, memory, tools

AGENT_NAME = "personal-assistant"

WELCOME = (
    "Привет! Я твой личный ассистент. Скидывай мысли и задачи — "
    "разложу, запомню и помогу спланировать.\n"
    "Команды: /tasks — задачи, /summary — итог сессии."
)

COMMANDS = {
    "tasks": "Покажи мои открытые задачи.",
    "summary": "Подведи короткий итог нашей сессии и запиши его в журнал (append_journal).",
}


def _system() -> str:
    persona = config.load_agent(AGENT_NAME)["persona"]
    ctx = (
        f"## Профиль владельца\n{memory.read_profile()}\n\n"
        f"## Открытые задачи\n{memory.list_tasks()}\n"
    )
    return llm.build_system(persona, ctx)


async def main() -> None:
    await agent_runtime.run(
        AGENT_NAME,
        tools_schema=tools.TOOLS,
        dispatch=tools.dispatch,
        system_builder=_system,
        welcome=WELCOME,
        commands=COMMANDS,
    )
