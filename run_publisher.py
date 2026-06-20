"""Точка входа: запуск Публикатора.

    python run_publisher.py

Нужны в .env: PUBLISHER_BOT_TOKEN (бот от @BotFather), PUBLISH_CHANNEL (куда постить),
TELEGRAM_SESSION (сессия аккаунта-публикатора @Amanbabai228 — та же, что у аналитики).
Публикатор детерминированный — ключ Claude ему НЕ нужен.
"""
import asyncio

from core.publisher_bot import main

if __name__ == "__main__":
    asyncio.run(main())
