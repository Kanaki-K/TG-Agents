"""Общий рантайм агента: aiogram-бот + цикл Claude с инструментами.

Один и тот же движок крутит любого агента — отличается только:
  - какой агент загружен (config.yaml + SKILL.md);
  - какие у него инструменты (tools_schema/dispatch);
  - как собирается системный контекст (system_builder);
  - приветствие и пресет-команды.

Слэш-команды реализованы как «пресет-промпты»: /report просто шлёт модели
заранее заданный запрос — модель сама дёргает нужные инструменты.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message

from core import config, llm, tg_format

logging.basicConfig(level=logging.INFO)


def _trim_history(hist: list, keep: int = 12) -> list:
    """Короткий хвост диалога, но обязательно начинающийся с «настоящего»
    хода пользователя (роль user + строковый content).

    Просто `hist[-keep:]` опасен: срез может попасть между `tool_use` и его
    `tool_result`, и тогда первым сообщением окажется `tool_result` без парного
    `tool_use` — Anthropic API отклоняет это с ошибкой 400. Поэтому после среза
    отбрасываем ведущие сообщения (assistant-ходы и блоки tool_result), пока в
    начале не окажется обычная реплика пользователя.
    """
    tail = hist[-keep:]
    while tail and not (tail[0].get("role") == "user"
                        and isinstance(tail[0].get("content"), str)):
        tail = tail[1:]
    return tail


async def _send(m: Message, text: str) -> None:
    """Отправить ответ модели, отрендерив Markdown как Telegram-HTML.

    Если разметка кривая и Telegram не смог её распарсить (400) — повторяем
    отправку чистым текстом, чтобы ответ дошёл, а бот не упал.
    """
    try:
        await m.answer(tg_format.to_telegram_html(text), parse_mode="HTML")
    except TelegramBadRequest:
        await m.answer(tg_format.strip_markdown(text))


async def run(
    agent_name: str,
    *,
    tools_schema: list[dict],
    dispatch: Callable[[str, dict], str],
    system_builder: Callable[[], str],
    welcome: str,
    commands: dict[str, str] | None = None,
) -> None:
    agent = config.load_agent(agent_name)
    model = agent["model"]
    api_key = config.agent_api_key(agent)   # свой ключ агента или общий
    commands = commands or {}
    history: dict[int, list] = {}   # короткий хвост диалога по пользователю
    dp = Dispatcher()

    async def _turn(m: Message, user_text: str) -> None:
        uid = m.from_user.id
        # пустой/не-текстовый ввод не шлём в модель: Anthropic отклоняет пустой
        # user-content (400), да и отвечать не на что. Голос/фото — позже.
        if not (user_text or "").strip():
            await m.answer("Пока понимаю только текст — пришли, пожалуйста, сообщением.")
            return
        await m.bot.send_chat_action(m.chat.id, "typing")
        # на входе чиним возможный «обрыв» tool_use/tool_result (лечит и старое состояние),
        prior = _trim_history(history.get(uid, []))
        text, hist = await asyncio.to_thread(
            llm.reply, model, system_builder(), prior,
            user_text, tools_schema, dispatch, api_key,
        )
        history[uid] = _trim_history(hist)
        await _send(m, text or "…")

    @dp.message(Command("start"))
    async def _start(m: Message) -> None:
        await m.answer(welcome)

    # пресет-команды: /<cmd> → заранее заданный промпт модели
    def _make_preset(preset: str):
        async def handler(m: Message) -> None:
            await _turn(m, preset)
        return handler

    for cmd, preset in commands.items():
        dp.message(Command(cmd))(_make_preset(preset))

    @dp.message()
    async def _chat(m: Message) -> None:
        await _turn(m, m.text or "")

    bot = Bot(config.get_secret(agent["token_env"]))
    logging.info("Запускаю агента '%s' (модель %s)", agent_name, model)
    await dp.start_polling(bot)
