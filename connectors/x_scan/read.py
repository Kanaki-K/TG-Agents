"""Чтение свежих твитов лидеров мнений в X (Twitter) — «руки» Скаута, его эдж.

X не индексируется веб-поиском и недоступен дип-ресёрчу — это и есть преимущество
Скаута: первичные голоса (Arthur Hayes, Lyn Alden, ...) появляются тут РАНЬШЕ
блога/RSS. Доступ — read-only через СЕССИЮ расходного (бёрнер) аккаунта (twikit,
НЕ платный API). Авторизация по cookies из браузера: auth_token + ct0
(см. .env.example и login.py). Список лидеров — в leaders.yaml (по трекам crypto/ai).

Безопасность бёрнера: каждый аккаунт читается изолированно (сбой одного не роняет
остальных), вежливый темп между запросами, остановка скана при рейт-лимите — чтобы
не словить заморозку. Только чтение, малый объём.

Синхронная обёртка `recent()` гоняет twikit в собственном event loop (как
telegram_scan) — её зовут из рабочего потока Скаута (asyncio.to_thread).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from core import config  # импорт грузит .env (load_dotenv) и даёт доступ к секретам

HERE = Path(__file__).resolve().parent
LEADERS_FILE = HERE / "leaders.yaml"
COOKIES_FILE = HERE.parents[1] / "data" / "x_cookies.json"
TRACKS = ("crypto", "ai")

PAUSE_BETWEEN = 2.0  # сек между аккаунтами — вежливый темп, бережём бёрнер от рейт-лимита


def load_leaders() -> list[dict]:
    """Плоский список лидеров с треком: [{handle, track}, ...]."""
    if not LEADERS_FILE.exists():
        return []
    data = yaml.safe_load(LEADERS_FILE.read_text(encoding="utf-8")) or {}
    out: list[dict] = []
    for track in TRACKS:
        for handle in data.get(track, []) or []:
            out.append({"handle": str(handle).lstrip("@").strip(), "track": track})
    return out


def _make_client():
    """twikit-клиент с cookies бёрнера. Возвращает (client, None) или (None, текст ошибки).

    Источник cookies (по приоритету): .env (X_AUTH_TOKEN + X_CT0) → файл data/x_cookies.json.
    Сам в аккаунт не логинимся (через Google/пароль twikit не ходит) — работаем по готовой сессии.
    """
    try:
        from twikit import Client
    except ImportError:
        return None, "twikit не установлен — добавь в окружение: pip install twikit"
    from connectors.x_scan import _twikit_patch
    _twikit_patch.apply()  # чиним сломанный апстримом get_indices (см. _twikit_patch.py)
    client = Client("en-US")
    auth_token = config.get_optional("X_AUTH_TOKEN")
    ct0 = config.get_optional("X_CT0")
    if auth_token and ct0:
        client.set_cookies({"auth_token": auth_token, "ct0": ct0})
        return client, None
    if COOKIES_FILE.exists():
        client.load_cookies(str(COOKIES_FILE))
        return client, None
    return None, ("X-сессия не задана. Впиши в .env cookies бёрнера X_AUTH_TOKEN и X_CT0 "
                  "(из браузера, где залогинен расходный аккаунт) — см. login.py.")


def _fmt_date(tw) -> str:
    dt = getattr(tw, "created_at_datetime", None)
    if dt is not None:
        try:
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    return str(getattr(tw, "created_at", "") or "")


async def _collect(leaders: list[dict], limit: int) -> list[dict]:
    client, err = _make_client()
    if err:
        return [{"error": err}]
    try:  # класс рейт-лимита — чтобы остановить скан и не злить X
        from twikit.errors import TooManyRequests
    except Exception:
        TooManyRequests = ()  # type: ignore[assignment]

    items: list[dict] = []
    for i, ld in enumerate(leaders):
        handle, track = ld["handle"], ld["track"]
        if i:
            await asyncio.sleep(PAUSE_BETWEEN)  # не долбим X залпом
        try:
            user = await client.get_user_by_screen_name(handle)
            tweets = await user.get_tweets("Tweets", count=max(limit, 5))
            taken = 0
            for tw in tweets:
                if getattr(tw, "retweeted_tweet", None):  # чистые ретвиты — шум, пропускаем
                    continue
                text = (getattr(tw, "full_text", None) or getattr(tw, "text", "") or "").strip()
                if not text:
                    continue
                items.append({
                    "handle": handle,
                    "track": track,
                    "date": _fmt_date(tw),
                    "text": text[:500],
                    "likes": getattr(tw, "favorite_count", None),
                    "retweets": getattr(tw, "retweet_count", None),
                    "views": getattr(tw, "view_count", None),
                    "url": f"https://x.com/{handle}/status/{getattr(tw, 'id', '')}",
                })
                taken += 1
                if taken >= limit:
                    break
        except TooManyRequests:
            items.append({"handle": handle, "track": track,
                          "error": "X просит паузу (рейт-лимит) — скан остановлен ради безопасности бёрнера"})
            break
        except Exception as e:  # аккаунт не найден/защищён/сеть — не роняем остальных
            items.append({"handle": handle, "track": track, "error": str(e)})
    return items


async def _collect_following(count: int) -> list[dict]:
    client, err = _make_client()
    if err:
        return [{"error": err}]
    try:
        me = await client.user()
        following = await client.get_user_following(me.id, count=count)
    except Exception as e:
        return [{"error": f"Не удалось получить список подписок: {e}"}]
    out: list[dict] = []
    for u in following:
        out.append({
            "handle": getattr(u, "screen_name", "?"),
            "name": getattr(u, "name", ""),
            "followers": getattr(u, "followers_count", None),
            "description": (getattr(u, "description", "") or "").replace("\n", " ")[:160],
        })
    return out


def following(count: int = 100) -> list[dict]:
    """Список аккаунтов, на которые подписан бёрнер — чтобы скурировать leaders.yaml.

    Разовая выгрузка: владелец смотрит/присылает, мы отбираем сильные в leaders.yaml.
    """
    return asyncio.run(_collect_following(max(1, min(count, 200))))


def recent(limit_per_account: int = 6, handle: str = "", track: str = "") -> list[dict]:
    """Свежие твиты лидеров мнений в X.

    track — фильтр по треку ('crypto' | 'ai'), handle — по имени аккаунта (подстрока).
    """
    leaders = load_leaders()
    if track:
        leaders = [l for l in leaders if l["track"] == track.lower()]
    if handle:
        h = handle.lstrip("@").lower()
        leaders = [l for l in leaders if h in l["handle"].lower()]
    if not leaders:
        return [{"error": "Список лидеров X пуст (leaders.yaml) или ничего не подошло под фильтр."}]
    return asyncio.run(_collect(leaders, max(1, min(limit_per_account, 15))))
