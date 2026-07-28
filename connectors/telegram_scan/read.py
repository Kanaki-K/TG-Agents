"""Чтение свежих сообщений ТГ-каналов (Тир-3, по трекам crypto/ai) через MTProto.

Переиспользует MTProto-сессию коннектора telegram_export (TELEGRAM_SESSION /
data/mtproto.session). Список каналов — в channels.yaml (сгруппирован по трекам).

Синхронная обёртка `recent()` гоняет Telethon в собственном event loop — её зовут
из рабочего потока Скаута (asyncio.to_thread), где запущенного loop нет.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import yaml
from telethon.errors import FloodWaitError

from connectors.telegram_export.collect import _client

HERE = Path(__file__).resolve().parent
CHANNELS_FILE = HERE / "channels.yaml"
if not CHANNELS_FILE.exists():                     # свежий клон: падаем на шаблон-пример
    CHANNELS_FILE = HERE / "channels.example.yaml"
TRACKS = ("crypto", "ai")

PAUSE_BETWEEN = 1.0  # сек между каналами — вежливый темп, не похоже на флуд-бота


def load_channels() -> list[dict]:
    """Плоский список каналов с треком: [{name, track}, ...]."""
    if not CHANNELS_FILE.exists():
        return []
    data = yaml.safe_load(CHANNELS_FILE.read_text(encoding="utf-8")) or {}
    out: list[dict] = []
    for track in TRACKS:
        for name in data.get(track, []) or []:
            out.append({"name": name, "track": track})
    return out


async def _collect(channels: list[dict], limit: int) -> list[dict]:
    client = _client()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return [{"error": "MTProto-сессия не авторизована — задай TELEGRAM_SESSION в .env "
                              "или сделай вход (connectors/telegram_export)."}]
        items: list[dict] = []
        for i, ch in enumerate(channels):
            name, track = ch["name"], ch["track"]
            if i:
                await asyncio.sleep(PAUSE_BETWEEN)  # не долбим Telegram залпом
            try:
                async for msg in client.iter_messages(name, limit=limit):
                    text = (msg.message or "").strip()
                    if not text:
                        continue
                    items.append({
                        "channel": name,
                        "track": track,
                        "id": getattr(msg, "id", None),  # стабильная идентичность для watermark Скаута
                        "date": msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else "",
                        "text": text[:400],
                    })
            except FloodWaitError as e:
                # Telegram просит паузу — останавливаем скан целиком, чтобы не словить лимит/бан
                items.append({"channel": name, "track": track,
                              "error": f"Telegram просит паузу {e.seconds}s — скан остановлен ради безопасности аккаунта"})
                break
            except Exception as e:  # канал недоступен/приватный — не роняем остальные
                items.append({"channel": name, "track": track, "error": str(e)})
        return items
    finally:
        await client.disconnect()


def recent(limit_per_channel: int = 5, channel: str = "", track: str = "") -> list[dict]:
    """Свежие сообщения ТГ-каналов Тир-3.

    track — фильтр по треку ('crypto' | 'ai'), channel — по имени канала (подстрока).
    """
    channels = load_channels()
    if track:
        channels = [c for c in channels if c["track"] == track.lower()]
    if channel:
        channels = [c for c in channels if channel.lower() in c["name"].lower()]
    if not channels:
        return [{"error": "Список ТГ-каналов пуст (channels.yaml) или нет под фильтр."}]
    return asyncio.run(_collect(channels, max(1, min(limit_per_channel, 15))))


def diagnose() -> str:
    """Диагностика: по КАЖДОМУ каналу — прочитался (сколько сообщений) или ТОЧНАЯ ошибка.

    Скаут схлопывает ошибки в «не прочитаны» — здесь видно правду по каждому каналу отдельно.
    Запуск: python -m connectors.telegram_scan.read
    """
    channels = load_channels()
    items = asyncio.run(_collect(channels, 3))
    ok: dict[str, int] = {}
    errors: dict[str, str] = {}
    for it in items:
        ch = it.get("channel", "?")
        if it.get("error"):
            errors[ch] = it["error"]
        else:
            ok[ch] = ok.get(ch, 0) + 1
    lines = [f"=== TG-диагностика: {len(channels)} каналов ==="]
    for c in channels:
        name = c["name"]
        if name in errors:
            lines.append(f"  ❌ {name} [{c['track']}] — {errors[name]}")
        elif name in ok:
            lines.append(f"  ✅ {name} [{c['track']}] — прочитано {ok[name]} сообщ.")
        else:
            lines.append(f"  ⚠️ {name} [{c['track']}] — 0 сообщений (пусто / только медиа без текста)")
    live = len(ok)
    lines.append(f"\nИТОГ: живых {live}/{len(channels)}, с ошибкой {len(errors)}, пустых "
                 f"{len(channels) - live - len(errors)}.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(diagnose())
