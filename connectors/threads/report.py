"""Жёсткий сухой аналитический отчёт по Threads — с ДВУМЯ объективами.

- КАЧЕСТВО (на просмотр, зрелые посты ≥ VIEW_FLOOR) — «когда увидели, насколько зашло».
- ОХВАТ (сырые просмотры среди зрелых) — «как далеко улетело».

Свежие посты (моложе MATURITY_DAYS) в рейтинги/сравнения НЕ берём — они ещё копят охват.
Сравнения «медиа/темы/тайминг» — на зрелых чистых постах (без душителей охвата).

Запуск:  python -m connectors.threads.report
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from connectors.threads import scoring

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
POSTS_JSON = DATA / "threads_posts.json"
TOPICS_JSON = DATA / "threads_topics.json"

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _title(topics: dict, p: dict) -> str:
    t = topics.get(str(p.get("id", "")), {}).get("title", "")
    return t or (p.get("text", "")[:40].replace("\n", " "))


def _weekday(p: dict):
    try:
        return WEEKDAYS[datetime.fromisoformat(p["date"]).weekday()]
    except Exception:  # noqa: BLE001
        return None


def _load(posts=None, topics=None):
    """Данные для отчёта: переданные posts/topics или из data/threads_*.json. (None, {}) — если нет файла."""
    if posts is None:
        if not POSTS_JSON.exists():
            return None, {}
        posts = json.loads(POSTS_JSON.read_text(encoding="utf-8"))
    if topics is None:
        topics = json.loads(TOPICS_JSON.read_text(encoding="utf-8")) if TOPICS_JSON.exists() else {}
    return posts, topics


_NO_DATA = ("Нет данных Threads (data/threads_posts.json пуст или отсутствует). "
            "Собери командой:  python refresh_threads.py")


def build_report(posts=None, topics=None) -> str:
    """Тот же двухобъективный отчёт, но СТРОКОЙ (для Аналитик-бота и CLI). posts/topics — для тестов."""
    posts, topics = _load(posts, topics)
    if not posts:
        return _NO_DATA
    base = scoring.enrich(posts)

    measured = [p for p in posts if (p.get("views") or 0) > 0]
    mature = [p for p in measured if p.get("mature")]
    elig = [p for p in mature if p["views"] >= base["view_floor"]]          # база Качества
    clean = [p for p in elig if not p.get("has_link") and not p.get("has_hashtag")]  # + без душителей

    out: list[str] = []
    P = out.append
    P("=" * 68)
    P("THREADS — ЖЁСТКИЙ ОТЧЁТ (возраст учтён, качество = на просмотр)")
    P("=" * 68)

    # 1. Корпус
    live = [p for p in mature if (p.get("people_count") or 0) > 0]
    multi = [p for p in mature if (p.get("people_count") or 0) >= 2]
    amp_posts = [p for p in mature if p.get("amplification", 0) > 0]
    P(f"\n[КОРПУС]")
    P(f"  всего с охватом: {len(measured)} | зрелых (>{base['maturity_days']} дн): {len(mature)} | "
      f"свежих (в рейтинги не берём): {base['fresh']}")
    P(f"  годны для оценки качества (зрелые, ≥{base['view_floor']} просм): {len(elig)}")
    P(f"  медиана просмотров: {int(base['median_views'])} | медиана ER: {base['median_er']}% | "
      f"медиана людей/1k: {base['median_ppk']}")
    if mature:
        P(f"  с комментами людей: {len(live)} ({round(len(live)/len(mature)*100)}%) | "
          f"≥2 разных людей: {len(multi)} ({round(len(multi)/len(mature)*100)}%) | "
          f"кого-то распространили: {len(amp_posts)} ({round(len(amp_posts)/len(mature)*100)}%)")

    # 2. КАЧЕСТВО — топ (на просмотр, независимо от охвата)
    q = sorted(elig, key=lambda p: -(p.get("quality") or 0))[:10]
    P("\n[КАЧЕСТВО — ТОП-10]  на просмотр (люди/1k 40% + распр/просм 30% + лайк/просм 20% + ответы/просм 10%)")
    P(f"  {'Кач':>4} {'люди/1k':>7} {'расп/пок':>8} {'просм':>6}  тир / заголовок")
    for p in q:
        P(f"  {p.get('quality',0):>4} {p.get('people_per_k',0):>7} "
          f"{round((p.get('amp_rate') or 0)*1000,2):>8} {p.get('views',0):>6}  "
          f"{p['tier_ru']} — {_title(topics, p)[:40]}")

    # 3. ОХВАТ — топ (сырой, отдельный объектив «как далеко улетело»)
    r = sorted(mature, key=lambda p: -(p.get("views") or 0))[:10]
    P("\n[ОХВАТ — ТОП-10]  сырые просмотры (рост ≠ качество — отдельный объектив)")
    P(f"  {'просм':>7} {'распр':>5} {'люди':>4} {'кач':>4}  заголовок")
    for p in r:
        P(f"  {p.get('views',0):>7} {p.get('amplification',0):>5} {p.get('people_count',0):>4} "
          f"{p.get('quality') if p.get('quality') is not None else '-':>4}  {_title(topics, p)[:44]}")

    # 4. Ложная виральность
    fake = sorted([p for p in mature if p.get("tier") == "one_on_one"],
                  key=lambda p: -(p.get("people_replies") or 0))
    P(f"\n[ЛОЖНАЯ ВИРАЛЬНОСТЬ]  много реплаев, но ≤1 человек (ты + один): {len(fake)} шт.")
    for p in fake[:5]:
        P(f"  реплаев {p.get('people_replies',0):>3} от {p.get('people_count',0)} чел, "
          f"свои {p.get('self_replies',0):>3} | {_title(topics, p)[:48]}")

    # 5. Медиа vs текст — на зрелых чистых, ОБА объектива
    med = [p for p in clean if p.get("has_media")]
    txt = [p for p in clean if not p.get("has_media")]
    P(f"\n[МЕДИА vs ТЕКСТ]  зрелые чистые: {len(clean)}  (охват=абсолют, качество=на просмотр)")

    def _mvt(name, a):
        if not a:
            P(f"  {name}: нет постов"); return
        P(f"  {name}: {len(a):>3} | охват ср.просм {int(_avg([p['views'] for p in a])):>5} "
          f"ср.распр {round(_avg([p.get('amplification') or 0 for p in a]),2):>4} || "
          f"качество люди/1k {round(_avg([p.get('people_per_k') or 0 for p in a]),2):>5} "
          f"ER {round(_avg([p.get('er') or 0 for p in a]),2):>4}% Кач {round(_avg([p.get('quality') or 0 for p in a]),1):>4}")
    _mvt("С медиа ", med)
    _mvt("Без медиа", txt)

    # 6. Темы — на зрелых чистых, сортировка по Качеству (≥5 постов)
    by_theme: dict[str, list] = {}
    for p in clean:
        by_theme.setdefault(topics.get(str(p.get("id", "")), {}).get("theme", "?"), []).append(p)
    rows = [(th, a) for th, a in by_theme.items() if len(a) >= 5]
    rows.sort(key=lambda x: -_avg([p.get("quality") or 0 for p in x[1]]))
    small = [th for th, a in by_theme.items() if 0 < len(a) < 5]
    P("\n[ТЕМЫ]  зрелые чистые, ≥5 постов, по Качеству (люди/1k = разные люди на 1000 показов)")
    P(f"  {'Кач':>4} {'люди/1k':>7} {'распр':>5} {'ER%':>5} {'n':>4}  тема")
    for th, a in rows:
        P(f"  {round(_avg([p.get('quality') or 0 for p in a]),1):>4} "
          f"{round(_avg([p.get('people_per_k') or 0 for p in a]),2):>7} "
          f"{round(_avg([p.get('amplification') or 0 for p in a]),2):>5} "
          f"{round(_avg([p.get('er') or 0 for p in a]),2):>5} {len(a):>4}  {th}")
    if small:
        P(f"  (пропущены как шум, n<5: {', '.join(small)})")

    # 7. Тайминг — зрелые чистые, качество на просмотр
    P("\n[ТАЙМИНГ]  зрелые чистые → люди/1k показов / ср.Качество")
    for wd in WEEKDAYS:
        a = [p for p in clean if _weekday(p) == wd]
        if a:
            P(f"  {wd}: люди/1k {round(_avg([p.get('people_per_k') or 0 for p in a]),2):>5} | "
              f"Кач {round(_avg([p.get('quality') or 0 for p in a]),1):>5} | n={len(a)}")

    # 8. Душители охвата
    killed = [p for p in mature if p.get("has_link") or p.get("has_hashtag")]
    ok = [p for p in mature if not p.get("has_link") and not p.get("has_hashtag")]
    P("\n[ДУШИТЕЛИ ОХВАТА]  ссылка/хештег в тексте (зрелые)")
    if killed and ok:
        P(f"  зарезано: {len(killed)} | ср.просм {int(_avg([p['views'] for p in killed]))} "
          f"vs чистые {int(_avg([p['views'] for p in ok]))} "
          f"(x{round(_avg([p['views'] for p in ok]) / max(_avg([p['views'] for p in killed]),1),1)})")
        P("  ВАЖНО: ссылка в ПЕРВОМ self-комменте и редактура поста тоже РЕЖУТ охват — эти цифры их НЕ")
        P("  ловят, реальный ущерб БОЛЬШЕ. НЕ советуй прятать ссылку в первый коммент — лучше без ссылки.")
    else:
        P("  постов с душителями в тексте не найдено")
    P("\n" + "=" * 68)
    return "\n".join(out)


def find_posts(query: str, n: int = 10, posts=None, topics=None) -> str:
    """Найти свои Threads-посты по слову/фразе (в тексте или заголовке) → топ по просмотрам с метриками.
    Для вопросов «как зашёл мой пост про X». posts/topics — для тестов."""
    posts, topics = _load(posts, topics)
    if not posts:
        return _NO_DATA
    q = (query or "").strip().lower()
    if not q:
        return "Пустой запрос — укажи слово или фразу для поиска по постам Threads."
    scoring.enrich(posts)
    hits = [p for p in posts
            if q in (f"{p.get('text', '')} {_title(topics, p)}").lower()]
    if not hits:
        return f"По запросу «{query}» постов Threads не найдено."
    hits.sort(key=lambda p: -(p.get("views") or 0))
    out = [f"Threads-посты по «{query}» — топ {min(n, len(hits))} из {len(hits)} по просмотрам:"]
    for p in hits[:n]:
        qv = p.get("quality")
        out.append(
            f"  просм {p.get('views', 0):>6} | люди/1k {p.get('people_per_k') or 0} | "
            f"ER {p.get('er') or 0}% | Кач {qv if qv is not None else '-'} | "
            f"{p.get('tier_ru') or ''} | {_title(topics, p)[:50]}")
    return "\n".join(out)


def orientation_digest(posts=None, topics=None, max_themes=4, max_posts=5) -> str:
    """Компактный ОРИЕНТИР «что заходит на Threads» для Криейтора (НЕ полный build_report). На зрелых
    чистых постах: сигнал медиа, топ-темы по Качеству, несколько зашедших постов. Это РЕКОМЕНДАЦИЯ
    (владелец в контуре), НЕ правило — голос/вкус метрике не подчиняем (Goodhart). posts/topics — тесты."""
    posts, topics = _load(posts, topics)
    if not posts:
        return "(данных Threads пока нет — ориентируйся на мануал и эталоны)"
    scoring.enrich(posts)
    mature = [p for p in posts if p.get("mature") and (p.get("views") or 0) > 0]
    clean = [p for p in mature if not p.get("has_link") and not p.get("has_hashtag")]
    if len(clean) < 5:
        return "(зрелых чистых постов Threads мало — ориентируйся на мануал и эталоны)"
    out = ["Ориентир «что заходит на Threads» (по ТВОИМ данным; рекомендация, не правило — "
           "голос не подчиняем метрике):"]
    med = [p for p in clean if p.get("has_media")]
    txt = [p for p in clean if not p.get("has_media")]
    if med and txt:
        mv, tv = _avg([p["views"] for p in med]), _avg([p["views"] for p in txt])
        out.append(f"- медиа vs текст: с медиа ср.просм {int(mv)} vs без {int(tv)} (x{round(mv / max(tv, 1), 1)})")
    by_theme: dict[str, list] = {}
    for p in clean:
        by_theme.setdefault(topics.get(str(p.get("id", "")), {}).get("theme", "?"), []).append(p)
    rows = [(th, a) for th, a in by_theme.items() if len(a) >= 5]
    rows.sort(key=lambda x: -_avg([p.get("quality") or 0 for p in x[1]]))
    if rows:
        out.append("- темы по Качеству (сильные сверху): "
                   + "; ".join(f"{th} ({round(_avg([p.get('quality') or 0 for p in a]))})" for th, a in rows[:max_themes]))
    top = sorted([p for p in clean if p.get("quality") is not None], key=lambda p: -(p.get("quality") or 0))[:max_posts]
    if top:
        out.append("- заходило (заголовок · тир): "
                   + "; ".join(f"{_title(topics, p)[:38]} · {p.get('tier_ru') or ''}" for p in top))
    return "\n".join(out)


def main() -> None:
    print(build_report())


if __name__ == "__main__":
    main()
