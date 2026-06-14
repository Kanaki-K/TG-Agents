"""Точка входа: запуск личного ассистента.

    python main.py

Перед запуском заполни в .env: TELEGRAM_BOT_TOKEN и ANTHROPIC_API_KEY.
"""
import asyncio

from core.bot import main

if __name__ == "__main__":
    asyncio.run(main())
