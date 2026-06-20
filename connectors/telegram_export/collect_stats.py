"""Сбор СВОДНОЙ статистики канала через админский Stats API (нужны права админа).

Тянет то, что Telegram прячет в приложении: рост подписчиков, источники подписок
и просмотров, лучшие часы, реакции по эмоциям, языки аудитории, отписки и т.д.

Запуск (аккаунт должен быть админом канала):
    python -m connectors.telegram_export.collect_stats   # → data/channel_stats.json
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.functions.stats import GetBroadcastStatsRequest, LoadAsyncGraphRequest
from telethon.tl.types import StatsGraph, StatsGraphAsync

from core import config

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SESSION = str(DATA / "evgeniyp")
OUT = DATA / "channel_stats.json"

# Графики, которые забираем (имя в API → понятное имя)
GRAPHS = {
    "growth_graph": "Рост аудитории",
    "followers_graph": "Подписки/отписки",
    "new_followers_by_source_graph": "Новые подписчики по источникам",
    "views_by_source_graph": "Просмотры по источникам",
    "languages_graph": "Языки аудитории",
    "top_hours_graph": "Активность по часам",
    "reactions_by_emotion_graph": "Реакции по эмоциям",
    "interactions_graph": "Просмотры и репосты",
    "mute_graph": "Отключения уведомлений",
}


def _pct(v):
    cur = getattr(v, "current", None)
    prev = getattr(v, "previous", None)
    if cur is None:
        return None
    out = {"current": cur, "previous": prev}
    if prev:
        out["change_pct"] = round((cur - prev) / prev * 100, 1)
    return out


async def _resolve(client, graph):
    """StatsGraphAsync → подгрузить; вернуть распарсенный JSON графика."""
    try:
        if isinstance(graph, StatsGraphAsync):
            graph = await client(LoadAsyncGraphRequest(token=graph.token))
        if isinstance(graph, StatsGraph):
            return json.loads(graph.json.data)
    except Exception as e:  # noqa: BLE001 — график мог быть пустым/недоступным
        return {"error": f"{type(e).__name__}: {e}"}
    return None


async def main() -> None:
    api_id = int(config.get_secret("TELEGRAM_API_ID"))
    api_hash = config.get_secret("TELEGRAM_API_HASH")
    target = (os.getenv("TELEGRAM_CHANNEL") or "").strip()
    client = TelegramClient(SESSION, api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("Не авторизован. Сначала вход (qr_login / login).")
        await client.disconnect()
        return

    entity = None
    async for d in client.iter_dialogs():
        if d.is_channel and (d.name == target
                             or (getattr(d.entity, "username", "") or "").lower()
                             == target.lstrip("@").lower()):
            entity = d.entity
            break
    if entity is None:
        print(f"Канал '{target}' не найден."); await client.disconnect(); return

    try:
        s = await client(GetBroadcastStatsRequest(channel=entity))
    except Exception as e:  # noqa: BLE001
        print(f"Stats API недоступен ({type(e).__name__}: {e}). "
              f"Нужны права админа и достаточно подписчиков.")
        await client.disconnect()
        return

    result = {
        "period": {
            "from": s.period.min_date.isoformat() if s.period else None,
            "to": s.period.max_date.isoformat() if s.period else None,
        },
        "headline": {
            "followers": _pct(s.followers),
            "views_per_post": _pct(s.views_per_post),
            "shares_per_post": _pct(s.shares_per_post),
            "reactions_per_post": _pct(getattr(s, "reactions_per_post", None)),
            "views_per_story": _pct(getattr(s, "views_per_story", None)),
            "enabled_notifications": getattr(getattr(s, "enabled_notifications", None), "part", None),
        },
        "graphs": {},
    }
    for api_name, human in GRAPHS.items():
        g = getattr(s, api_name, None)
        if g is None:
            continue
        result["graphs"][human] = await _resolve(client, g)

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    h = result["headline"]
    print("Сводная статистика собрана →", OUT)
    print(f"  подписчиков: {h['followers']['current'] if h['followers'] else '—'}")
    print(f"  просмотров/пост: {h['views_per_post']['current'] if h['views_per_post'] else '—'}")
    print(f"  графиков сохранено: {len(result['graphs'])}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
