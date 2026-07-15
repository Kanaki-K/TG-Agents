"""Сбор своих постов Threads + метрики → data/threads_posts.json и threads_stats.json.

Аналог telegram_export/collect.py, но через официальный Threads API (без MTProto/сессий —
доступ уже держит токен из auth.py). Даёт аналитику тот же материал, что и по ТГ-каналу:
пост + дата + метрики. Дальше enrich_topics.py размечает темы, build_table.py строит таблицу.

Что собирается:
  - посты владельца (текст, дата, ссылка, тип медиа) — read.recent()
  - метрики каждого поста (views/likes/replies/reposts/quotes/shares) — insights
  - сводка аккаунта за период + демография подписчиков — для листа «Сводка»

Идемпотентно: повторный запуск ДОПОЛНЯЕТ базу (метрики свежих постов растут — их
обновляем; старые остаются). Так же дёшево гонять регулярно, как ТГ-сбор.

Запуск:
    python -m connectors.threads.collect            # все посты (до кэпа) + метрики
    python -m connectors.threads.collect 50         # только последние 50 постов
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from connectors.threads import _api, insights, read, replies

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
POSTS_OUT = DATA / "threads_posts.json"
STATS_OUT = DATA / "threads_stats.json"

_DAY = 86400
# Нахлёст watermark: пост мог выйти, пока прошлый сбор ещё шёл. Без нахлёста он бы провалился
# в дыру навсегда — инкрементальность не должна покупаться дырами в данных.
_OVERLAP_DAYS = 7
# Старше этого срока пост уже не набирает ни просмотров, ни комментов — метрики не перезапрашиваем.
_METRICS_FRESH_DAYS = int(os.getenv("THREADS_FRESH_DAYS", "30"))
# «Живые» типы медиа (текстовый пост — это «без медиа»).
_TEXT_TYPES = {"", "TEXT_POST", "TEXT"}
# Детекторы того, что душит охват (см. память threads-reach-killers).
_LINK_RE = re.compile(r"https?://|t\.me/|\bwww\.", re.IGNORECASE)
_HASHTAG_RE = re.compile(r"(?:^|\s)#[\wЀ-ӿ]+")


def _engagement(m: dict) -> int:
    """Суммарная вовлечённость поста (аналог «реакций» у ТГ): лайки+ответы+репосты+цитаты+шеры."""
    return sum(int(m.get(k) or 0) for k in ("likes", "replies", "reposts", "quotes", "shares"))


def _merge_post(post: dict, metrics: dict) -> dict:
    """Нормализованный пост (read) + метрики (insights) → одна плоская запись для аналитика."""
    m = {} if not isinstance(metrics, dict) or metrics.get("error") else metrics
    views = int(m.get("views") or 0)
    eng = _engagement(m)
    text = post.get("text", "") or ""
    media_type = post.get("media_type", "")
    return {
        "platform": "threads",
        "id": post.get("id", ""),
        "date": post.get("timestamp", ""),          # ISO-8601 от Meta
        "text": text,
        "permalink": post.get("permalink", ""),
        "media_type": media_type,
        "has_media": media_type not in _TEXT_TYPES,   # медиа/без медиа — отдельная ось анализа
        "is_quote": bool(post.get("is_quote")),
        "has_link": bool(_LINK_RE.search(text)),      # душители охвата — прямо в данные
        "has_hashtag": bool(_HASHTAG_RE.search(text)),
        # метрики Threads (могут отсутствовать у старых постов до апреля 2024 — тогда 0)
        "views": views,
        "likes": int(m.get("likes") or 0),
        "replies": int(m.get("replies") or 0),        # ВСЕ ответы (свои + чужие)
        "reposts": int(m.get("reposts") or 0),
        "quotes": int(m.get("quotes") or 0),
        "shares": int(m.get("shares") or 0),
        "engagement": eng,
        "er": round(eng / views * 100, 2) if views else None,
        # живой отклик людей (заполняется отдельным проходом по conversation)
        "people_replies": 0,     # ответы ДРУГИХ людей — честный сигнал «зашло»
        "people_count": 0,       # сколько РАЗНЫХ людей отписалось
        "self_replies": 0,       # свои ответы (длина self-треда)
        "replies_error": None,
        "metrics_error": metrics.get("error") if isinstance(metrics, dict) else None,
    }


def _watermark(old: dict[str, dict]) -> int | None:
    """С какого момента запрашивать ленту. None = с начала (первый сбор).

    ЗАЧЕМ (15.07.2026). Раньше collect звал read.recent(500) БЕЗ since — то есть каждый прогон
    тянул всю ленту заново, хотя посты уже лежали на диске. Инкрементальным был только merge
    файла, не трафик. Именно поэтому 14.07 три повторных захода превратились в три ПОЛНЫХ прохода
    подряд — а Meta видит запросы, а не наши файлы.

    Берём дату самого свежего известного поста минус нахлёст: пост мог выйти, пока прошлый сбор
    ещё шёл, и без нахлёста он бы навсегда провалился в дыру.
    """
    dates = [p.get("date") or "" for p in old.values()]
    newest = max((d for d in dates if d), default="")
    if not newest:
        return None
    try:
        ts = time.mktime(time.strptime(newest[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return None
    return int(ts - _OVERLAP_DAYS * _DAY)


def _needs_metrics(row: dict, old: dict[str, dict]) -> bool:
    """Тянуть ли метрики этого поста. Старые посты уже не растут — не трогаем.

    Это вторая по величине экономия после watermark: раньше metrics_for шёл по ВСЕМ 500 постам,
    то есть 500 отдельных запросов подряд за каждый прогон.
    """
    prev = old.get(row["id"])
    if not prev or prev.get("metrics_error") or prev.get("metrics_stale"):
        return True                       # ещё не собрали или собрали неудачно
    if not prev.get("views"):
        return True
    age_days = _age_days(row.get("date") or "")
    return age_days is None or age_days <= _METRICS_FRESH_DAYS


def _needs_replies(row: dict, old: dict[str, dict]) -> bool:
    """Разбирать ли комменты этого поста. Под старым постом новые вряд ли появятся."""
    prev = old.get(row["id"])
    if not prev or prev.get("replies_error") or prev.get("replies_stale"):
        return True
    if not prev.get("people_replies") and not prev.get("self_replies"):
        return True                       # разбора ещё не было
    age_days = _age_days(row.get("date") or "")
    return age_days is None or age_days <= _METRICS_FRESH_DAYS


def _age_days(iso: str) -> float | None:
    try:
        ts = time.mktime(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return None
    return (time.time() - ts) / _DAY


def _row_for(post: dict, metrics: dict[str, dict], old: dict[str, dict]) -> dict:
    """Запись поста: свежие поля + метрики. Если метрики намеренно НЕ тянули — берём их из базы.

    Тонкость, которая тут легко теряется: `_merge_post(post, {})` даёт нули, а не «нет данных».
    Записать такую строку в базу = стереть накопленное. Поэтому пропуск по возрасту обязан
    ПЕРЕНОСИТЬ старые цифры, а не оставлять пустое место.
    """
    pid = post.get("id", "")
    if pid in metrics:
        return _merge_post(post, metrics[pid])
    row = _merge_post(post, {})                  # текст/ссылка/тип медиа — всегда свежие
    prev = old.get(pid)
    if prev:
        for k in _FROM_INSIGHTS + _FROM_REPLIES:
            if prev.get(k) is not None:
                row[k] = prev[k]
        row["metrics_error"] = prev.get("metrics_error")
    return row


def collect_posts(limit: int, old: dict[str, dict] | None = None) -> list[dict]:
    old = old or {}
    since = _watermark(old)
    if since:
        print(f"Инкрементальный сбор: лента с {time.strftime('%d.%m.%Y', time.localtime(since))} "
              f"(в базе уже {len(old)} постов — заново их не тянем).")
    posts = read.recent(limit=limit, since=since)
    print(f"Постов получено: {len(posts)}.")

    # Метрики — только там, где они реально могут измениться.
    skeleton = [_merge_post(p, {}) for p in posts]
    fresh = [s for s in skeleton if _needs_metrics(s, old)]
    ids = [s["id"] for s in fresh]

    # Добор «долгов»: посты, по которым метрики так и не собрались (сбой/бюджет кончился). Лента их
    # уже не отдаст — они старше окна watermark, — но id у нас есть, и insights принимает id напрямую.
    # Без этого добора недобранный пост завис бы с нулями НАВСЕГДА: watermark его не вернёт.
    debt = [pid for pid, p in old.items()
            if pid not in ids and (p.get("metrics_error") or p.get("metrics_stale"))]
    if debt:
        print(f"Добираю метрики по {len(debt)} постам, недособранным в прошлые разы.")
        ids += debt

    print(f"Тяну метрики по {len(ids)} постам "
          f"(посты старше {_METRICS_FRESH_DAYS} дн не трогаем — их цифры уже не растут).")
    metrics = insights.metrics_for(ids)
    rows = [_row_for(p, metrics, old) for p in posts]
    errs = sum(1 for r in rows if r["metrics_error"])
    if errs:
        print(f"⚠ метрики не пришли для {errs}/{len(rows)} постов "
              f"(норма для постов старше апреля 2024 или без прав insights).")

    # Живой отклик: тянем комменты только там, где ответы вообще есть (если replies==0, чужих
    # комментов заведомо нет) И где они ещё могут появиться. Отделяем людей от self-тредов.
    # Каждый такой пост — это МИНИМУМ ещё один запрос, а с пагинацией и больше; раньше проход шёл
    # по всем постам с ответами за всю историю, каждый прогон.
    todo = [r for r in rows if r["replies"] > 0 and _needs_replies(r, old)]
    skipped = sum(1 for r in rows if r["replies"] > 0) - len(todo)
    print(f"Разбираю комменты (люди vs self-треды) по {len(todo)} постам"
          f"{f' (пропущено {skipped} старых — их разбор уже в базе)' if skipped else ''}...")
    aud = replies.audience_for_many([r["id"] for r in todo])
    for r in todo:
        a = aud.get(r["id"], {})
        r["people_replies"] = a.get("people_replies", 0)
        r["people_count"] = a.get("people_count", 0)
        r["self_replies"] = a.get("self_replies", 0)
        r["replies_error"] = a.get("error")
    live = sum(1 for r in rows if r["people_replies"] > 0)
    print(f"Постов с ЖИВЫМИ комментами людей: {live} (из {len(rows)}).")
    return rows


def collect_stats() -> dict:
    """Сводка аккаунта за последние 30 дней + демография (демография требует ≥100 подписчиков)."""
    until = int(time.time())
    since = until - 30 * _DAY
    out: dict = {"period": {"from": since, "to": until}}
    try:
        out["account"] = insights.account_insights(since=since, until=until)
    except _api.ThreadsBlocked:
        raise  # защита обязана пробивать наверх: голое `except Exception` глотало и её тоже
    except Exception as e:  # noqa: BLE001 — сводка не критична, посты важнее
        out["account"] = {"error": str(e)}
    out["demographics"] = {
        b: insights.follower_demographics(breakdown=b)
        for b in ("country", "city", "age", "gender")
    }
    return out


def _load_old() -> dict[str, dict]:
    if not POSTS_OUT.exists():
        return {}
    try:
        return {p["id"]: p for p in json.loads(POSTS_OUT.read_text(encoding="utf-8"))}
    except Exception:  # noqa: BLE001
        return {}


# Заработанные цифры, которые НЕЛЬЗЯ перезаписывать нулём из неудачного прогона.
_FROM_INSIGHTS = ("views", "likes", "replies", "reposts", "quotes", "shares", "engagement", "er")
_FROM_REPLIES = ("people_replies", "people_count", "self_replies")


def _merge_keep(old_row: dict | None, new_row: dict) -> dict:
    """Слить старую запись с новой, НЕ теряя уже собранные метрики при сбое.

    Баг, который это чинит (15.07.2026): раньше было безусловное `old[id] = new`. При троттлинге
    insights возвращал {"error": ...} по каждому посту → _merge_post превращал это в views=0 →
    merge затирал накопленную базу нулями. То есть рейт-лимит не просто не тормозил нас, он ещё и
    молча уничтожал данные, ради которых всё затевалось. Хуже всего, что тихо: в файле лежали
    правдоподобные нули, и отличить «пост не зашёл» от «нас лимитнули» было уже нельзя.

    Правило: текст/ссылка/тип медиа — всегда свежие (они не «зарабатываются»), а заработанные
    цифры перезаписываются ТОЛЬКО если прогон реально их принёс.
    """
    if not old_row:
        return new_row
    row = dict(new_row)
    if new_row.get("metrics_error"):
        for k in _FROM_INSIGHTS:
            if old_row.get(k) not in (None, 0):
                row[k] = old_row[k]
        row["metrics_stale"] = True   # видно в таблице: цифра старая, а не «пост умер»
    if new_row.get("replies_error"):
        for k in _FROM_REPLIES:
            if old_row.get(k):
                row[k] = old_row[k]
        row["replies_stale"] = True
    return row


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 500
    DATA.mkdir(exist_ok=True)

    old = _load_old()
    try:
        rows = collect_posts(limit, old)
    except _api.ThreadsBlocked as e:
        # Защита сработала (троттлинг/бюджет/закрытая сеть). База на диске НЕ трогается —
        # лучше остаться со вчерашними данными, чем записать поверх них мусор.
        print(f"\n⛔ Сбор остановлен защитой: {e}")
        print("   База на диске не изменена. Повторить можно позже — данные не потеряны.")
        return

    for r in rows:
        old[r["id"]] = _merge_keep(old.get(r["id"]), r)
    merged = sorted(old.values(), key=lambda r: r.get("date", ""))
    POSTS_OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    stale = sum(1 for r in merged if r.get("metrics_stale"))
    if stale:
        print(f"⚠ У {stale} постов метрики НЕ обновились — оставлены прежние значения "
              f"(не перезаписаны нулями). Это не потеря данных.")

    try:
        stats = collect_stats()
        STATS_OUT.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    except _api.ThreadsBlocked as e:
        print(f"⚠ Сводка аккаунта не собрана (защита: {e}). Посты сохранены.")

    total_views = sum(r["views"] for r in merged)
    print(f"\n✅ Постов в базе: {len(merged)} (просмотров суммарно: {total_views})")
    print(f"   Посты → {POSTS_OUT}")
    print(f"   Сводка аккаунта → {STATS_OUT}")
    print("Дальше: python -m connectors.threads.enrich_topics  (темы)  →  "
          "python -m connectors.threads.build_table  (таблица)")


if __name__ == "__main__":
    main()
