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
import json
import logging
from datetime import date
from typing import Callable

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message

from core import config, llm, tg_format

logging.basicConfig(level=logging.INFO)


# --- Простой планировщик: запускать пресет раз в N дней и слать владельцу в чат ---
# Состояние (дата прошлого прогона) и chat_id владельца лежат в data/ (вне git).
def _read_owner(path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip()) if path.exists() else None
    except Exception:
        return None


def _write_owner(path, chat_id: int) -> None:
    try:
        path.parent.mkdir(exist_ok=True)
        path.write_text(str(chat_id), encoding="utf-8")
    except Exception:
        logging.exception("Не смог сохранить chat владельца")


def _read_run_date(path):
    try:
        if path.exists():
            return date.fromisoformat(json.loads(path.read_text(encoding="utf-8"))["last"])
    except Exception:
        pass
    return None


def _write_run_date(path, d: date) -> None:
    try:
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"last": d.isoformat()}), encoding="utf-8")
    except Exception:
        logging.exception("Не смог записать дату прогона")


async def _periodic_loop(bot, agent_name, spec, model, system_builder,
                         tools_schema, dispatch, api_key) -> None:
    """Раз в spec['days'] дней гоняет spec['preset'] и шлёт результат владельцу.

    Перезапуск-устойчиво: дату прошлого прогона храним в файле, проверяем раз в час.
    Пока владелец ни разу не написал боту — не знаем chat_id, тихо ждём.
    """
    data_dir = config.ROOT / "data"
    state_file = data_dir / f"{agent_name}_{spec['key']}.json"
    owner_file = data_dir / f"{agent_name}_owner.txt"
    while True:
        await asyncio.sleep(spec.get("check_every", 3600))
        try:
            chat_id = _read_owner(owner_file)
            if not chat_id:
                continue
            last = _read_run_date(state_file)
            today = date.today()
            if last and (today - last).days < spec["days"]:
                continue
            logging.info("Периодический прогон '%s' агента %s", spec["key"], agent_name)
            text, _ = await asyncio.to_thread(
                llm.reply, model, system_builder(), [], spec["preset"],
                tools_schema, dispatch, api_key)
            for chunk in _chunks((spec.get("header", "") + (text or "…")).strip()):
                try:
                    await bot.send_message(chat_id, tg_format.strip_markdown(chunk)[:TG_LIMIT])
                except Exception:
                    logging.exception("Не смог отправить периодический отчёт")
            _write_run_date(state_file, today)
        except Exception:
            logging.exception("Периодический прогон не удался")


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


TG_LIMIT = 4096          # жёсткий лимит Telegram на длину сообщения
CHUNK = 3500             # режем с запасом: HTML-теги раздувают текст сверх исходного
SPLIT_MARK = "[[SPLIT]]" # агент ставит этот маркер, чтобы разбить ответ на ОТДЕЛЬНЫЕ сообщения


def _chunks(text: str, size: int = CHUNK) -> list[str]:
    """Разбить длинный текст на куски ≤ size, по границам строк (не рвём слова/теги).

    Очень длинную одиночную строку (напр. гигантский URL) режем жёстко.
    """
    out: list[str] = []
    cur = ""
    for line in text.split("\n"):
        while len(line) > size:                 # одиночная строка длиннее куска
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:size])
            line = line[size:]
        if cur and len(cur) + 1 + len(line) > size:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out or [text]


async def _send(m: Message, text: str) -> None:
    """Отправить ответ модели как Telegram-HTML, разбив длинный текст на части.

    Telegram режет сообщения на 4096 символов — длинные ответы шлём кусками.
    На каждый кусок: пробуем HTML; если разметка кривая (400) — шлём чистым
    текстом, чтобы ответ дошёл, а бот не упал.
    """
    parts = [p.strip() for p in text.split(SPLIT_MARK)] if SPLIT_MARK in text else [text]
    for part in parts:
        if not part:
            continue
        for chunk in _chunks(part):
            try:
                await m.answer(tg_format.to_telegram_html(chunk), parse_mode="HTML")
            except TelegramBadRequest:
                await m.answer(tg_format.strip_markdown(chunk)[:TG_LIMIT])


async def run(
    agent_name: str,
    *,
    tools_schema: list[dict],
    dispatch: Callable[[str, dict], str],
    system_builder: Callable[[], str],
    welcome: str,
    commands: dict[str, str] | None = None,
    periodic: dict | None = None,
) -> None:
    agent = config.load_agent(agent_name)
    model = agent["model"]
    api_key = config.agent_api_key(agent)   # свой ключ агента или общий
    commands = commands or {}
    history: dict[int, list] = {}   # короткий хвост диалога по пользователю
    busy: set[int] = set()          # пользователи с уже идущим запросом (защита от параллельного дубля)
    owner_file = config.ROOT / "data" / f"{agent_name}_owner.txt"  # куда слать проактивные отчёты
    dp = Dispatcher()

    async def _turn(m: Message, user_text: str) -> None:
        uid = m.from_user.id
        _write_owner(owner_file, m.chat.id)  # запоминаем чат для проактивных (еженедельных) отчётов
        # пустой/не-текстовый ввод не шлём в модель: Anthropic отклоняет пустой
        # user-content (400), да и отвечать не на что. Голос/фото — позже.
        if not (user_text or "").strip():
            await m.answer("Пока понимаю только текст — пришли, пожалуйста, сообщением.")
            return
        # один запрос на пользователя за раз: aiogram обрабатывает апдейты параллельно,
        # а долгий /scan (инструменты + веб-поиск) при повторном тапе запускался дважды
        # — два отчёта и порча общей истории. Пока занят — просим подождать.
        if uid in busy:
            await m.answer("Ещё думаю над прошлым запросом — секунду, отвечу по нему.")
            return
        busy.add(uid)
        try:
            await m.bot.send_chat_action(m.chat.id, "typing")
            # на входе чиним возможный «обрыв» tool_use/tool_result (лечит и старое состояние),
            prior = _trim_history(history.get(uid, []))
            text, hist = await asyncio.to_thread(
                llm.reply, model, system_builder(), prior,
                user_text, tools_schema, dispatch, api_key,
            )
            history[uid] = _trim_history(hist)
            await _send(m, text or "…")
        finally:
            busy.discard(uid)

    @dp.message(Command("start"))
    async def _start(m: Message) -> None:
        _write_owner(owner_file, m.chat.id)
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
    if periodic:
        asyncio.create_task(_periodic_loop(
            bot, agent_name, periodic, model, system_builder,
            tools_schema, dispatch, api_key))
        logging.info("Планировщик '%s' включён: раз в %s дн.", periodic.get("key"), periodic.get("days"))
    await dp.start_polling(bot)
