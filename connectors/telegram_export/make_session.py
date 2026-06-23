"""Помощник: генерирует СТРОКУ СЕССИИ MTProto (telethon) для аккаунта-публикатора.

Запусти из корня репозитория:  python connectors/telegram_export/make_session.py

Берёт api_id/api_hash из переменных окружения TELEGRAM_API_ID / TELEGRAM_API_HASH
(см. .env / .env.example). Если их нет — спросит ввести вручную. Никаких ключей в коде.
Дальше спросит:
  - телефон  -> введи свой номер в формате +<странакод><номер>
  - код из Telegram -> введи сразу, как придёт
  - (если есть) пароль 2FA
В конце напечатает СТРОКУ СЕССИИ — впиши её в .env как TELEGRAM_SESSION.
"""
import os
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

# Секреты только из окружения (или интерактивный ввод) — НЕ хардкодим в коде.
API_ID = os.getenv("TELEGRAM_API_ID") or input("TELEGRAM_API_ID: ").strip()
API_HASH = os.getenv("TELEGRAM_API_HASH") or input("TELEGRAM_API_HASH: ").strip()

with TelegramClient(StringSession(), int(API_ID), API_HASH) as client:
    print("\n\n========== СТРОКА СЕССИИ — скопируй ВСЮ строку ниже ==========")
    print(client.session.save())
    print("========== впиши её в .env как TELEGRAM_SESSION ==========\n")
