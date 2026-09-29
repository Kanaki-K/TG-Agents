"""Сторож метрик Threads API: заметить день, когда Meta откроет подписки и заходы в профиль.

ЗАЧЕМ. Подписок и заходов в профиль НА ПОСТ в API сегодня нет — проверено перебором 09.09.2026.
Но список допустимых метрик Meta отдаёт САМА: на неизвестное имя метрики приходит ошибка, где
допустимые перечислены дословно («metric[0] must be one of the following values: clicks, likes,
quotes, replies, reposts, shares, views»). Значит нам не нужно ни следить за блогом Meta, ни
угадывать: раз в неделю спрашиваем заведомо несуществующую метрику и читаем список из ответа.

Появится в списке follows/profile_visits — сторож скажет об этом владельцу в тот же день, и вся
возня с ручным съёмом станет ненужной. Это дешевле любой автоматизации: один запрос в неделю,
чтение, без сессий и без браузера.

ЦЕНА ОШИБКИ НИЗКАЯ В ОБЕ СТОРОНЫ: не заметим — продолжим снимать руками; ложно заметим — увидим
на первом же сборе. Поэтому сторож молчит, пока список не ИЗМЕНИЛСЯ, и не спорит с API.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from core import config, content_plan, io_safe

STATE = config.ROOT / "data" / "threads_metric_watch.json"
_PROBE = "___probe___"          # заведомо несуществующее имя метрики: ответ вернёт список допустимых
_LIST = re.compile(r"must be one of the following values:\s*([a-z_,\s]+)", re.I)

# То, ради чего сторож стоит: метрики, замыкающие воронку «увидел → зашёл → подписался».
WANTED = ("follows", "followers", "new_followers", "profile_visits", "profile_views",
          "unique_views", "viewers", "reach")


def _allowed(level: str) -> set[str]:
    """Спросить у Meta список допустимых метрик уровня 'media' или 'account'. Один запрос."""
    from connectors.threads import _api, auth
    token = auth.valid_token()
    uid = auth.user_id()
    if level == "account":
        path, params = f"{uid}/threads_insights", {"metric": _PROBE}
    else:
        posts = io_safe.load_json(config.ROOT / "data" / "threads_posts.json", [])
        if not posts:
            return set()
        path, params = f"{posts[-1]['id']}/insights", {"metric": _PROBE}
    try:
        _api.get(path, params, token=token)
    except Exception as e:  # noqa: BLE001 — ошибка здесь ОЖИДАЕМА, в ней и лежит ответ
        m = _LIST.search(str(e))
        if m:
            return {x.strip() for x in m.group(1).split(",") if x.strip()}
        raise
    return set()                                  # ответ без ошибки — значит имя вдруг валидно


def check() -> str:
    """Сверить списки метрик с прошлым разом. Возвращает текст для владельца ('' — без изменений)."""
    state = io_safe.load_json(STATE, {})
    news = []
    for level in ("media", "account"):
        try:
            now = _allowed(level)
        except Exception:  # noqa: BLE001 — сторож не имеет права уронить прогон
            logging.getLogger(__name__).warning("сторож метрик: уровень %s не спросился", level,
                                                exc_info=True)
            continue
        if not now:
            continue
        was = set(state.get(level, {}).get("metrics") or [])
        added, gone = sorted(now - was), sorted(was - now)
        state[level] = {"metrics": sorted(now),
                        "checked": datetime.now(content_plan.tz()).isoformat(timespec="seconds")}
        if was and added:
            hot = [a for a in added if a in WANTED]
            news.append(f"🎉 Threads API ({level}): НОВЫЕ метрики — {', '.join(added)}"
                        + (f"\n   Из них нужные нам: {', '.join(hot)}. Ручной съём можно снимать "
                           "с повестки — забираем из API." if hot else ""))
        if was and gone:
            news.append(f"⚠️ Threads API ({level}): метрики ПРОПАЛИ — {', '.join(gone)}. "
                        "Сбор может начать возвращать пустые поля.")
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return "\n".join(news)


def status() -> str:
    state = io_safe.load_json(STATE, {})
    if not state:
        return "Сторож метрик ещё не запускался."
    out = []
    for level, row in state.items():
        out.append(f"{level}: {', '.join(row.get('metrics') or [])} (проверено {row.get('checked','?')[:16]})")
        missing = [w for w in WANTED if w not in (row.get("metrics") or [])]
        out.append(f"   нужного нам всё ещё нет: {', '.join(missing)}")
    return "\n".join(out)


if __name__ == "__main__":
    print(check() or "Список метрик не изменился.")
    print()
    print(status())
