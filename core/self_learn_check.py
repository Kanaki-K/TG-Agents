"""Проверка петли само-обучения на РЕАЛЬНЫХ данных — read-only, ничего не меняет.

    python -m core.self_learn_check

Показывает:
1) распределение банка тем по 7 категориям (санити таксономии);
2) каждый ВЫШЕДШИЙ флагман → его категория (проверка join'а «тема→банк→слой»; UNKNOWN = тревога);
3) состояние журнала дистилляций;
4) ПОЛНЫЙ проход: флагман+дистилляция → балл темы → рейтинг категорий (линкер + сборка + оценка).

Пункт [4] реально работает только на СВЕЖИХ данных: нужны Threads-посты этой недели
(прогони refresh_threads.py) — иначе линковать нечего. Интеграции в пайплайн тут НЕТ.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date, timedelta

from core import (analytics, category_scoring, config, tg_scoring,
                  threads_distill_journal, topic_category as tc, topic_datapoints)
from connectors.threads import scoring as th_scoring

_FLAGSHIPS = config.ROOT / "data" / "published_flagships.jsonl"
_THREADS_POSTS = config.ROOT / "data" / "threads_posts.json"


def _load_flagships() -> list[dict]:
    if not _FLAGSHIPS.exists():
        return []
    rows = []
    for ln in _FLAGSHIPS.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return rows


def _load_threads_posts() -> list[dict]:
    if not _THREADS_POSTS.exists():
        return []
    try:
        return json.loads(_THREADS_POSTS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _fresh_note(created: str) -> str:
    """Объяснить, почему балл ещё None: посты моложе гейта зрелости (это норма, не поломка)."""
    mdays = th_scoring.MATURITY_DAYS
    try:
        c = date.fromisoformat((created or "")[:10])
    except ValueError:
        return "балл: — (нет зрелых данных)"
    age = (date.today() - c).days
    if age < mdays:
        ripe = (c + timedelta(days=mdays)).strftime("%d.%m")
        return f"балл: — рано судить (посты ~{age} дн из {mdays}; оценка ≈ после {ripe})"
    return "балл: — нет зрелых цифр (пост без охвата / ТГ не привязался)"


def _bank_distribution() -> None:
    dist = Counter(tc._bank_map().values())
    print(f"[1] БАНК ТЕМ → категории (всего тем: {sum(dist.values())})")
    for slug in tc.all_slugs():
        print(f"    {dist.get(slug, 0):>3}  {tc.label(slug)}")
    if dist.get(tc.UNKNOWN):
        print(f"    {dist[tc.UNKNOWN]:>3}  ⚠ UNKNOWN (тема вне слоёв — проверь заголовки банка)")


def _published_flagships(rows: list[dict]) -> None:
    print("\n[2] ВЫШЕДШИЕ ФЛАГМАНЫ → категория (проверка join'а на живых темах)")
    if not rows:
        print("    журнала флагманов нет — ещё ни один не вышел.")
        return
    unknown = 0
    for r in rows:
        theme = (r.get("theme") or "").strip()
        cat = tc.category_of(theme)
        if cat == tc.UNKNOWN:
            unknown += 1
        name = tc.label(cat) if cat != tc.UNKNOWN else "UNKNOWN ⚠ НЕ ПРИВЯЗАН"
        print(f"    {r.get('date', '?'):<11} [{name}]")
        print(f"                «{theme[:70]}»")
    ok = len(rows) - unknown
    print(f"    → привязано {ok}/{len(rows)}"
          + (f", НЕ привязано {unknown}" if unknown else " — join чистый ✓"))


def _distill_journal() -> None:
    print("\n[3] ЖУРНАЛ ДИСТИЛЛЯЦИЙ (связь флагман → Threads-серия)")
    entries = threads_distill_journal.entries()
    if not entries:
        print("    пусто — журнал пишет только БУДУЩИЕ прогоны дистиллятора.")
        return
    for e in entries:
        print(f"    {e.get('flagship_date', '?'):<11} [{tc.label(e.get('category', ''))}] "
              f"постов: {len(e.get('posts', []))}  «{(e.get('theme') or '')[:50]}»")


def _evaluation(flagships: list[dict]) -> None:
    print("\n[4] ОЦЕНКА ТЕМ/КАТЕГОРИЙ (полный проход: линк → сборка → балл → рейтинг)")
    if not flagships:
        print("    флагманов нет — оценивать нечего.")
        return
    threads_posts = _load_threads_posts()
    if not threads_posts:
        print("    Threads-постов нет (data/threads_posts.json пуст) — прогони refresh_threads.py.")
        return
    tg_posts = analytics._load_posts()
    tg_scoring.enrich(tg_posts)
    th_scoring.enrich(threads_posts)
    res = topic_datapoints.build(threads_distill_journal.entries(), flagships, tg_posts, threads_posts)
    dps = res["datapoints"]
    if not dps:
        print(f"    ни один флагман не связался с Threads-постами (постов вне окна/покрытия: "
              f"{len(res['unmatched_threads'])}).")
        print("    Вероятно, Threads-данные несвежие (нет постов этой недели) — обнови refresh_threads.py.")
        return
    print(f"    датапоинтов: {len(dps)} | Threads-постов не привязано: {len(res['unmatched_threads'])}")
    for dp in dps:
        sc = category_scoring.topic_score(dp["tg_quality"], dp["threads_best"])
        if sc is None:
            verdict = _fresh_note(dp["created"])       # None не из-за поломки — посты ещё зреют
        else:
            verdict = f"балл темы: {sc}"
        print(f"    {dp['created']} [{tc.label(dp['category'])}] {verdict}  (связь: {dp.get('via') or '?'})")
        print(f"                ТГ {dp['tg_quality']} · Threads-best {dp['threads_best']} из "
              f"{dp['n_threads']} постов  «{(dp['theme'] or '')[:52]}»")
    rows = category_scoring.leaderboard(dps, today=date.today())
    print("\n    " + category_scoring.render(rows).replace("\n", "\n    "))


def main() -> None:
    print("=" * 70)
    print("ПРОВЕРКА ПЕТЛИ САМО-ОБУЧЕНИЯ (read-only, на реальных данных)")
    print("=" * 70)
    flagships = _load_flagships()
    _bank_distribution()
    _published_flagships(flagships)
    _distill_journal()
    _evaluation(flagships)
    print("\nИнтеграция в пайплайн (влияние на выбор тем) — отдельным шагом, по команде владельца.")


if __name__ == "__main__":
    main()
