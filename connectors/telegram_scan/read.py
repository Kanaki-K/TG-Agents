"""Чтение свежих сообщений ТГ-каналов (Тир-3) через MTProto — для разведки Скаута.

Переиспользует MTProto-сессию коннектора telegram_export (TELEGRAM_SESSION /
data/kanaki.session). Список каналов — в channels.yaml.

Синхронная обёртка `recent()` гоняет Telethon в собственном event loop — её зовут
из рабочего потока Скаута (asyncio.to_thread), где запущенного loop нет.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from connectors.telegram_export.collect import _client

HERE = Path(__file__).resolve().parent
CHANNELS_FILE = HERE / "channels.yaml"


def load_channels() -> list[str]:
    if not CHANNELS_FILE.exists():
        return []
    data = yaml.safe_load(CHANNELS_FILE.read_text(encoding="utf-8")) or {}
    return data.get("channels", [])


async def _collect(channels: list[str], limit: int) -> list[dict]:
    client = _client()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return [{"error": "MTProto-сессия не авторизована — задай TELEGRAM_SESSION в .env "
                              "или сделай вход (connectors/telegram_export)."}]
        items: list[dict] = []
        for ch in channels:
            try:
                async for msg in client.iter_messages(ch, limit=limit):
                    text = (msg.message or "").strip()
                    if not text:
                        continue
                    items.append({
                        "channel": ch,
                        "date": msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else "",
                        "text": text[:400],
                    })
            except Exception as e:  # канал недоступен/приватный — не роняем остальные
                items.append({"channel": ch, "error": str(e)})
        return items
    finally:
        await client.disconnect()


def recent(limit_per_channel: int = 5, channel: str = "") -> list[dict]:
    """Свежие сообщения ТГ-каналов Тир-3. channel — необязательный фильтр (подстрока имени)."""
    channels = load_channels()
    if channel:
        channels = [c for c in channels if channel.lower() in c.lower()]
    if not channels:
        return [{"error": "Список ТГ-каналов пуст (channels.yaml)."}]
    return asyncio.run(_collect(channels, max(1, min(limit_per_channel, 15))))
