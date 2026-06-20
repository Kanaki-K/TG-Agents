"""Вход в Telegram через QR — фоновый вариант (QR держит свежим автоматически).

Запуск:
    python -m connectors.telegram_export.qr_login

QR сохраняется в data/qr.png и обновляется сам. Статус — в data/qr_status.txt:
    WAITING   — ждём скан QR
    NEED_2FA  — QR отсканирован, нужен облачный пароль
    OK ...    — вошли, сессия сохранена
    TIMEOUT   — время вышло

Пароль 2FA берётся из .env (TELEGRAM_2FA), а если там пусто — скрипт ждёт
файл data/2fa.txt (туда пароль кладёт оркестратор/ассистент), читает и СРАЗУ удаляет.
По успеху сохраняет файл сессии data/evgeniyp.session → дальше collect.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from core import config

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SESSION = str(DATA / "evgeniyp")
PNG = DATA / "qr.png"
TXT = DATA / "qr.txt"
STATUS = DATA / "qr_status.txt"
TFA = DATA / "2fa.txt"


def _render(url: str) -> None:
    qr = qrcode.QRCode(border=2)
    qr.add_data(url)
    qr.make(fit=True)
    qr.make_image(fill_color="black", back_color="white").save(PNG)
    TXT.write_text(url + "\n", encoding="utf-8")


async def _await_2fa() -> str:
    """Пароль 2FA: из .env, иначе ждём файл data/2fa.txt (до ~5 минут)."""
    pwd = (os.getenv("TELEGRAM_2FA") or "").strip()
    if pwd:
        return pwd
    STATUS.write_text("NEED_2FA", encoding="utf-8")
    for _ in range(150):  # 150 * 2с = 5 минут
        if TFA.exists():
            pwd = TFA.read_text(encoding="utf-8").strip()
            try:
                TFA.unlink()  # пароль на диске не задерживаем
            except OSError:
                pass
            if pwd:
                return pwd
        await asyncio.sleep(2)
    raise SystemExit("Пароль 2FA не получен за 5 минут.")


async def main() -> None:
    DATA.mkdir(exist_ok=True)
    if TFA.exists():
        TFA.unlink()
    STATUS.write_text("WAITING", encoding="utf-8")
    api_id = int(config.get_secret("TELEGRAM_API_ID"))
    api_hash = config.get_secret("TELEGRAM_API_HASH")
    client = TelegramClient(SESSION, api_id, api_hash)
    await client.connect()

    if await client.is_user_authorized():
        STATUS.write_text("OK (уже был авторизован)", encoding="utf-8")
        await client.disconnect()
        return

    qr = await client.qr_login()
    _render(qr.url)

    authed = False
    for _ in range(40):  # ~12 минут
        try:
            await qr.wait(timeout=18)   # обновляем QR ДО истечения (~30с)
            authed = True
            break
        except asyncio.TimeoutError:
            await qr.recreate()
            _render(qr.url)
            continue
        except SessionPasswordNeededError:
            await client.sign_in(password=await _await_2fa())
            authed = True
            break

    if not authed:
        STATUS.write_text("TIMEOUT", encoding="utf-8")
        await client.disconnect()
        return

    me = await client.get_me()
    STATUS.write_text(f"OK {me.first_name} @{me.username}", encoding="utf-8")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
