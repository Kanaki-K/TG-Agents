"""РАЗОВЫЙ вход вручную — запусти ЭТОТ файл в СВОЁМ терминале.

Зачем: получить «строку сессии» Telegram у себя (где Telegram тебе доверяет),
чтобы не логиниться из рабочей среды. Строку пришлёшь — вставим в .env.

Подготовка (один раз):
    pip install telethon

Запуск:
    python make_session.py

Скрипт спросит api_id, api_hash, телефон и код из Telegram (и пароль 2FA,
если он у тебя есть), затем напечатает длинную строку сессии. Скопируй её ВСЮ.

ВНИМАНИЕ: строка сессии = доступ к твоему аккаунту. Никому не показывай,
кроме как вставить в .env (он в git не попадает). Отозвать можно в
Telegram → Настройки → Устройства.
"""
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("api_id (число): ").strip())
api_hash = input("api_hash (строка): ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("\n=== ТВОЯ СТРОКА СЕССИИ (скопируй её целиком и пришли) ===\n")
    print(client.session.save())
    print("\n=========================================================\n")
