"""Точка отсчёта завода: один снимок всех метрик, по которым мы будем судить об улучшениях.

ЗАЧЕМ ИМЕННО ИНСТРУМЕНТ, А НЕ ЦИФРЫ В ОТЧЁТЕ. Владелец 09.09.2026: «сохрани аудит и аналитику,
чтобы мы могли сравнить после». Сравнить можно только то, что померено ОДИНАКОВО. Цифры, выписанные
руками в документ, через месяц пересчитать нечем: не вспомнить, какие посты входили в выборку, что
считалось зрелым и за какой срок брались деньги. Поэтому снимок делает код, а документ на него
ссылается.

ЧТО ВНУТРИ: деньги (по ролям), производство (сколько постов), Telegram (динамика зрелых постов и
счётчики канала), Threads (аккаунт + воронка заводских постов по форматам), рычаги (ставка).

КАК СРАВНИВАТЬ: снимок берётся САМ, раз в месяц, из автопилота — владелец не должен ничего
помнить и запускать (его прямые слова 09.09: «вот это я не запомню»). Новый JSON ложится рядом со
старым в docs/baselines/, разница по одинаковым ключам уходит владельцу в Telegram обычным
сообщением. Руками: `python -m core.factory_baseline`.

ЧЕСТНОСТЬ: где данных мало (например, финал-вопрос стоит на двух постах), снимок пишет n рядом с
числом. Метрика без размера выборки — это мнение, а не замер.
"""
from __future__ import annotations

import json
import statistics as st
from collections import defaultdict
from datetime import date, datetime, timedelta

from core import config, factory_link, threads_app_metrics, threads_lint

DAYS = 90
OUT_DIR = config.ROOT / "docs" / "baselines"


def _money(edge: str) -> dict:
    by_who, by_month, total = defaultdict(float), defaultdict(float), 0.0
    path = config.ROOT / "data" / "cost_log.jsonl"
    for ln in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if (r.get("ts") or "")[:10] < edge:
            continue
        c = float(r.get("cost") or 0)
        by_who[r.get("who") or "?"] += c
        by_month[(r.get("ts") or "")[:7]] += c
        total += c
    return {"total_usd": round(total, 2),
            "by_role_usd": {k: round(v, 2) for k, v in sorted(by_who.items(), key=lambda t: -t[1])},
            "by_month_usd": {k: round(v, 2) for k, v in sorted(by_month.items())}}


def _telegram(edge: str) -> dict:
    posts = {p["id"]: p for p in json.loads((config.ROOT / "data" / "channel_posts.json")
                                            .read_text(encoding="utf-8")) if p.get("id")}
    best: dict = {}
    for s in json.loads((config.ROOT / "data" / "snapshots.json").read_text(encoding="utf-8")):
        pid = s.get("post_id")
        if pid and (pid not in best or (s.get("views") or 0) > (best[pid].get("views") or 0)):
            best[pid] = s
    by_month = defaultdict(list)
    for pid, s in best.items():
        p = posts.get(pid)
        if not p or (p.get("date") or "")[:10] < edge or (s.get("age_days") or 0) < 5:
            continue
        by_month[(p["date"])[:7]].append(s)
    months = {m: {"posts": len(rows),
                  "views_median": round(st.median([r["views"] for r in rows])),
                  "reactions_avg": round(st.mean([r.get("reactions") or 0 for r in rows]), 1),
                  "forwards_avg": round(st.mean([r.get("forwards") or 0 for r in rows]), 1),
                  "comments_avg": round(st.mean([r.get("comments") or 0 for r in rows]), 1)}
              for m, rows in sorted(by_month.items())}
    stats = json.loads((config.ROOT / "data" / "channel_stats.json").read_text(encoding="utf-8"))
    h = stats.get("headline", {})
    return {"channel_now": {k: h.get(k, {}).get("current") for k in
                            ("followers", "views_per_post", "shares_per_post", "reactions_per_post")},
            "channel_prev": {k: h.get(k, {}).get("previous") for k in
                             ("followers", "views_per_post", "shares_per_post", "reactions_per_post")},
            "stats_period": stats.get("period"),
            "mature_posts_by_month": months}


def _threads(edge: str) -> dict:
    r = factory_link.build(DAYS)
    app = threads_app_metrics.known()
    fact, pers = r["factory"], r["personal"]
    for p in fact:
        p["kind"] = (r["map"][str(p["id"])].get("kind") or "?")

    def funnel(rows: list[dict]) -> dict:
        have = [p for p in rows if str(p["id"]) in app]
        vw = sum(app[str(p["id"])].get("viewers") or 0 for p in have)
        pv = sum(app[str(p["id"])].get("profile_visits") or 0 for p in have)
        nf = sum(app[str(p["id"])].get("new_followers") or 0 for p in have)
        return {"posts": len(rows), "posts_measured": len(have), "viewers": vw,
                "profile_visits": pv, "new_followers": nf,
                "viewers_to_profile_pct": round(100 * pv / vw, 2) if vw else None,
                "profile_to_follow_pct": round(100 * nf / pv, 1) if pv else None,
                "views_median": round(st.median([p.get("views") or 0 for p in rows])) if rows else None,
                "people_avg": round(st.mean([p.get("people_count") or 0 for p in rows]), 2) if rows else None,
                "zero_profile_visits": sum(1 for p in have
                                           if not (app[str(p["id"])].get("profile_visits") or 0))}

    acc_log = config.ROOT / "data" / "threads_account_insights.jsonl"
    account = {}
    if acc_log.exists():
        rows = [json.loads(x) for x in acc_log.read_text(encoding="utf-8").splitlines() if x.strip()]
        if rows:
            account = rows[-1]

    # Рычаг «ставка»: считаем на постах с ≥100 зрителей, иначе доли шумят.
    stake = {"with": {"posts": 0, "viewers": 0, "profile_visits": 0, "new_followers": 0},
             "without": {"posts": 0, "viewers": 0, "profile_visits": 0, "new_followers": 0}}
    for p in fact:
        a = app.get(str(p["id"]))
        if not a or (a.get("viewers") or 0) < 100:
            continue
        key = "without" if any("НЕТ ставки" in c for c in threads_lint.check(p.get("text") or "")) else "with"
        stake[key]["posts"] += 1
        for f in ("viewers", "profile_visits", "new_followers"):
            stake[key][f] += a.get(f) or 0
    for key in stake:
        vw = stake[key]["viewers"]
        stake[key]["viewers_to_profile_pct"] = round(100 * stake[key]["profile_visits"] / vw, 2) if vw else None

    return {"account_last_snapshot": account,
            "flagship": funnel([p for p in fact if p["kind"] == "flagship"]),
            "scope": funnel([p for p in fact if p["kind"] == "scope"]),
            "factory_all": funnel(fact),
            "personal": funnel(pers),
            "stake_lever": stake}


def build() -> dict:
    edge = (date.today() - timedelta(days=DAYS)).isoformat()
    tg_posts = [p for p in json.loads((config.ROOT / "data" / "channel_posts.json")
                                      .read_text(encoding="utf-8")) if (p.get("date") or "")[:10] >= edge]
    th_posts = [p for p in json.loads((config.ROOT / "data" / "threads_posts.json")
                                      .read_text(encoding="utf-8")) if (p.get("date") or "")[:10] >= edge]
    money = _money(edge)
    made = len(tg_posts) + len(th_posts)
    return {
        "taken_at": datetime.now().isoformat(timespec="seconds"),
        "window_days": DAYS,
        "window_from": edge,
        "money": money,
        "production": {"telegram_posts": len(tg_posts), "threads_posts": len(th_posts),
                       "cost_per_post_usd": round(money["total_usd"] / made, 2) if made else None},
        "telegram": _telegram(edge),
        "threads": _threads(edge),
    }


def _last_two() -> tuple[dict | None, dict | None]:
    files = sorted(OUT_DIR.glob("????-??-??.json"))
    load = lambda f: json.loads(f.read_text(encoding="utf-8"))
    if not files:
        return None, None
    return (load(files[-2]) if len(files) > 1 else None), load(files[-1])


def _delta(now, was, digits: int = 0, suffix: str = "") -> str:
    """«872 (−204)» — число и изменение. Нет прошлого — просто число, без выдуманного нуля."""
    if now is None:
        return "—"
    body = f"{now:.{digits}f}{suffix}"
    if was is None:
        return body
    d = now - was
    return f"{body} ({d:+.{digits}f})"


def diff_text() -> str:
    """Короткое человеческое сравнение двух последних снимков — то, что уходит владельцу.

    Показываем ТОЛЬКО то, что решает: деньги, производство, обе площадки и воронку. Всё
    остальное лежит в JSON и ждёт вопроса; сообщение, которое лень дочитать, не читают вовсе."""
    was, now = _last_two()
    if not now:
        return "Снимков ещё нет."
    g = lambda d, *path: (None if d is None else
                          (lambda v: v)(_dig(d, path)))
    lines = [f"📊 Точка отсчёта {now['taken_at'][:10]}"
             + (f" против {was['taken_at'][:10]}" if was else " (первая, сравнивать не с чем)")]
    lines.append("\nДЕНЬГИ И ВЫПУСК за 90 дней")
    lines.append(f"   потрачено ${_delta(g(now,'money','total_usd'), g(was,'money','total_usd'), 2)} · "
                 f"постов {_delta(g(now,'production','telegram_posts'), g(was,'production','telegram_posts'))}"
                 f" в ТГ и {_delta(g(now,'production','threads_posts'), g(was,'production','threads_posts'))}"
                 f" в Threads · ${g(now,'production','cost_per_post_usd')}/пост")
    lines.append("\nTELEGRAM")
    lines.append(f"   подписчиков {_delta(g(now,'telegram','channel_now','followers'), g(was,'telegram','channel_now','followers'))}"
                 f" · просмотров на пост {_delta(g(now,'telegram','channel_now','views_per_post'), g(was,'telegram','channel_now','views_per_post'))}")
    lines.append("\nTHREADS — воронка заводских постов")
    for key, label in (("factory_all", "все заводские"), ("flagship", "мини-флагман"),
                       ("scope", "мини-скоуп"), ("personal", "личные (для сравнения)")):
        n, w = g(now, "threads", key), (g(was, "threads", key) if was else None)
        if not n:
            continue
        lines.append(f"   {label:24} в профиль {_delta(n.get('viewers_to_profile_pct'), (w or {}).get('viewers_to_profile_pct'), 2, '%')}"
                     f" · подписок {_delta(n.get('new_followers'), (w or {}).get('new_followers'))}")
    fa = g(now, "threads", "factory_all") or {}
    lines.append(f"   постов без единого захода в профиль: {fa.get('zero_profile_visits')} из {fa.get('posts_measured')}")
    st_now = g(now, "threads", "stake_lever") or {}
    if st_now:
        lines.append("\nРЫЧАГ СТАВКИ (заходов в профиль на 100 зрителей)")
        lines.append(f"   со ставкой {st_now.get('with',{}).get('viewers_to_profile_pct')}% "
                     f"(постов {st_now.get('with',{}).get('posts')}) · "
                     f"без ставки {st_now.get('without',{}).get('viewers_to_profile_pct')}% "
                     f"(постов {st_now.get('without',{}).get('posts')})")
    return "\n".join(lines)


def _dig(d: dict, path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def take(force: bool = False) -> tuple[bool, str]:
    """Снять точку, если пора (раз в месяц). Возвращает (снял ли, текст для владельца).

    Раз в месяц — потому что метрики, по которым мы судим, меняются медленно: недельная разница в
    охвате это шум площадки, а не результат наших правок."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(OUT_DIR.glob("????-??-??.json"))
    if files and not force:
        last = date.fromisoformat(files[-1].stem)
        if (date.today() - last).days < 28:
            return False, ""
    snap = build()
    (OUT_DIR / f"{date.today().isoformat()}.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, diff_text()


if __name__ == "__main__":
    import sys

    took, text = take(force="--force" in sys.argv)
    print(text if took else "Снимок за этот месяц уже есть — рано. Пересилить: --force")
