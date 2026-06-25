"""Общий инструмент живой цены (connectors/market) для Криейтора / 2FA-фактчека / Скаута.

Один бэкенд (connectors.market.price.spot) с единой схемой инструмента и dispatch — как
analytics_tools. Любой агент добавляет PRICE_TOOL в свой TOOLS и зовёт handle() в своём dispatch.
"""
from __future__ import annotations

from connectors.market import price

PRICE_TOOL = {
    "name": "market_price",
    "description": (
        "Текущая РЫНОЧНАЯ цена монет в USD прямо сейчас (CoinMarketCap, спот в реальном времени) + "
        "изменение за 24ч/7д и капитализация. Используй для ТОЧНОЙ сверки живых цен/процентов перед "
        "тем, как вписать их в пост или подтвердить факт — НЕ доверяй приблизительной/устаревшей цене "
        "из web_search. Тикеры через запятую."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbols": {
                "type": "string",
                "description": "Тикеры через запятую, напр. 'BTC' или 'BTC,ETH,SOL'. По умолчанию BTC,ETH.",
            },
        },
    },
}


def handle(name: str, args: dict):
    """Результат инструмента живой цены, либо None если имя не наше (агент обработает сам)."""
    if name == "market_price":
        return price.spot(args.get("symbols") or price.DEFAULT_SYMBOLS)
    return None
