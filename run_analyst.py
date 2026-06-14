"""Точка входа: запуск агента-аналитика канала.

    python run_analyst.py

Нужны в .env: ANALYST_BOT_TOKEN и ANTHROPIC_API_KEY.
Перед первым запуском собери метрики:
    python -m connectors.telegram_export.collect collect
    python -m connectors.telegram_export.collect_stats
"""
import asyncio

from core.analyst_bot import main

if __name__ == "__main__":
    asyncio.run(main())
