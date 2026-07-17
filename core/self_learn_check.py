"""Проверка петли само-обучения на РЕАЛЬНЫХ данных — read-only, ничего не меняет.

    python -m core.self_learn_check

Показывает:
1) распределение банка тем по 7 категориям (санити таксономии — покрыт ли банк, ровны ли бакеты);
2) каждый ВЫШЕДШИЙ флагман → его категория (проверка join'а «тема → банк → слой» на живых темах;
   UNKNOWN здесь = тревога: тема разошлась с банком и не привязалась);
3) состояние журнала дистилляций (связь флагман→Threads-серия).

Полного end-to-end (рейтинг категорий по перформансу) тут НЕТ: нужен линкер + зрелые данные.
Это проверка, что кирпичи 1-2 верно категоризируют реальные темы.
"""
from __future__ import annotations

import json
from collections import Counter

from core import config, threads_distill_journal, topic_category as tc

_FLAGSHIPS = config.ROOT / "data" / "published_flagships.jsonl"


def _bank_distribution() -> None:
    dist = Counter(tc._bank_map().values())
    total = sum(dist.values())
    print(f"[1] БАНК ТЕМ → категории (всего тем: {total})")
    for slug in tc.all_slugs():
        print(f"    {dist.get(slug, 0):>3}  {tc.label(slug)}")
    unknown = dist.get(tc.UNKNOWN, 0)
    if unknown:
        print(f"    {unknown:>3}  ⚠ UNKNOWN (тема вне слоёв — проверь заголовки банка)")


def _published_flagships() -> None:
    print("\n[2] ВЫШЕДШИЕ ФЛАГМАНЫ → категория (проверка join'а на живых темах)")
    if not _FLAGSHIPS.exists():
        print("    журнала флагманов нет — ещё ни один не вышел.")
        return
    rows = []
    for ln in _FLAGSHIPS.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    if not rows:
        print("    журнал пуст.")
        return
    unknown = 0
    for r in rows:
        theme = (r.get("theme") or "").strip()
        cat = tc.category_of(theme)
        mark = "  ⚠ НЕ ПРИВЯЗАН" if cat == tc.UNKNOWN else ""
        if cat == tc.UNKNOWN:
            unknown += 1
        print(f"    {r.get('date', '?'):<11} [{tc.label(cat) if cat != tc.UNKNOWN else 'UNKNOWN'}]{mark}")
        print(f"                «{theme[:70]}»")
    ok = len(rows) - unknown
    print(f"    → привязано {ok}/{len(rows)}"
          + (f", НЕ привязано {unknown} (тема разошлась с банком)" if unknown else " — join чистый ✓"))


def _distill_journal() -> None:
    print("\n[3] ЖУРНАЛ ДИСТИЛЛЯЦИЙ (связь флагман → Threads-серия)")
    entries = threads_distill_journal.entries()
    if not entries:
        print("    пусто — журнал пишет только БУДУЩИЕ прогоны дистиллятора. Появится с первого прогона.")
        return
    for e in entries:
        print(f"    {e.get('flagship_date', '?'):<11} [{tc.label(e.get('category', ''))}] "
              f"постов: {len(e.get('posts', []))}  тема: «{(e.get('theme') or '')[:50]}»")


def main() -> None:
    print("=" * 70)
    print("ПРОВЕРКА ПЕТЛИ САМО-ОБУЧЕНИЯ (read-only, на реальных данных)")
    print("=" * 70)
    _bank_distribution()
    _published_flagships()
    _distill_journal()
    print("\nПолный рейтинг категорий по перформансу появится, когда будет линкер + зрелые данные.")


if __name__ == "__main__":
    main()
