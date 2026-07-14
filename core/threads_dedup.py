"""🧵 Анти-повтор для Threads — зеркало core/dedup, но по ленте Threads.

Та же идея, что в ТГ (core.dedup): не выпустить пост про то, что в Threads УЖЕ выходило. Отличие
ТОЛЬКО в источнике данных — сверяемся с историей Threads (data/threads_posts.json + threads_topics.json),
а не канала. Судью (DEDUP_SYSTEM) и парсеры вердикта (all_repeats/recommended_theme/repeat_themes/
failed) ПЕРЕИСПОЛЬЗУЕМ из core.dedup: механика одна, расходиться им нельзя (память: «нужен ТАКОЙ ЖЕ
флагману и Threads»). Тот же приём — перечитай ближайший прошлый пост и СРАВНИ ТЕЗИС, дата/событие
решает, «новый угол на то же» не спасает; окно свежести, не вся история; Sonnet, не Haiku.

⚠️ Свежесть данных: живой collect Threads пока заблокирован (токен — threads.md шаг 0), сверка идёт
по выгрузке на диске (434 поста, свежесть встала 12.07). Как токен пере-засеют и refresh_threads
заработает — сверка сама увидит свежие посты. Для анти-повтора это не ломающе: 434 дают крепкую
историю, новых постов пока мало. Живого refresh-гейта (как refresh_if_stale в ТГ) тут НЕТ намеренно,
пока collect не чинён — иначе он падал бы на каждом прогоне.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from core import config, dedup, llm, runmode

POSTS_JSON = config.ROOT / "data" / "threads_posts.json"
TOPICS_JSON = config.ROOT / "data" / "threads_topics.json"
DEDUP_WINDOW_WEEKS = dedup.DEDUP_WINDOW_WEEKS   # то же окно свежести, что ТГ (4 нед)


def _load() -> tuple[list, dict]:
    posts = json.loads(POSTS_JSON.read_text(encoding="utf-8")) if POSTS_JSON.exists() else []
    topics = json.loads(TOPICS_JSON.read_text(encoding="utf-8")) if TOPICS_JSON.exists() else {}
    return posts, topics


def digest(weeks: int = DEDUP_WINDOW_WEEKS, limit: int = 60, posts=None, topics=None) -> str:
    """Дайджест недавних Threads-постов (свежие сверху): дата | заголовок | тема — суть. Окно свежести,
    не вся история (в простыне модель топит нужный пост). posts/topics — для тестов. Пусто → пометка."""
    if posts is None or topics is None:
        posts, topics = _load()
    if not posts:
        return "(нет выгрузки Threads — сверять не с чем)"
    dated = []
    for p in posts:
        try:
            dated.append((datetime.fromisoformat(p["date"]), p))
        except Exception:
            continue
    if not dated:
        return "(у постов Threads нет разбираемых дат)"
    newest = max(dt for dt, _ in dated)
    cutoff = newest - timedelta(weeks=weeks)
    recent = sorted([(dt, p) for dt, p in dated if dt >= cutoff], key=lambda x: -x[0].timestamp())[:limit]
    if not recent:
        return f"(за последние {weeks} нед постов Threads нет)"
    lines = []
    for dt, p in recent:
        t = topics.get(str(p.get("id", "")), {})
        title = (t.get("title") or p.get("text", "")[:50].replace("\n", " "))[:60]
        theme = t.get("theme", "?")
        summary = (t.get("summary") or "")[:120]
        lines.append(f"{dt.date().isoformat()} | {title} | {theme} — {summary}")
    return "\n".join(lines)


def check(candidate: str, api_key: str | None = None, model: str | None = None) -> str:
    """Сверить кандидата (тема/тезис будущего Threads-поста) с недавней историей Threads. Возвращает
    вердикт в ТОМ ЖЕ формате, что core.dedup (строки 🆕/🔁 + РЕКОМЕНДУЮ/СТАТУС) — читай его парсерами
    core.dedup (all_repeats/recommended_theme/repeat_themes/failed). Не роняет пайплайн: любой сбой →
    маркер «(анти-повтор не удался…)» + мягкий СТАТУС: ОК (ветка сама решит fail-open/closed)."""
    candidate = (candidate or "").strip()
    if not candidate:
        return "(кандидата нет — нечего сверять)\nРЕКОМЕНДУЮ: «»\nСТАТУС: ОК"
    dg = digest()
    mdl = model or runmode.resolve("claude-sonnet-4-6")
    user = (f"НАПРАВЛЕНИЕ-КАНДИДАТ (будущий пост Threads):\n{candidate}\n\n"
            f"УЖЕ ОПУБЛИКОВАНО В THREADS за последние {DEDUP_WINDOW_WEEKS} нед (дата | заголовок | тема — "
            f"суть, свежие сверху):\n{dg}\n\n"
            "Найди ближайший прошлый пост Threads по теме/сути, ПЕРЕЧИТАЙ и СРАВНИ ТЕЗИС. Вердикт по форме.")
    try:
        text, _ = llm.reply(mdl, dedup.DEDUP_SYSTEM, [], user, [], lambda _n, _a: "", api_key, None)
        return (text or "(пусто)").strip()
    except Exception as e:  # noqa: BLE001 — анти-повтор не роняет конвейер
        return f"(анти-повтор не удался: {e})\nРЕКОМЕНДУЮ: «»\nСТАТУС: ОК"
