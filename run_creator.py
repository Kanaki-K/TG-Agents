"""Точка входа: запуск агента-Криейтора.

    python run_creator.py

Нужны в .env: CREATOR_BOT_TOKEN и ANTHROPIC_API_KEY
(или свой CREATOR_ANTHROPIC_KEY для автономного учёта расходов).
"""
import asyncio

from core.creator_bot import main

if __name__ == "__main__":
    asyncio.run(main())
