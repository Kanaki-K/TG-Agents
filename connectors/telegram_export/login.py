"""Разовый вход в Telegram через QR — для запуска В КОНСОЛИ.

Самостоятельный скрипт (зависимости: telethon + qrcode, всё в твоём .venv).
Пароль 2FA вводится РУКАМИ в консоли скрытым вводом и НИГДЕ не сохраняется.

Запуск (Windows, из папки проекта):
    .venv\\Scripts\\python.exe -m pip install qrcode
    .venv\\Scripts\\python.exe connectors\\telegram_export\\login.py

Что делать: появится QR в консоли -> на телефоне нужным аккаунтом
Telegram -> Настройки -> Устройства -> «Подключить устройство» -> сканируй.
Если есть облачный пароль (2FA) — скрипт спросит его в консоли.

По успеху строка сессии сама запишется в .env (TELEGRAM_SESSION=...),
после чего сбор данных можно запускать командой collect.
"""
from __future__ import annotations

import asyncio
import re
from getpass import getpass
from pathlib import Path

import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / ".env"


def _read_env(name: str) -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == name:
            return v.strip().strip('"').strip("'")
    raise SystemExit(f"В .env не задан {name}. Заполни его и повтори.")


def _save_session(session_str: str) -> None:
    """Записать/заменить строку TELEGRAM_SESSION в .env, не трогая остальное."""
    lines = ENV.read_text(encoding="utf-8").splitlines()
    out, done = [], False
    for line in lines:
        if re.match(r"\s*#?\s*TELEGRAM_SESSION\s*=", line):
            out.append(f"TELEGRAM_SESSION={session_str}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"TELEGRAM_SESSION={session_str}")
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")


def _show_qr(url: str) -> None:
    qr = qrcode.QRCode(border=2)
    qr.add_data(url)
    qr.make(fit=True)
    print("\n" + "=" * 54)
    qr.print_ascii(invert=True)
    print("=" * 54)


async def main() -> None:
    api_id = int(_read_env("TELEGRAM_API_ID"))
    api_hash = _read_env("TELEGRAM_API_HASH")
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()

    qr = await client.qr_login()
    _show_qr(qr.url)
    print("Сканируй QR нужным аккаунтом (Настройки → Устройства → Подключить устройство). Жду...")

    for _ in range(40):  # ~12 минут
        try:
            await qr.wait(timeout=18)  # обновляем ДО истечения (~30с), чтобы QR всегда свежий
            break
        except asyncio.TimeoutError:
            await qr.recreate()
            _show_qr(qr.url)
            print("↑↑↑ СВЕЖИЙ QR — сканируй именно его (нижний), быстро.")
        except SessionPasswordNeededError:
            print("\n>>> На аккаунте включён облачный пароль (2FA).")
            pwd = getpass(">>> Введи пароль 2FA (ввод скрыт, нигде не сохранится): ").strip()
            await client.sign_in(password=pwd)
            break
    else:
        print("Время вышло — перезапусти скрипт.")
        await client.disconnect()
        return

    me = await client.get_me()
    session_str = client.session.save()
    _save_session(session_str)
    print(f"\n✅ Вошёл как {me.first_name} (@{me.username}).")
    print("Строка сессии записана в .env (TELEGRAM_SESSION). Пароль 2FA нигде не сохранён.")
    print("Готово — теперь можно собирать данные (collect).")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
