"""Бот агента-аналитика канала — обвязка над общим рантаймом.

Оценивает контент по метрикам Telegram и подсказывает контент-криейтору,
что зашло лучше. Данные готовит коннектор telegram_export.

Запуск: python -m run_analyst   (нужны ANALYST_BOT_TOKEN и ANTHROPIC_API_KEY)
"""
from __future__ import annotations

from core import agent_runtime, analytics, analyst_tools, config, llm

AGENT_NAME = "channel-analyst"

WELCOME = (
    "Я аналитик канала KANAKI CRYPTO. Сужу по метрикам, что зашло, а что нет, "
    "помогаю не повторяться и подсказываю, какой контент усиливать.\n"
    "Команды: /report — обзор, /themes — какие темы работают, /best — что зашло, "
    "/timing — время и формат, /playbook — собрать плейбук форматов для Криейтора, "
    "/update — обновить метрики."
)

COMMANDS = {
    "report": "Сделай краткий обзор канала: общая сводка, какие темы и форматы заходят лучше, "
              "слабые места и 2-3 конкретные рекомендации контент-криейтору.",
    "themes": "Покажи темы канала со средними метриками (themes_overview) и сделай вывод: "
              "с какими темами стоит работать, а какие не заходят.",
    "best": "Покажи топ постов по просмотрам и по вовлечённости (ER) и кратко объясни, "
            "что у них общего — какие темы/форматы заходят.",
    "timing": "Разбери лучшее время публикации (по дням недели и часам) и какой формат "
              "(текст/медиа) заходит лучше. Дай вывод одной фразой.",
    "playbook": "Собери/обнови ПЛЕЙБУК ФОРМАТОВ для Криейтора. 1) Достань данные: top_posts(metric="
                "'forwards') и top_posts(metric='er') (что шарят и что вовлекает), by_dimension('type') "
                "и by_dimension('weekday'/'hour'), themes_overview. 2) Выдели РАБОТАЮЩИЕ форматы (флагман, "
                "лёгкий философский, образовательный типа «Словарь крипто» и т.п.): по каждому — что это, "
                "метрики (ER/репосты), когда/кому заходит, рекомендация (чаще/реже). 3) Предложи 1-2 формата-"
                "КАНДИДАТА под пробу по данным/трендам (помимо длинного флагмана). 4) save_playbook(полный "
                "текст) → в чат краткая выжимка владельцу: какие форматы усиливать и что попробовать.",
    "update": "Обнови метрики канала (update_metrics) и коротко скажи, что изменилось.",
}


def _system() -> str:
    persona = config.load_agent(AGENT_NAME)["persona"]
    ctx = (
        "## Текущая сводка по каналу (актуальна на момент последнего сбора)\n"
        f"{analytics.summary()}\n"
    )
    return llm.build_system(persona, ctx)


async def main() -> None:
    await agent_runtime.run(
        AGENT_NAME,
        tools_schema=analyst_tools.TOOLS,
        dispatch=analyst_tools.dispatch,
        system_builder=_system,
        welcome=WELCOME,
        commands=COMMANDS,
    )
