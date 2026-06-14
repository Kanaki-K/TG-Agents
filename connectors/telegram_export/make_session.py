"""Полностью готовый файл. Ничего менять не нужно — просто запусти его.

Он сам поставит telethon (если её нет) и спросит:
  - телефон  -> введи +REDACTED
  - код из Telegram -> введи сразу, как придёт
  - (если есть) пароль 2FA
В конце напечатает СТРОКУ СЕССИИ — пришли её ассистенту.
"""
import subprocess
import sys

try:
    from telethon.sync import TelegramClient
    from telethon.sessions import StringSession
except ModuleNotFoundError:
    print("Ставлю telethon, подожди...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "telethon"])
    from telethon.sync import TelegramClient
    from telethon.sessions import StringSession

API_ID = REDACTED
API_HASH = "ROTATED_SEE_ENV"

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print("\n\n========== СТРОКА СЕССИИ — скопируй ВСЮ строку ниже ==========")
    print(client.session.save())
    print("========== и пришли её ассистенту ==========\n")
