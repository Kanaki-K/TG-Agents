"""Бот Криейтора — пишет посты канала по направлению от владельца (часто от Скаута).

Обвязка над общим рантаймом. Инструментов нет: задача — писать текст в голосе автора
по стандарту поста, не выдумывая фактов. Канон голоса/красные линии и стандарт поста
подаются в контекст из общего слоя памяти.

Запуск: python run_creator.py   (нужны CREATOR_BOT_TOKEN и ключ Claude)
"""
from __future__ import annotations

from core import agent_runtime, analytics, config, llm

AGENT_NAME = "creator"

WELCOME = (
    "Я Криейтор KANAKI CRYPTO. Пришли направление/тему (можно прямо вывод Скаута) — напишу пост "
    "в твоём голосе по стандарту канала. По умолчанию флагман (800–1100 слов: заголовок-вопрос → "
    "факт → механика → кейсы → личный вывод). Скажи «лёгкий», если нужен короткий философский "
    "(200–400 слов). Цифры не выдумываю — чего нет, помечу [ПРОВЕРИТЬ]. Это драфт на правку — публикуешь ты."
)


def _read(rel: str) -> str:
    p = config.ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _system() -> str:
    persona = config.load_agent(AGENT_NAME)["persona"]
    ctx = (
        "## Канон бренда — голос и красные линии (memory/brand.md)\n"
        f"{_read('memory/brand.md')}\n\n"
        "## Стандарт поста — как писать (memory/post_standard.md)\n"
        f"{_read('memory/post_standard.md')}\n\n"
        "## Сводка по каналу (контекст: что заходит)\n"
        f"{analytics.summary()}\n"
    )
    return llm.build_system(persona, ctx)


def _dispatch(name: str, args: dict) -> str:  # инструментов нет — заглушка для рантайма
    return f"Неизвестный инструмент: {name}"


async def main() -> None:
    await agent_runtime.run(
        AGENT_NAME,
        tools_schema=[],
        dispatch=_dispatch,
        system_builder=_system,
        welcome=WELCOME,
        commands={},
    )
