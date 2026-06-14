"""Аналитика канала: чтение собранных метрик и ответы на вопросы по контенту.

Источники (готовит коннектор telegram_export):
  data/channel_posts.json — метрики по каждому посту (просмотры, реакции, ...)
  data/channel_stats.json — сводка канала (рост, источники, языки, ...)

Функции возвращают готовый ТЕКСТ — он отдаётся модели как результат инструмента.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
POSTS_JSON = DATA / "channel_posts.json"
STATS_JSON = DATA / "channel_stats.json"
TOPICS_JSON = DATA / "post_topics.json"

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
METRICS = {
    "views": "Просмотры", "reactions": "Реакции", "comments": "Комментарии",
    "forwards": "Репосты", "er": "ER% (реакции/просмотры)",
}


def _load_topics() -> dict:
    if TOPICS_JSON.exists():
        return json.loads(TOPICS_JSON.read_text(encoding="utf-8"))
    return {}


def _load_posts() -> list[dict]:
    if not POSTS_JSON.exists():
        return []
    raw = json.loads(POSTS_JSON.read_text(encoding="utf-8"))
    topics = _load_topics()
    posts = []
    for p in raw:
        if p.get("views") is None:        # служебные сообщения пропускаем
            continue
        dt = datetime.fromisoformat(p["date"]) if p.get("date") else None
        views = p.get("views") or 0
        reactions = p.get("likes_total") or sum(r.get("count", 0) for r in p.get("reactions", []))
        t = topics.get(str(p["id"]), {})
        posts.append({
            "id": p["id"],
            "dt": dt,
            "date": dt.strftime("%Y-%m-%d %H:%M") if dt else "",
            "weekday": WEEKDAYS[dt.weekday()] if dt else "",
            "hour": dt.hour if dt else None,
            "type": "Медиа" if p.get("has_media") else "Текст",
            "title": t.get("title", ""),
            "theme": t.get("theme", ""),
            "summary": t.get("summary", ""),
            "views": views,
            "reactions": reactions,
            "comments": p.get("comments") or 0,
            "forwards": p.get("forwards") or 0,
            "er": round(reactions / views * 100, 2) if views else 0.0,
            "text": p.get("text", ""),
            "preview": (t.get("title") or p.get("text", "")[:90].replace("\n", " ")) or "(без текста)",
            "reactions_detail": " ".join(
                f"{r.get('emoji') or '?'}{r.get('count')}" for r in p.get("reactions", [])
            ),
        })
    return posts


def themes_overview() -> str:
    """Темы канала: сколько постов и средние метрики по каждой — что работает."""
    posts = [p for p in _load_posts() if p["theme"]]
    if not posts:
        return "Тем нет (запусти enrich_topics)."
    groups: dict = {}
    for p in posts:
        groups.setdefault(p["theme"], []).append(p)

    def avg(items, key):
        return sum(i[key] for i in items) / len(items)
    rows = sorted(groups.items(), key=lambda kv: -avg(kv[1], "er"))
    out = ["Темы канала (отсортированы по вовлечённости ER, средние на пост):"]
    for theme, g in rows:
        out.append(f"  {theme}: постов {len(g)} | 👀{avg(g,'views'):.0f} "
                   f"❤{avg(g,'reactions'):.1f} 💬{avg(g,'comments'):.1f} ER={avg(g,'er'):.2f}%")
    return "\n".join(out)


def by_theme(theme: str) -> str:
    """Все посты заданной темы — чтобы видеть, что уже выходило (против повторов)."""
    q = (theme or "").lower().strip()
    posts = [p for p in _load_posts() if q in p["theme"].lower()]
    if not posts:
        return f"Постов по теме «{theme}» не найдено. Доступные темы — в themes_overview."
    posts.sort(key=lambda p: p["views"], reverse=True)
    out = [f"Посты по теме «{theme}» ({len(posts)} шт.) — что уже было:"]
    for p in posts[:25]:
        out.append(f"  #{p['id']} [{p['date'][:10]}] 👀{p['views']} ER={p['er']}% | "
                   f"{p['title'] or p['preview']} — {p['summary']}")
    return "\n".join(out)


def _metric_key(metric: str) -> str:
    metric = (metric or "views").lower().strip()
    aliases = {"просмотры": "views", "реакции": "reactions", "лайки": "reactions",
               "комменты": "comments", "комментарии": "comments",
               "репосты": "forwards", "вовлечённость": "er", "engagement": "er"}
    metric = aliases.get(metric, metric)
    return metric if metric in METRICS else "views"


def _fmt_row(p: dict, metric: str) -> str:
    return (f"#{p['id']} [{p['date']} {p['weekday']}] {p['type']} | "
            f"👀{p['views']} ❤{p['reactions']} 💬{p['comments']} 🔁{p['forwards']} "
            f"ER={p['er']}% | {p['preview']}")


def summary() -> str:
    posts = _load_posts()
    if not posts:
        return "Данных по постам нет. Сначала собери их (collect)."
    n = len(posts)
    avg_v = sum(p["views"] for p in posts) // n
    avg_er = round(sum(p["er"] for p in posts) / n, 2)
    d0 = min(p["date"] for p in posts)
    d1 = max(p["date"] for p in posts)
    out = [f"Постов: {n} | период {d0[:10]} → {d1[:10]}",
           f"Средние: просмотры {avg_v}, ER {avg_er}%, "
           f"реакции {sum(p['reactions'] for p in posts)//n}, "
           f"комменты {sum(p['comments'] for p in posts)//n}"]
    if STATS_JSON.exists():
        s = json.loads(STATS_JSON.read_text(encoding="utf-8"))
        h = s.get("headline", {})

        def line(key, name):
            v = h.get(key)
            if not v:
                return None
            ch = f" ({v['change_pct']:+}%)" if v.get("change_pct") is not None else ""
            return f"  {name}: {v.get('current')}{ch}"
        extra = [x for x in (
            line("followers", "подписчиков"),
            line("views_per_post", "просмотров/пост (за неделю)"),
            line("shares_per_post", "репостов/пост"),
            line("reactions_per_post", "реакций/пост"),
        ) if x]
        if extra:
            out.append("Сводка канала (админ-статистика):")
            out += extra
    return "\n".join(out)


def top_posts(metric: str = "views", n: int = 10, content_type: str = "") -> str:
    posts = _load_posts()
    if not posts:
        return "Данных нет."
    key = _metric_key(metric)
    if content_type:
        ct = content_type.strip().lower()
        posts = [p for p in posts if p["type"].lower() == ct]
    posts = sorted(posts, key=lambda p: p[key], reverse=True)[:max(1, min(n, 30))]
    head = f"ТОП-{len(posts)} по «{METRICS[key]}»" + (f" среди «{content_type}»" if content_type else "")
    return head + "\n" + "\n".join(_fmt_row(p, key) for p in posts)


def bottom_posts(metric: str = "views", n: int = 10) -> str:
    posts = _load_posts()
    if not posts:
        return "Данных нет."
    key = _metric_key(metric)
    posts = sorted(posts, key=lambda p: p[key])[:max(1, min(n, 30))]
    return f"ХУДШИЕ {len(posts)} по «{METRICS[key]}»\n" + "\n".join(_fmt_row(p, key) for p in posts)


def by_dimension(dim: str = "weekday") -> str:
    """Срез средних метрик по: weekday | hour | type."""
    posts = _load_posts()
    if not posts:
        return "Данных нет."
    dim = (dim or "weekday").lower().strip()
    aliases = {"день": "weekday", "дни": "weekday", "часы": "hour", "час": "hour",
               "тип": "type", "weekday": "weekday", "hour": "hour", "type": "type"}
    dim = aliases.get(dim, "weekday")
    groups: dict = {}
    for p in posts:
        k = p[dim]
        if k is None:
            continue
        groups.setdefault(k, []).append(p)

    def avg(items, key):
        return sum(i[key] for i in items) / len(items)

    if dim == "weekday":
        order = WEEKDAYS
    elif dim == "hour":
        order = sorted(groups, key=lambda x: x)
    else:
        order = sorted(groups, key=lambda k: -avg(groups[k], "views"))
    rows = [f"Срез по «{dim}» (средние на пост):"]
    for k in order:
        if k not in groups:
            continue
        g = groups[k]
        label = f"{k:02d}:00" if dim == "hour" else str(k)
        rows.append(f"  {label:>6}: постов {len(g):>3} | 👀{avg(g,'views'):.0f} "
                    f"❤{avg(g,'reactions'):.1f} 💬{avg(g,'comments'):.1f} ER={avg(g,'er'):.2f}%")
    return "\n".join(rows)


def post_details(post_id: int) -> str:
    posts = _load_posts()
    p = next((x for x in posts if x["id"] == int(post_id)), None)
    if not p:
        return f"Пост #{post_id} не найден."
    return (f"Пост #{p['id']} [{p['date']} {p['weekday']}] тип: {p['type']}\n"
            f"👀 просмотры: {p['views']} | ❤ реакции: {p['reactions']} ({p['reactions_detail']})\n"
            f"💬 комментарии: {p['comments']} | 🔁 репосты: {p['forwards']} | ER: {p['er']}%\n"
            f"Текст:\n{p['text'][:1500]}")


def find_posts(query: str, n: int = 8) -> str:
    posts = _load_posts()
    q = (query or "").lower().strip()
    if not q:
        return "Пустой запрос."
    hits = [p for p in posts if q in p["text"].lower()][:max(1, min(n, 20))]
    if not hits:
        return f"Постов со словами «{query}» не найдено."
    return f"Найдено {len(hits)} (по «{query}»):\n" + "\n".join(_fmt_row(p, "views") for p in hits)


def refresh_metrics(full: bool = True) -> str:
    """«Обновить»: пересобрать свежие метрики и таблицу (запуск refresh.py).

    Требует окружения сборщика (сессия аккаунта + telethon). Может занять до пары минут.
    """
    import subprocess
    import sys
    cmd = [sys.executable, str(ROOT / "refresh.py")] + (["--all"] if full else [])
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return "Обновление идёт дольше обычного (>5 мин) — проверь позже."
    except Exception as e:  # noqa: BLE001
        return f"Не удалось запустить обновление: {type(e).__name__}: {e}"
    tail = "\n".join((r.stdout or "").strip().splitlines()[-4:])
    ok = r.returncode == 0
    return ("Метрики обновлены, таблица пересобрана.\n" if ok
            else "Обновление прошло с ошибками.\n") + tail


def audience() -> str:
    """Сводка по аудитории из админ-статистики (источники, языки, часы)."""
    if not STATS_JSON.exists():
        return "Сводной статистики нет (collect_stats не запускался)."
    s = json.loads(STATS_JSON.read_text(encoding="utf-8"))
    g = s.get("graphs", {})

    def totals(name, top=6):
        graph = g.get(name)
        if not graph or "columns" not in graph:
            return []
        names = graph.get("names", {})
        out = []
        for c in graph["columns"]:
            if not c or c[0] == "x":
                continue
            out.append((names.get(c[0], c[0]), sum(v for v in c[1:] if isinstance(v, (int, float)))))
        return sorted(out, key=lambda x: -x[1])[:top]

    parts = []
    for title, name in [("Просмотры по источникам", "Просмотры по источникам"),
                        ("Новые подписчики по источникам", "Новые подписчики по источникам"),
                        ("Языки аудитории", "Языки аудитории")]:
        t = totals(name)
        if t:
            parts.append(title + ": " + ", ".join(f"{k} {int(v)}" for k, v in t))
    return "\n".join(parts) if parts else "Графики недоступны."
