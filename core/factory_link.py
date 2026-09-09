"""Опознание постов Threads, сделанных ЗАВОДОМ, среди всей ленты аккаунта.

ЗАЧЕМ. В Threads у владельца два потока: личное (Сакартвело, «мне одному впадло») и переработки
постов контент-завода (флагман/скоуп из ТГ). Аналитика по всей ленте бесполезна для обучения:
личный пост с 32 собеседниками ничему не учит писателя постов про SEC. Учиться и мерить надо
ТОЛЬКО на заводских — значит их сначала нужно отделить, и не глазами.

КАК ОПОЗНАЁМ. Два слоя, от точного к правдоподобному:

1. **ID** — когда публикацию делает сам завод, id вышедшего поста Threads пишется в журнал
   переработок (`threads_distill_journal`). Тогда связь детерминированная, сверять нечего.
2. **Дата + общие токены** — историю (посты, которые владелец делал руками через браузер) ID не
   закрывает: журнала тогда не было. Но ТГ-пост и его Threads-версия выходили В ОДИН ДЕНЬ и
   неизбежно делят редкие слова — имена, числа, термины повода. Этого достаточно: личный пост того
   же дня общих токенов с постом про трансфер-агентов не имеет.

Порог покрытия НИЗКИЙ намеренно (0.3): Threads-версия — не сокращение, а переписывание под площадку,
у неё свои формулировки. Ошибиться в другую сторону дороже: пропущенный заводской пост просто не
попадёт в замер, а лишний личный — исказит вывод об обучении.

РУЧНЫЕ ПОПРАВКИ. Карта лежит в data/threads_factory_map.json и переживает пересборку: связи,
помеченные `"by": "рука"`, автоматика не трогает. Владелец видит спорные случаи в отчёте и правит
их там же, а не спорит с алгоритмом.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from core import config, content_plan, io_safe, text_match

THREADS_POSTS = config.ROOT / "data" / "threads_posts.json"
TG_POSTS = config.ROOT / "data" / "channel_posts.json"
TG_FORMATS = config.ROOT / "data" / "post_formats.json"
MAP_FILE = config.ROOT / "data" / "threads_factory_map.json"

WINDOW_DAYS = 1        # Threads-версия выходит в тот же день или на следующий (владелец: «в одну дату»)
MIN_COVERAGE = 0.30    # доля токенов Threads-поста, найденных в ТГ-посте
# ...но одной доли мало: у короткой личной реплики токенов три, и любые два общих слова дают «две
# трети совпало». Поэтому вторым условием — АБСОЛЮТНОЕ число общих редких слов. Реальный промах,
# из-за которого условие появилось: «Просто хочется денег» (3 токена) прилипло к флагману про майнинг.
MIN_SHARED = 5         # сколько отличительных слов ДОЛЖНО совпасть, чтобы считать это переработкой
MIN_CHARS_TG = 300     # короче — футер/анонс, не пост завода
NOT_OUR_TAGS = {"служебное", "медиа", "личный", "психология", "обучающий"}


def _day(s: str):
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def tg_factory_posts(since_days: int = 90) -> list[dict]:
    """Посты ЗАВОДА в ТГ за последние N дней: флагман и скоуп, без личного и служебного.

    Формат берём длиной (единый порог завода), а разметку Аналитика используем только как фильтр
    «наш ли это контент» — она отстаёт с июня и свежие посты не размечены."""
    tags = io_safe.load_json(TG_FORMATS, {})
    edge = date.today() - timedelta(days=since_days)
    out = []
    for p in io_safe.load_json(TG_POSTS, []):
        d, text = _day(p.get("date", "")), (p.get("text") or "").strip()
        if not d or d < edge or len(text) < MIN_CHARS_TG:
            continue
        if (tags.get(str(p.get("id"))) or "").strip().lower() in NOT_OUR_TAGS:
            continue
        out.append({"id": p.get("id"), "date": d.isoformat(),
                    "kind": content_plan.norm_kind(content_plan.infer_kind(text)), "text": text})
    return sorted(out, key=lambda r: r["date"])


def _known_ids() -> dict[str, dict]:
    """Связи, известные ТОЧНО: id постов, записанные журналом переработок при авто-публикации."""
    from core import threads_distill_journal
    known: dict[str, dict] = {}
    for e in threads_distill_journal.entries():
        for pid in e.get("post_ids") or []:
            known[str(pid)] = {"tg_date": e.get("flagship_date", ""), "theme": e.get("theme", ""),
                               "by": "журнал"}
    return known


def build(since_days: int = 90, window: int = WINDOW_DAYS,
          min_coverage: float = MIN_COVERAGE) -> dict:
    """Собрать карту «пост Threads → пост завода в ТГ». Ручные пометки в файле сохраняются.

    Возвращает {"map": {id_threads: {...}}, "factory": [...], "personal": [...]}, где factory/personal —
    сами посты Threads (для отчёта и аналитики)."""
    old = io_safe.load_json(MAP_FILE, {})
    manual = {k: v for k, v in old.items() if (v or {}).get("by") == "рука"}
    known = _known_ids()

    tg = tg_factory_posts(since_days)
    edge = date.today() - timedelta(days=since_days)
    threads = [p for p in io_safe.load_json(THREADS_POSTS, [])
               if (p.get("text") or "").strip() and (_day(p.get("date", "")) or edge) >= edge]

    new_map: dict[str, dict] = {}
    factory, personal = [], []
    for p in sorted(threads, key=lambda r: r.get("date") or ""):
        pid, pd = str(p.get("id")), _day(p.get("date", ""))
        if pid in manual:                                  # рука владельца сильнее алгоритма
            new_map[pid] = manual[pid]
            (factory if manual[pid].get("tg_id") else personal).append(p)
            continue
        if pid in known:                                   # авто-публикация: связь известна точно
            new_map[pid] = known[pid]
            factory.append(p)
            continue
        best, best_cov, best_shared = None, 0.0, 0
        p_tokens = text_match.tokens(p.get("text", ""))
        for t in tg:
            td = _day(t["date"])
            if td is None or pd is None or not (td <= pd <= td + timedelta(days=window)):
                continue
            shared = len(p_tokens & text_match.tokens(t["text"]))
            cov = text_match.coverage(p.get("text", ""), t["text"])
            if cov > best_cov:
                best, best_cov, best_shared = t, cov, shared
        if best and best_cov >= min_coverage and best_shared >= MIN_SHARED:
            new_map[pid] = {"tg_id": best["id"], "tg_date": best["date"], "kind": best["kind"],
                            "coverage": round(best_cov, 2), "shared": best_shared, "by": "дата+слова"}
            factory.append(p)
        else:
            new_map[pid] = {"tg_id": None, "by": "не опознан", "coverage": round(best_cov, 2),
                            "shared": best_shared}
            personal.append(p)
    try:
        MAP_FILE.write_text(json.dumps(new_map, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logging.exception("factory_link: карту не сохранил (в памяти она есть)")
    return {"map": new_map, "factory": factory, "personal": personal, "tg": tg}


def mark(threads_id: str, tg_id, kind: str = "") -> str:
    """Поправить связь РУКОЙ: привязать пост Threads к посту ТГ (или отвязать, tg_id=None).

    Такие записи помечаются `by: рука` и переживают пересборку карты — алгоритм их не трогает."""
    m = io_safe.load_json(MAP_FILE, {})
    m[str(threads_id)] = ({"tg_id": tg_id, "kind": content_plan.norm_kind(kind) if kind else "",
                           "by": "рука"} if tg_id else {"tg_id": None, "by": "рука"})
    MAP_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"Связь записана рукой: {threads_id} → {tg_id or 'НЕ заводской'}"


# ── Отчёт: как живут ИМЕННО заводские посты ───────────────────────────────────────────────────────
# Владелец 09.09: «меня интересовали исключительно посты скоуп/флагмана за последние 90 дней, как
# начал работать контент-завод». Личное (Сакартвело, беговая дорожка) в замер не идёт: писателя
# постов про SEC оно ничему не учит, а средние портит.
_METRICS = (("views", "просмотры"), ("likes", "лайки"), ("replies", "ответы"),
            ("people_count", "людей в ответах"), ("people_replies", "ответы людей"),
            ("reposts", "репосты"), ("quotes", "цитаты"), ("shares", "поделились"))


def _avg(rows: list[dict], key: str) -> float:
    return round(sum(r.get(key) or 0 for r in rows) / len(rows), 1) if rows else 0.0


def report(since_days: int = 90, top: int = 8) -> str:
    """Текстовый разбор заводских постов Threads: средние по форматам, лидеры, что не опознано."""
    r = build(since_days)
    m, factory, personal = r["map"], r["factory"], r["personal"]
    by_kind: dict[str, list] = {}
    for p in factory:
        by_kind.setdefault(m[str(p["id"])].get("kind") or "?", []).append(p)

    out = [f"🧵 ЗАВОДСКИЕ посты Threads за {since_days} дн: {len(factory)} "
           f"(личных/не опознано — {len(personal)}, в замер не идут)",
           f"   ТГ-постов завода за тот же срок: {len(r['tg'])} — из них переработано "
           f"{len({m[str(p['id'])].get('tg_id') for p in factory})}"]
    for kind, rows in sorted(by_kind.items()):
        out.append(f"\n▸ {kind} — постов {len(rows)}")
        out.append("   " + " · ".join(f"{label} {_avg(rows, key)}" for key, label in _METRICS))
    if personal:
        out.append(f"\n▸ личное (для сравнения) — постов {len(personal)}")
        out.append("   " + " · ".join(f"{label} {_avg(personal, key)}" for key, label in _METRICS))

    out.append(f"\n🏆 ЛИДЕРЫ среди заводских — по числу РАЗНЫХ людей в ответах (сигнал владельца):")
    for p in sorted(factory, key=lambda x: ((x.get("people_count") or 0), (x.get("views") or 0)),
                    reverse=True)[:top]:
        link = m[str(p["id"])]
        head = " ".join((p.get("text") or "").split())[:64]
        out.append(f"   {p.get('date','')[:10]} люди:{p.get('people_count',0):>2} "
                   f"ответов:{p.get('people_replies',0):>2} просм:{p.get('views',0):>6} "
                   f"репост:{p.get('reposts',0):>2} ← ТГ #{link.get('tg_id')} [{link.get('kind')}] «{head}»")
    weak = [p for p in factory if not (p.get("people_count") or 0)]
    out.append(f"\n⚠️ Заводских постов БЕЗ единого собеседника: {len(weak)} из {len(factory)} — "
               "материал для разбора «почему молчат».")
    # Подписки. На пост их Meta не отдаёт вообще — единственный доступный сигнал это дневной
    # прирост счётчика аккаунта, который мы копим сами с 09.09.2026 (core/threads_followers).
    from core import threads_app_metrics, threads_followers
    out.append("\n" + threads_followers.report(factory))
    # Подписки и заходы в профиль НА ПОСТ есть только в приложении (проверено запросами 09.09:
    # Meta перечисляет допустимые метрики явно, этих там нет). Владелец присылает их вставкой.
    out.append("\n" + threads_app_metrics.funnel_report())
    return "\n".join(out)


if __name__ == "__main__":
    import sys

    days = next((int(a) for a in sys.argv[1:] if a.isdigit()), 90)
    print(report(days))
