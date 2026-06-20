"""Сборщик истории канала через Telegram Client API (MTProto, Telethon).

Под аккаунтом владельца читает ВСЕ посты канала с полной статистикой:
текст, дата, просмотры (views), репосты (forwards), реакции, число комментариев.

Разовый вход (создаёт файл сессии data/evgeniyp.session — это доступ к аккаунту,
держим строго локально, в git не попадает):
    python -m connectors.telegram_export.collect send-code     # Telegram пришлёт код
    python -m connectors.telegram_export.collect sign-in 12345 # код из Telegram

Сбор данных (можно повторять — дополняет базу):
    python -m connectors.telegram_export.collect collect       # → data/channel_posts.json
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError

from core import config

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SESSION = str(DATA / "evgeniyp")          # → data/evgeniyp.session (аккаунт ЕвгенийП / @Amanbabai228)
HASH_FILE = DATA / ".login_code_hash"
OUT = DATA / "channel_posts.json"


def _client() -> TelegramClient:
    DATA.mkdir(exist_ok=True)
    api_id = int(config.get_secret("TELEGRAM_API_ID"))
    api_hash = config.get_secret("TELEGRAM_API_HASH")
    # Если в .env есть готовая строка сессии (сделанная вручную через make_session.py)
    # — используем её и не логинимся здесь вообще.
    session_str = (os.getenv("TELEGRAM_SESSION") or "").strip()
    if session_str:
        from telethon.sessions import StringSession
        return TelegramClient(StringSession(session_str), api_id, api_hash)
    return TelegramClient(SESSION, api_id, api_hash)


async def send_code() -> None:
    client = _client()
    await client.connect()
    if await client.is_user_authorized():
        print("Уже авторизован — логин не нужен. Запускай: collect")
        await client.disconnect()
        return
    phone = config.get_secret("TELEGRAM_PHONE")
    try:
        sent = await client.send_code_request(phone)
    except FloodWaitError as e:
        print(f"Telegram просит подождать {e.seconds} сек перед новой отправкой кода.")
        await client.disconnect()
        return
    HASH_FILE.write_text(sent.phone_code_hash, encoding="utf-8")
    delivery = type(sent.type).__name__  # SentCodeTypeApp / ...Sms / ...Call / ...
    print(f"Код отправлен на {phone}. Способ доставки: {delivery}. "
          f"Дай его командой: sign-in <код>")
    await client.disconnect()


async def resend() -> None:
    """Попросить Telegram доставить код следующим способом (обычно SMS)."""
    from telethon.tl.functions.auth import ResendCodeRequest
    client = _client()
    await client.connect()
    phone = config.get_secret("TELEGRAM_PHONE")
    code_hash = HASH_FILE.read_text(encoding="utf-8").strip()
    try:
        sent = await client(ResendCodeRequest(phone_number=phone, phone_code_hash=code_hash))
    except FloodWaitError as e:
        print(f"Telegram просит подождать {e.seconds} сек перед повтором.")
        await client.disconnect()
        return
    HASH_FILE.write_text(sent.phone_code_hash, encoding="utf-8")
    print(f"Повторно отправлено. Способ доставки: {type(sent.type).__name__}. "
          f"Дай код: sign-in <код>")
    await client.disconnect()


async def sign_in(code: str) -> None:
    client = _client()
    await client.connect()
    phone = config.get_secret("TELEGRAM_PHONE")
    code_hash = HASH_FILE.read_text(encoding="utf-8").strip()
    try:
        await client.sign_in(phone, code=code, phone_code_hash=code_hash)
    except SessionPasswordNeededError:
        pwd = (os.getenv("TELEGRAM_2FA") or "").strip()
        if not pwd:
            print("На аккаунте включён облачный пароль (2FA). "
                  "Впиши его в .env как TELEGRAM_2FA и повтори sign-in.")
            await client.disconnect()
            return
        await client.sign_in(password=pwd)
    me = await client.get_me()
    print(f"Авторизован как {me.first_name} (@{me.username}). "
          f"Сессия сохранена. Запускай: collect")
    await client.disconnect()


async def _find_channel(client: TelegramClient):
    target = (os.getenv("TELEGRAM_CHANNEL") or "KANAKI CRYPTO").strip()
    uname = target.lstrip("@").lower()
    async for d in client.iter_dialogs():
        if not d.is_channel:
            continue
        if d.name == target or (getattr(d.entity, "username", None) or "").lower() == uname:
            return d.entity
    raise SystemExit(f"Канал '{target}' не найден среди твоих диалогов. "
                     f"Проверь TELEGRAM_CHANNEL в .env.")


async def collect() -> None:
    client = _client()
    await client.connect()
    if not await client.is_user_authorized():
        print("Не авторизован. Сначала: send-code → sign-in <код>")
        await client.disconnect()
        return
    channel = await _find_channel(client)
    posts: list[dict] = []
    async for m in client.iter_messages(channel):
        reactions = []
        if m.reactions:
            for r in m.reactions.results:
                emoji = getattr(r.reaction, "emoticon", None) \
                    or getattr(r.reaction, "document_id", None)
                reactions.append({"emoji": emoji, "count": r.count})
        posts.append({
            "id": m.id,
            "date": m.date.isoformat() if m.date else None,
            "text": m.message or "",
            "views": m.views,
            "forwards": m.forwards,
            "reactions": reactions,
            "likes_total": sum(r["count"] for r in reactions),
            "comments": m.replies.replies if m.replies else None,
            "has_media": m.media is not None,
        })
    OUT.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Собрано постов: {len(posts)} → {OUT}")
    await client.disconnect()


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "send-code":
        asyncio.run(send_code())
    elif cmd == "resend":
        asyncio.run(resend())
    elif cmd == "sign-in" and len(sys.argv) > 2:
        asyncio.run(sign_in(sys.argv[2]))
    elif cmd == "collect":
        asyncio.run(collect())
    else:
        print("Команды: send-code | sign-in <код> | collect")


if __name__ == "__main__":
    main()
