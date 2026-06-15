"""Точка входа: запуск агента-Скаута.

    python run_scout.py

Нужны в .env: SCOUT_BOT_TOKEN и ANTHROPIC_API_KEY
(или свой SCOUT_ANTHROPIC_KEY для автономного учёта расходов).
"""
import asyncio

from core.scout_bot import main

if __name__ == "__main__":
    asyncio.run(main())
