"""Бот агента-Разработчика — обвязка над общим рантаймом (core/agent_runtime).

Разработчик улучшает других сотрудников команды, правя их личность (SKILL.md),
строго через протокол «предложить → одобрение владельца → применить» (см. core/workshop).

Запуск: python run_dev.py   (нужны DEVELOPER_BOT_TOKEN и ANTHROPIC_API_KEY в .env)
"""
from __future__ import annotations

from core import agent_runtime, config, dev_tools, llm, workshop

AGENT_NAME = "developer"

WELCOME = (
    "Я Разработчик команды. По запросу (твоему или другого агента) улучшаю "
    "личности других ассистентов — но всегда сначала показываю diff и жду твоего «ок».\n"
    "Команды: /agents — состав команды, /pending — неприменённые предложения."
)

COMMANDS = {
    "agents": "Покажи состав команды (list_agents).",
    "pending": "Проверь через list_agents, по каким агентам есть неприменённые предложения, "
               "и покажи их diff через show_proposal.",
}


def _system() -> str:
    persona = config.load_agent(AGENT_NAME)["persona"]
    ctx = f"## Текущий состав команды\n{workshop.list_agents()}\n"
    return llm.build_system(persona, ctx)


async def main() -> None:
    await agent_runtime.run(
        AGENT_NAME,
        tools_schema=dev_tools.TOOLS,
        dispatch=dev_tools.dispatch,
        system_builder=_system,
        welcome=WELCOME,
        commands=COMMANDS,
    )
