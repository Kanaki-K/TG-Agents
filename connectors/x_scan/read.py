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
import json
from datetime import date
from pathlib import Path

import yaml

from core import config  # импорт грузит .env (load_dotenv) и даёт доступ к секретам

HERE = Path(__file__).resolve().parent
LEADERS_FILE = HERE / "leaders.yaml"               # семя: курируемый владельцем стартовый ростер
LEDGER_FILE = HERE.parents[1] / "memory" / "x_authors.json"  # источник правды: тиры + история проверок
COOKIES_FILE = HERE.parents[1] / "data" / "x_cookies.json"
TRACKS = ("crypto", "ai")

# Тиры качества автора. scan_x по умолчанию читает только «эталон».
TIERS = ("эталон", "тир2", "кандидат", "отклонён")
SCAN_DEFAULT_TIERS = ("эталон",)

PAUSE_BETWEEN = 2.0  # сек между аккаунтами — вежливый темп, бережём бёрнер от рейт-лимита


def _seed_universe() -> list[dict]:
    """Хэндлы-семена из leaders.yaml — ими инициализируем леджер при первом обращении."""
    if not LEADERS_FILE.exists():
        return []
    data = yaml.safe_load(LEADERS_FILE.read_text(encoding="utf-8")) or {}
    out: list[dict] = []
    for track in TRACKS:
        for handle in data.get(track, []) or []:
            out.append({"handle": str(handle).lstrip("@").strip(), "track": track})
    return out


def _load_ledger() -> dict:
    if LEDGER_FILE.exists():
        try:
            return json.loads(LEDGER_FILE.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def _save_ledger(ledger: dict) -> None:
    LEDGER_FILE.parent.mkdir(exist_ok=True)
    LEDGER_FILE.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")


def _ensure_seeded(ledger: dict) -> bool:
    """Досеять авторов из leaders.yaml, которых ещё нет в леджере (стартовый тир «эталон»)."""
    changed = False
    have = {k.lower() for k in ledger}
    for s in _seed_universe():
        if s["handle"].lower() not in have:
            ledger[s["handle"]] = {"track": s["track"], "tier": "эталон", "checks": 0,
                                   "last_check": "", "notes": ["seed: стартовая курация владельца"]}
            have.add(s["handle"].lower())
            changed = True
    return changed


def load_leaders(scope: tuple = SCAN_DEFAULT_TIERS) -> list[dict]:
    """Авторы из леджера в заданных тирах: [{handle, track}, ...]. Леджер сеется из leaders.yaml."""
    ledger = _load_ledger()
    if _ensure_seeded(ledger):
        _save_ledger(ledger)
    return [{"handle": h, "track": i.get("track", "crypto")}
            for h, i in ledger.items() if i.get("tier", "эталон") in scope]


def update_author(handle: str, track: str = "", tier: str = "", note: str = "") -> str:
    """Записать вердикт проверки автора: ставит/меняет тир, добавляет датированную заметку,
    увеличивает счётчик проверок. Единая точка для повышения/понижения/занесения кандидата."""
    h = handle.lstrip("@").strip()
    if not h:
        return "Пустой хэндл."
    if tier and tier not in TIERS:
        return f"Неизвестный тир '{tier}'. Допустимо: {', '.join(TIERS)}."
    ledger = _load_ledger()
    _ensure_seeded(ledger)
    key = next((k for k in ledger if k.lower() == h.lower()), h)
    entry = ledger.get(key, {"track": "crypto", "tier": "кандидат", "checks": 0,
                             "last_check": "", "notes": []})
    if track and track.lower() in TRACKS:
        entry["track"] = track.lower()
    if tier:
        entry["tier"] = tier
    today = date.today().isoformat()
    entry["checks"] = int(entry.get("checks", 0)) + 1
    entry["last_check"] = today
    if note:
        entry.setdefault("notes", []).append(f"{today}: {note}")
    ledger[key] = entry
    _save_ledger(ledger)
    return f"✓ @{key}: тир «{entry['tier']}», проверок {entry['checks']}, {today}. {note}".strip()


def read_ledger_text() -> str:
    """Леджер авторов в читабельном виде — для еженедельной курации (видно тир, счётчик, историю)."""
    ledger = _load_ledger()
    if _ensure_seeded(ledger):
        _save_ledger(ledger)
    if not ledger:
        return "Леджер авторов X пуст."
    order = {t: n for n, t in enumerate(TIERS)}
    lines = []
    for h, i in sorted(ledger.items(), key=lambda kv: (order.get(kv[1].get("tier", ""), 9), kv[0].lower())):
        lines.append(f"@{h} [{i.get('track','?')}] тир={i.get('tier','?')} "
                     f"проверок={i.get('checks',0)} посл.проверка={i.get('last_check') or '—'}")
        for n in i.get("notes", [])[-3:]:
            lines.append(f"    • {n}")
    return "\n".join(lines)


def account_tweets(handle: str, limit: int = 8) -> list[dict]:
    """Свежие твиты ЛЮБОГО аккаунта (не только из списка) — для глубокой проверки кандидата."""
    h = handle.lstrip("@").strip()
    if not h:
        return [{"error": "Пустой хэндл."}]
    return asyncio.run(_collect([{"handle": h, "track": "?"}], max(1, min(limit, 20))))


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


def recent(limit_per_account: int = 6, handle: str = "", track: str = "",
           max_accounts: int = 12, tier: str = "") -> list[dict]:
    """Свежие твиты авторов из леджера.

    По умолчанию читает только тир «эталон». tier='all'/'все' добавит «тир2»; либо
    конкретный тир. track — фильтр трека; handle — точечно (игнорирует max_accounts);
    max_accounts — кап на широкий скан (бережём бёрнер).
    """
    scope = SCAN_DEFAULT_TIERS
    if tier:
        t = tier.lower()
        scope = ("эталон", "тир2") if t in ("all", "все") else (tier,) if tier in TIERS else scope
    leaders = load_leaders(scope)
    if track:
        leaders = [l for l in leaders if l["track"] == track.lower()]
    if handle:
        h = handle.lstrip("@").lower()
        leaders = [l for l in leaders if h in l["handle"].lower()]
    elif max_accounts and max_accounts > 0:  # ограничиваем только широкий скан, не точечный
        leaders = leaders[:max_accounts]
    if not leaders:
        return [{"error": "В выбранных тирах нет авторов (или не подошло под фильтр)."}]
    return asyncio.run(_collect(leaders, max(1, min(limit_per_account, 15))))
