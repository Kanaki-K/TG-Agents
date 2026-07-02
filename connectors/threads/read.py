"""Чтение своих постов Threads — материал для анализа контента (как ТГ-канал у аналитика).

Отдаёт нормализованные записи постов; метрики к ним подцепляет insights.py, а таблицу
и разбор «что заходит» строит слой аналитики (веха 2.2). Здесь — только тяга и нормализация.
"""
from __future__ import annotations

from connectors.threads import _api, auth

# Поля поста, которые тянем. ⚠ ПРОВЕРИТЬ на живом ответе: часть аккаунтов может не
# отдавать отдельные поля (media_url и пр.) — берём безопасный минимум под анализ текста.
_FIELDS = "id,text,timestamp,permalink,media_type,shortcode,is_quote_post"

_HARD_CAP = 500   # предохранитель от бесконечной пагинации


def _normalize(item: dict) -> dict:
    return {
        "platform": "threads",
        "id": item.get("id", ""),
        "text": (item.get("text") or "").strip(),
        "timestamp": item.get("timestamp", ""),      # ISO-8601 от Meta
        "permalink": item.get("permalink", ""),
        "media_type": item.get("media_type", ""),    # TEXT_POST/IMAGE/VIDEO/CAROUSEL/REPOST_FACADE
        "is_quote": bool(item.get("is_quote_post")),
    }


def recent(limit: int = 25, since: int | None = None, until: int | None = None) -> list[dict]:
    """Свежие посты владельца (по убыванию даты). since/until — Unix-время (необязательно).

    Пагинация по курсору; тянем страницами по 100 до limit или конца ленты.
    """
    token = auth.valid_token()
    uid = auth.user_id()
    out: list[dict] = []
    after: str | None = None
    limit = max(1, min(int(limit), _HARD_CAP))

    while len(out) < limit:
        page = _api.get(f"{uid}/threads", {
            "fields": _FIELDS,
            "limit": min(100, limit - len(out)),
            "since": since,
            "until": until,
            "after": after,
        }, token=token)
        rows = page.get("data") or []
        out.extend(_normalize(r) for r in rows)
        after = ((page.get("paging") or {}).get("cursors") or {}).get("after")
        if not rows or not after:
            break
    return out[:limit]


def one(media_id: str) -> dict:
    """Один пост по id — нормализованный."""
    token = auth.valid_token()
    return _normalize(_api.get(media_id, {"fields": _FIELDS}, token=token))
