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
FORMATS_JSON = DATA / "post_formats.json"   # формат/тип поста (флагман/обучающий/…), размечает Аналитик

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
METRICS = {
    "views": "Просмотры", "reactions": "Реакции", "comments": "Комментарии",
    "forwards": "Репосты", "er": "ER% (реакции/просмотры)",
}

# Автоклассификация формата (первый проход; спорные средние — на ручную доразметку set_format).
# Формат — это НЕ тема (о чём), а КАК сделан пост (тех-карта в memory/post_standard.md).
# Флагман (определение владельца) = МЕДИА + ДЛИННЫЙ текст (глубокая завершённая мысль),
# а не репосты и не просто длина текстом. Примеры владельца: #434 (670 сл.), #432 (620 сл.).
FLAGMAN_MIN_WORDS = 450     # «длинный текст» (порог под примеры владельца; правь, если нужно строже)


def _load_topics() -> dict:
    if TOPICS_JSON.exists():
        return json.loads(TOPICS_JSON.read_text(encoding="utf-8"))
    return {}


def _load_formats() -> dict:
    if FORMATS_JSON.exists():
        return json.loads(FORMATS_JSON.read_text(encoding="utf-8"))
    return {}


def _save_formats(formats: dict) -> None:
    FORMATS_JSON.write_text(json.dumps(formats, ensure_ascii=False, indent=2), encoding="utf-8")


def _classify(p: dict) -> str:
    """Эвристика формата по содержанию+метрикам (НЕ только по длине — учитываем смысл флагмана)."""
    text = p.get("text") or ""
    low = text.lower()
    words = p.get("words", 0)
    theme = (p.get("theme") or "").strip().lower()
    if words == 0:
        return "медиа"                       # пост без текста (только картинка/видео)
    if (any(k in low for k in ("розыгрыш", "конкурс", "giveaway", "разыгрыва", "буст"))
            or ("премиум" in low and ("подпис" in low or "розыгр" in low or "конкурс" in low))):
        return "служебное"                   # анонс/розыгрыш/служебное, не контент
    if p.get("type") == "Медиа" and words >= FLAGMAN_MIN_WORDS:
        return "флагман"                     # медиа + длинный текст (определение владельца)
    if theme == "психология":
        return "психология"
    if theme == "обучение":
        return "обучающий"
    if theme == "личное":
        return "личный"
    return "короткий"                        # свежее со своим углом / прочий короткий


def auto_classify_formats(force: bool = False) -> str:
    """Разметить формат всех постов (первый проход / дозаполнить новые).

    force=False — не трогает уже размеченные (бережёт ручные правки), заполняет только новые.
    force=True — переразметить весь канал заново.
    """
    posts = _load_posts()
    if not posts:
        return "Данных по постам нет."
    formats = {} if force else _load_formats()
    new = 0
    for p in posts:
        sid = str(p["id"])
        if not force and formats.get(sid):
            continue
        formats[sid] = _classify(p)
        new += 1
    _save_formats(formats)
    counts: dict = {}
    for v in formats.values():
        counts[v] = counts.get(v, 0) + 1
    dist = ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
    return (f"Разметка форматов обновлена (новых: {new}, всего: {len(formats)}).\n"
            f"Распределение: {dist}\nСпорные — поправь set_format(id, формат).")


def set_format(post_id: int, fmt: str) -> str:
    """Ручная правка формата одного поста (перекрывает авторазметку)."""
    formats = _load_formats()
    formats[str(int(post_id))] = (fmt or "").strip().lower()
    _save_formats(formats)
    return f"Пост #{post_id} помечен форматом «{fmt}»."


def _load_posts() -> list[dict]:
    if not POSTS_JSON.exists():
        return []
    raw = json.loads(POSTS_JSON.read_text(encoding="utf-8"))
    topics = _load_topics()
    formats = _load_formats()
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
            "format": formats.get(str(p["id"]), ""),
            "words": len((p.get("text") or "").split()),
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


def formats_overview() -> str:
    """Форматы канала со средними метриками — что заходит по ФОРМАТУ (а не теме). Основа плейбука."""
    posts = [p for p in _load_posts() if p["format"]]
    if not posts:
        return "Форматы ещё не размечены. Запусти классификацию: /classify (auto_classify_formats)."
    groups: dict = {}
    for p in posts:
        groups.setdefault(p["format"], []).append(p)

    def avg(items, key):
        return sum(i[key] for i in items) / len(items)
    rows = sorted(groups.items(), key=lambda kv: -avg(kv[1], "forwards"))
    out = ["Форматы канала (сорт. по репостам; средние на пост):"]
    for fmt, g in rows:
        out.append(f"  {fmt}: постов {len(g)} | 👀{avg(g,'views'):.0f} ❤{avg(g,'reactions'):.1f} "
                   f"💬{avg(g,'comments'):.1f} 🔁{avg(g,'forwards'):.1f} ER={avg(g,'er'):.2f}% "
                   f"| слов~{avg(g,'words'):.0f}")
    return "\n".join(out)


def by_format(fmt: str) -> str:
    """Все посты заданного формата (напр. 'флагман') — вытащить примеры/историю формата."""
    q = (fmt or "").lower().strip()
    posts = [p for p in _load_posts() if q and q in p["format"]]
    if not posts:
        return f"Постов формата «{fmt}» не найдено. Доступные форматы — в formats_overview."
    posts.sort(key=lambda p: p["forwards"], reverse=True)
    out = [f"Посты формата «{fmt}» ({len(posts)} шт.), сильные сверху:"]
    for p in posts[:25]:
        out.append(f"  #{p['id']} [{p['date'][:10]}] 🔁{p['forwards']} ER={p['er']}% слов~{p['words']} | "
                   f"{p['title'] or p['preview']}")
    return "\n".join(out)


def _metric_key(metric: str) -> str:
    metric = (metric or "views").lower().strip()
    aliases = {"просмотры": "views", "реакции": "reactions", "лайки": "reactions",
               "комменты": "comments", "комментарии": "comments",
               "репосты": "forwards", "вовлечённость": "er", "engagement": "er"}
    metric = aliases.get(metric, metric)
    return metric if metric in METRICS else "views"


def _fmt_row(p: dict, metric: str) -> str:
    fmt = f"·{p['format']}" if p.get("format") else ""
    return (f"#{p['id']} [{p['date']} {p['weekday']}] {p['type']}{fmt} | "
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


def top_posts(metric: str = "views", n: int = 10, content_type: str = "",
              post_format: str = "") -> str:
    posts = _load_posts()
    if not posts:
        return "Данных нет."
    key = _metric_key(metric)
    if content_type:
        ct = content_type.strip().lower()
        posts = [p for p in posts if p["type"].lower() == ct]
    if post_format:
        pf = post_format.strip().lower()
        posts = [p for p in posts if pf in p["format"]]
    posts = sorted(posts, key=lambda p: p[key], reverse=True)[:max(1, min(n, 30))]
    head = (f"ТОП-{len(posts)} по «{METRICS[key]}»"
            + (f" среди «{content_type}»" if content_type else "")
            + (f" формата «{post_format}»" if post_format else ""))
    return head + "\n" + "\n".join(_fmt_row(p, key) for p in posts)


def bottom_posts(metric: str = "views", n: int = 10) -> str:
    posts = _load_posts()
    if not posts:
        return "Данных нет."
    key = _metric_key(metric)
    posts = sorted(posts, key=lambda p: p[key])[:max(1, min(n, 30))]
    return f"ХУДШИЕ {len(posts)} по «{METRICS[key]}»\n" + "\n".join(_fmt_row(p, key) for p in posts)


def by_dimension(dim: str = "weekday") -> str:
    """Срез средних метрик по: weekday | hour | type | format."""
    posts = _load_posts()
    if not posts:
        return "Данных нет."
    dim = (dim or "weekday").lower().strip()
    aliases = {"день": "weekday", "дни": "weekday", "часы": "hour", "час": "hour",
               "тип": "type", "формат": "format", "weekday": "weekday", "hour": "hour",
               "type": "type", "format": "format"}
    dim = aliases.get(dim, "weekday")
    groups: dict = {}
    for p in posts:
        k = p[dim]
        if k is None or k == "":      # формат без разметки не считаем
            continue
        groups.setdefault(k, []).append(p)

    def avg(items, key):
        return sum(i[key] for i in items) / len(items)

    if dim == "weekday":
        order = WEEKDAYS
    elif dim == "hour":
        order = sorted(groups, key=lambda x: x)
    elif dim == "format":
        order = sorted(groups, key=lambda k: -avg(groups[k], "forwards"))
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
    return (f"Пост #{p['id']} [{p['date']} {p['weekday']}] тип: {p['type']} | "
            f"формат: {p['format'] or '—'} | слов: {p['words']}\n"
            f"👀 просмотры: {p['views']} | ❤ реакции: {p['reactions']} ({p['reactions_detail']})\n"
            f"💬 комментарии: {p['comments']} | 🔁 репосты: {p['forwards']} | ER: {p['er']}%\n"
            f"Текст:\n{p['text'][:1500]}")


def read_post(post_id: int) -> str:
    """ПОЛНЫЙ текст утверждённого поста по id — эталон для калибровки (плотность фактов,
    лаконичность, голос, длина). В отличие от post_details/recent_posts текст НЕ обрезается."""
    posts = _load_posts()
    p = next((x for x in posts if x["id"] == int(post_id)), None)
    if not p:
        return f"Пост #{post_id} не найден."
    text = p.get("text") or ""
    return (f"Эталон #{p['id']} [{p['date'][:10]}] формат: {p['format'] or '—'} | "
            f"длина: {len(text)} знаков | 🔁{p['forwards']} 👀{p['views']} ER {p['er']}%\n"
            f"--- учись: плотность фактов на знак, лаконичность, голос, что влезает в ОДНО сообщение ---\n"
            f"{text}")


def find_posts(query: str, n: int = 8) -> str:
    posts = _load_posts()
    q = (query or "").lower().strip()
    if not q:
        return "Пустой запрос."
    hits = [p for p in posts if q in p["text"].lower()][:max(1, min(n, 20))]
    if not hits:
        return f"Постов со словами «{query}» не найдено."
    return f"Найдено {len(hits)} (по «{query}»):\n" + "\n".join(_fmt_row(p, "views") for p in hits)


def topics_digest(limit: int = 0) -> str:
    """Компактная сводка тем ВСЕХ постов (id, дата, тема, заголовок, суть) — свежие сверху.

    Готовый материал для анти-повтора (core/dedup): по строке на пост, недавние первыми (свежий
    повтор заметнее всего). limit>0 — только N последних. Источник тем — post_topics.json (его
    наполняет Аналитик через enrich_topics); даты берём из channel_posts.json.
    """
    posts = [p for p in _load_posts() if p.get("dt")]
    if not posts:
        return "(данных по постам нет — сначала собери выгрузку канала)"
    posts.sort(key=lambda p: p["dt"], reverse=True)
    if limit > 0:
        posts = posts[:limit]
    lines = []
    for p in posts:
        title = p.get("title") or p.get("preview") or "(без заголовка)"
        summary = p.get("summary") or ""
        lines.append(f"#{p['id']} [{p['date'][:10]}] {p['theme'] or '—'} | {title}"
                     + (f" — {summary}" if summary else ""))
    return "\n".join(lines)


def _headtail(t: str, head: int = 600, tail: int = 400) -> str:
    t = (t or "").strip()
    if len(t) <= head + tail:
        return t
    return t[:head] + "\n   […]\n" + t[-tail:]


def recent_posts(n: int = 5, post_format: str = "") -> str:
    """Последние N постов по дате (что читатели видели недавно) — заголовок + начало и конец текста.

    Для проверки СВЕЖЕСТИ ПРИЁМОВ (анти-самоповтор): не повторять подряд тип хука, каркас
    главной антитезы, угол закрывающего вопроса и формулировку заголовка. Окно ~5, не весь канал.
    """
    posts = [p for p in _load_posts() if p.get("dt")]
    if not posts:
        return "Данных нет."
    if post_format:
        pf = post_format.strip().lower()
        posts = [p for p in posts if pf in p["format"]]
    posts.sort(key=lambda p: p["dt"], reverse=True)
    posts = posts[:max(1, min(n, 15))]
    head = (f"Последние {len(posts)} постов" + (f" формата «{post_format}»" if post_format else "")
            + " — НЕ повторяй их приёмы (хук, антитезу, вопрос, заголовок) в новом посте:")
    out = [head]
    for p in posts:
        out.append(f"\n#{p['id']} [{p['date'][:10]}] {p['format'] or '—'} | {p['title'] or p['preview']}\n"
                   f"{_headtail(p['text'])}")
    return "\n".join(out)


def refresh_metrics(full: bool = True) -> str:
    """«Обновить»: пересобрать свежие метрики и таблицу (запуск refresh.py).

    Требует окружения сборщика (сессия аккаунта + telethon). Может занять до пары минут.
    """
    import os
    import subprocess
    import sys
    cmd = [sys.executable, str(ROOT / "refresh.py")] + (["--all"] if full else [])
    # UTF-8 в ОБЕ стороны (RU-Windows): без этого text=True декодит вывод подпроцесса в cp1251 и падает
    # на эмодзи/русском (UnicodeDecodeError 0x98 в reader-потоке). encoding/errors — для ЧТЕНИЯ родителем;
    # PYTHONUTF8/PYTHONIOENCODING — чтобы сам refresh.py и его под-модули ПИСАЛИ в pipe utf-8, а не cp1251.
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300,
                           encoding="utf-8", errors="replace", env=env)
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
