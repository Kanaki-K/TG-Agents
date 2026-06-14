"""Telegram-бот личного ассистента (aiogram). v0: текст + память.

Запуск: python main.py  (нужны TELEGRAM_BOT_TOKEN и ANTHROPIC_API_KEY в .env)
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from core import config, llm, memory

logging.basicConfig(level=logging.INFO)

AGENT = config.load_agent("personal-assistant")
MODEL = AGENT["model"]

# Короткая история диалога в памяти процесса, по пользователю.
# Перезапуск бота её обнуляет — это нормально: знания живут в /memory.
_history: dict[int, list] = {}

dp = Dispatcher()


def _system() -> str:
    ctx = (
        f"## Профиль владельца\n{memory.read_profile()}\n\n"
        f"## Открытые задачи\n{memory.list_tasks()}\n"
    )
    return llm.build_system(AGENT["persona"], ctx)


@dp.message(Command("start"))
async def start(m: Message) -> None:
    await m.answer(
        "Привет! Я твой личный ассистент. Скидывай мысли и задачи — "
        "разложу, запомню и помогу спланировать.\n"
        "Команды: /tasks — задачи, /summary — итог сессии."
    )


@dp.message(Command("tasks"))
async def tasks(m: Message) -> None:
    await m.answer(memory.list_tasks())


@dp.message(Command("summary"))
async def summary(m: Message) -> None:
    uid = m.from_user.id
    text, hist = await asyncio.to_thread(
        llm.reply, MODEL, _system(), _history.get(uid, []),
        "Подведи короткий итог нашей сессии и запиши его в журнал (append_journal).",
    )
    _history[uid] = hist[-12:]
    await m.answer(text or "Готово.")


@dp.message()
async def chat(m: Message) -> None:
    uid = m.from_user.id
    await m.bot.send_chat_action(m.chat.id, "typing")
    text, hist = await asyncio.to_thread(
        llm.reply, MODEL, _system(), _history.get(uid, []), m.text or ""
    )
    _history[uid] = hist[-12:]  # держим короткий хвост диалога
    await m.answer(text or "…")


async def main() -> None:
    bot = Bot(config.get_secret(AGENT["token_env"]))
    await dp.start_polling(bot)
