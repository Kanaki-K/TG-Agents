"""Точка входа: запуск агента-Разработчика.

    python run_dev.py

Нужны в .env: DEVELOPER_BOT_TOKEN и ANTHROPIC_API_KEY
(или свой DEVELOPER_ANTHROPIC_KEY для автономного учёта расходов).
"""
import asyncio

from core.dev_bot import main

if __name__ == "__main__":
    asyncio.run(main())
