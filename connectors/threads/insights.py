"""Метрики Threads: по посту и по аккаунту → нормализация в общий вид.

Формат ответа insights у Meta: {"data":[{"name":"views","period":..,"values":[{"value":N}]
или "total_value":{"value":N}}, ...]}. Парсер терпим к обоим вариантам.

⚠ Два подтверждённых риска (проверить на живом ключе):
- ГЛУБИНА ИСТОРИИ: метрики есть примерно с апреля 2024 (запуск сбора). Запрос за более
  ранний период вернёт пусто — это не баг.
- ДЕМОГРАФИЯ и followers_count требуют ≥100 подписчиков + привязку к Instagram; иначе
  метрика может не прийти. Поэтому demographics вынесены отдельно и ошибка не роняет остальное.
"""
from __future__ import annotations

from connectors.threads import _api, auth

# Метрики уровня поста (period=lifetime).
MEDIA_METRICS = ["views", "likes", "replies", "reposts", "quotes", "shares"]
# Метрики уровня аккаунта (временной ряд по since/until, кроме followers_count).
ACCOUNT_METRICS = ["views", "likes", "replies", "reposts", "quotes", "followers_count"]


def _value(item: dict):
    """Достать число из метрики: total_value, иначе сумма values[].value."""
    if isinstance(item.get("total_value"), dict):
        return item["total_value"].get("value")
    vals = item.get("values") or []
    nums = [v.get("value") for v in vals if isinstance(v, dict) and isinstance(v.get("value"), (int, float))]
    return sum(nums) if nums else None


def _parse(payload: dict) -> dict:
    out: dict = {}
    for item in payload.get("data") or []:
        name = item.get("name")
        if name:
            out[name] = _value(item)
    return out


def media_insights(media_id: str) -> dict:
    """Метрики одного поста: {views, likes, replies, reposts, quotes, shares}."""
    token = auth.valid_token()
    payload = _api.get(f"{media_id}/insights", {"metric": ",".join(MEDIA_METRICS)}, token=token)
    return _parse(payload)


def metrics_for(media_ids: list[str]) -> dict[str, dict]:
    """Метрики для набора постов: {media_id: {метрики}}. Ошибка по ОДНОМУ не роняет остальные.

    Но ThreadsBlocked (защита: троттлинг/бюджет/закрытая сеть) НЕ ловим — он обязан пробить цикл
    наверх. Раньше здесь было `except ThreadsError` на всё: при лимите цикл 500 раз подряд получал
    отказ, 500 раз его проглатывал и шёл дальше — то есть ускорялся ровно тогда, когда надо было
    остановиться. Кто зовёт — сохраняет то, что успел (см. collect._merge_keep).
    """
    result: dict[str, dict] = {}
    for mid in media_ids:
        try:
            result[mid] = media_insights(mid)
        except _api.ThreadsBlocked:
            raise
        except _api.ThreadsError as e:
            result[mid] = {"error": str(e)}
    return result


def account_insights(since: int | None = None, until: int | None = None) -> dict:
    """Метрики аккаунта за период (since/until — Unix-время). followers_count — суммарно."""
    token = auth.valid_token()
    uid = auth.user_id()
    payload = _api.get(f"{uid}/threads_insights", {
        "metric": ",".join(ACCOUNT_METRICS),
        "since": since,
        "until": until,
    }, token=token)
    return _parse(payload)


def follower_demographics(breakdown: str = "country") -> dict:
    """Демография подписчиков. Требует ≥100 подписчиков + привязку к Instagram.

    breakdown: country | city | age | gender. Возвращает {значение: число} или {'error': ...}.
    """
    token = auth.valid_token()
    uid = auth.user_id()
    try:
        payload = _api.get(f"{uid}/threads_insights", {
            "metric": "follower_demographics",
            "breakdown": breakdown,
        }, token=token)
    except _api.ThreadsError as e:
        return {"error": str(e)}
    for item in payload.get("data") or []:
        if item.get("name") == "follower_demographics":
            tv = item.get("total_value") or {}
            return {b.get("dimension_values", ["?"])[0]: b.get("value")
                    for b in (tv.get("breakdowns") or [{}])[0].get("results", [])}
    return {}
