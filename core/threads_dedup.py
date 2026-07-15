"""🧵 Анти-повтор для Threads — МЯГКИЙ (не путать с ТГ-дедупом).

Механика та же, что в ТГ (core.dedup): перечитай ближайший прошлый пост и сравни ТЕЗИС, сверка по
истории Threads (data/threads_posts.json + threads_topics.json), окно свежести, Sonnet. НО философия
ПРОТИВОПОЛОЖНАЯ по строгости — и это НАМЕРЕННО:

- ТГ: выверено, эксклюзивно — «новый угол на то же» НЕ спасает, сомневаешься → 🔁 (пропуск дешевле дубля).
- Threads: частота и объём — ПЛЮС (верх воронки, живёшь ритмом). 4-5 постов за день на горячую тему,
  тот же домен снова, та же тема под новым углом/эмоцией — НОРМА. Режем ТОЛЬКО near-дубль (тот же самый
  пост почти дословно). Сомневаешься → 🆕 (на Threads молчание дороже лишнего поста — враг РАЗРЫВ, §2).

Поэтому у Threads СВОЙ судья (THREADS_DEDUP_SYSTEM), а не ТГ-строгий. Формат вердикта тот же (🆕/🔁 +
РЕКОМЕНДУЮ/СТАТУС) — читается парсерами core.dedup (all_repeats/recommended_theme/failed).

⚠️ Свежесть: сверка идёт по выгрузке на диске (434 поста, последний collect 12.07). Токен Threads
ЖИВОЙ (истекает ~сен-2026, авто-обновляется) — данные устаревают лишь оттого, что refresh_threads
давно не гоняли, НЕ потому что collect сломан (запись «API blocked» в threads.md §11 от 12.07 протухла).
Прогонишь refresh_threads — сверка увидит свежие посты. Живого refresh-гейта тут пока нет намеренно.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from core import config, io_safe, llm, runmode

POSTS_JSON = config.ROOT / "data" / "threads_posts.json"
TOPICS_JSON = config.ROOT / "data" / "threads_topics.json"
# Окно короче ТГ (там 4 нед): Threads — быстрая площадка, сверяемся с недавним, чтобы поймать near-дубль,
# а не тематическое пересечение месячной давности. Мягкость в основном в СУДЬЕ, окно — вторично.
WINDOW_WEEKS = 2

THREADS_DEDUP_SYSTEM = (
    "Ты ловишь ТОЛЬКО настоящий САМО-ПОВТОР в ленте Threads — когда автор выложил бы ПРАКТИЧЕСКИ ТОТ ЖЕ "
    "пост (та же конкретная мысль, тот же поворот, почти теми же словами), что уже выходил на днях. Тебе "
    "дают пост-кандидат и недавние посты Threads (дата | заголовок | тема — суть, свежие сверху).\n"
    "⭐ THREADS ≠ ТЕЛЕГРАМ. Здесь ЧАСТОТА и ОБЪЁМ — ПЛЮС (верх воронки, живёшь ритмом). Один и тот же "
    "ДОМЕН много раз, ДАЖЕ несколько постов за день на горячую тему (биток, макро, личное), та же тема "
    "под новым углом/эмоцией — это НОРМА, НЕ повтор. Планка повтора ВЫСОКАЯ: режем near-дубль, НЕ "
    "тематическое пересечение.\n"
    "По кандидату:\n"
    "  🆕 (ПО УМОЛЧАНИЮ) — любой свежий заход: новый факт, новый угол, новый крючок, другая эмоция, иной "
    "поворот — ДАЖЕ на том же домене/той же горячей теме, что вчера. Сомневаешься — 🆕 (на Threads "
    "молчание дороже лишнего поста: враг — РАЗРЫВ, не объём).\n"
    "  🔁 — ТОЛЬКО если кандидат по сути ТОТ ЖЕ пост, что уже вышел недавно: та же конкретная мысль + та "
    "же подача, автор почти дословно повторил бы себя. «Та же тема/домен» этого НЕ делает — нужна та "
    "самая МЫСЛЬ почти теми же словами.\n"
    "Выведи по СТРОКЕ на кандидата:\n"
    "  <🆕|🔁> «<кандидат коротко>» — <почему свежо ЛИБО дата near-дубля и совпавшая мысль>\n"
    "Затем ДВЕ финальные строки СТРОГО в формате:\n"
    "  РЕКОМЕНДУЮ: «<как подать кандидата одной строкой; если 🔁 — чем отстроиться>»\n"
    "  СТАТУС: ОК (кандидат свежий, 🆕) либо   СТАТУС: ПОВТОР (кандидат — near-дубль недавнего поста)"
)


def _load() -> tuple[list, dict]:
    # io_safe: битый/пустой threads_posts.json не должен ронять сверку трейсбеком —
    # digest() честно скажет «нет выгрузки», check() отработает мягким СТАТУС: ОК.
    posts = io_safe.load_json(POSTS_JSON, [])
    topics = io_safe.load_json(TOPICS_JSON, {})
    return posts, topics


def digest(weeks: int = WINDOW_WEEKS, limit: int = 60, posts=None, topics=None) -> str:
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
    """Мягкая сверка кандидата (тема/тезис будущего Threads-поста) с недавней историей Threads. Формат
    вердикта тот же, что core.dedup (🆕/🔁 + РЕКОМЕНДУЮ/СТАТУС) — читай парсерами core.dedup. Не роняет
    пайплайн: сбой → маркер «(анти-повтор не удался…)» + мягкий СТАТУС: ОК."""
    candidate = (candidate or "").strip()
    if not candidate:
        return "(кандидата нет — нечего сверять)\nРЕКОМЕНДУЮ: «»\nСТАТУС: ОК"
    dg = digest()
    mdl = model or runmode.resolve("claude-sonnet-4-6")
    user = (f"ПОСТ-КАНДИДАТ (будущий пост Threads):\n{candidate}\n\n"
            f"НЕДАВНИЕ ПОСТЫ THREADS за {WINDOW_WEEKS} нед (дата | заголовок | тема — суть, свежие "
            f"сверху):\n{dg}\n\n"
            "Это near-дубль недавнего поста (та же мысль почти дословно) или свежий заход? Помни: тот же "
            "домен/тема сами по себе НЕ повтор. Вердикт строго по форме.")
    try:
        text, _ = llm.reply(mdl, THREADS_DEDUP_SYSTEM, [], user, [], lambda _n, _a: "", api_key, None)
        return (text or "(пусто)").strip()
    except Exception as e:  # noqa: BLE001 — анти-повтор не роняет конвейер
        return f"(анти-повтор не удался: {e})\nРЕКОМЕНДУЮ: «»\nСТАТУС: ОК"
