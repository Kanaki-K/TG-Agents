"""Сборщик custom_emoji_id из премиум-паков Telegram.

Зачем: чтобы бот мог показывать кастомные эмодзи (через <tg-emoji emoji-id=...>),
ему нужно знать id каждого эмодзи. Из картинки/ссылки на пак их не достать — id
живут только внутри Telegram. Этот мини-бот читает их из присланного сообщения.

Как пользоваться (разово):
  1. Останови криейтор-бота, если запущен (этот скрипт берёт тот же токен).
  2. python -m connectors.telegram_emoji.collect_ids
  3. Открой чат с ботом и пришли ОДНИМ-двумя сообщениями кастомные эмодзи из паков
     (нужен Telegram Premium, чтобы их отправить).
  4. Бот ответит «эмодзи → id» и сохранит карту в data/custom_emoji.json.
  5. Ctrl+C. Запусти криейтора снова — драфты будут приходить с кастом-иконками.

Можно задать отдельный токен EMOJI_BOT_TOKEN в .env, тогда останавливать
криейтора не нужно.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.types import Message

from core import config

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "custom_emoji.json"

dp = Dispatcher()


def _load() -> dict:
    if OUT.exists():
        try:
            return json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(data: dict) -> None:
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@dp.message()
async def collect(m: Message) -> None:
    text = m.text or m.caption or ""
    entities = m.entities or m.caption_entities or []
    found: dict[str, str] = {}
    for e in entities:
        if e.type == "custom_emoji" and e.custom_emoji_id:
            # extract_from корректно режет по UTF-16 offset/length и отдаёт сам эмодзи-дублёр
            emoji = e.extract_from(text)
            found[emoji] = str(e.custom_emoji_id)
    if not found:
        await m.answer(
            "Не вижу кастомных эмодзи. Пришли премиум-эмодзи из пака "
            "(нужен Telegram Premium, чтобы их отправить)."
        )
        return
    data = _load()
    data.update(found)
    _save(data)
    lines = "\n".join(f"{em} → {cid}" for em, cid in found.items())
    await m.answer(
        f"Собрал и сохранил:\n{lines}\n\nВсего в карте: {len(data)}. "
        "Файл: data/custom_emoji.json"
    )


async def main() -> None:
    token = config.get_optional("EMOJI_BOT_TOKEN") or config.get_secret("CREATOR_BOT_TOKEN")
    bot = Bot(token)
    print("Сборщик id эмодзи запущен. Открой чат с ботом и пришли эмодзи из пака. "
          "Ctrl+C — остановить.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
