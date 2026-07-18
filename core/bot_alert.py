"""Доставка health-алертов владельцу через Bot API (HTTPS + токен бота) — НЕЗАВИСИМО от MTProto.

Зачем (аудит N-45): stale-алерт «данные канала не обновляются» срабатывает чаще всего именно
потому, что MTProto-сессия истекла/забанена. А старый путь слал его через ТУ ЖЕ мёртвую сессию
(`telegram_publish.notify` → `_client()`), т.е. при реальном сбое владелец его не получал.
Bot API живёт на токене бота, к MTProto отношения не имеет → алерт дойдёт, даже когда сессия мертва.

Только для АЛЕРТОВ (короткий текст владельцу). Публикация постов — по-прежнему через MTProto.
stdlib urllib (без aiogram) — это разовый POST из скрипта пайплайна, не бот-процесс.
"""
from __future__ import annotations

import json
import logging
import urllib.request

from core import config

log = logging.getLogger(__name__)

# Порядок ботов для отправки — любой живой токен подойдёт (владелец их запускал → бот может ему писать).
_BOT_TOKEN_KEYS = ("CREATOR_BOT_TOKEN", "SCOUT_BOT_TOKEN", "ANALYST_BOT_TOKEN", "SECRETARY_BOT_TOKEN")


def _first_owner_id() -> str | None:
    raw = config.get_optional("OWNER_ID") or ""
    ids = [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]
    return ids[0] if ids else None


def _bot_token() -> str | None:
    for k in _BOT_TOKEN_KEYS:
        t = config.get_optional(k)
        if t:
            return t
    return None


def notify_owner(text: str, timeout: float = 10.0) -> bool:
    """Отправить владельцу через Bot API. True — ушло. НИКОГДА не бросает (алерт не должен ронять прогон)."""
    token, chat = _bot_token(), _first_owner_id()
    if not (token and chat):
        log.warning("[health] Bot-алерт НЕ отправлен: нет токена бота (%s) или OWNER_ID",
                    "/".join(_BOT_TOKEN_KEYS))
        return False
    try:
        data = json.dumps({"chat_id": chat, "text": text}).encode("utf-8")
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                     data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — фикс. хост api.telegram.org
            return 200 <= r.status < 300
    except Exception:  # noqa: BLE001 — сеть/токен: логируем, но прогон не роняем
        log.exception("[health] Bot-алерт владельцу не ушёл")
        return False
