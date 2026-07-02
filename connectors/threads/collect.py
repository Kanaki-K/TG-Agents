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
import re
import sys
import time
from pathlib import Path

from connectors.threads import insights, read, replies

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
POSTS_OUT = DATA / "threads_posts.json"
STATS_OUT = DATA / "threads_stats.json"

_DAY = 86400
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


def collect_posts(limit: int) -> list[dict]:
    posts = read.recent(limit=limit)
    ids = [p["id"] for p in posts if p.get("id")]
    print(f"Постов получено: {len(posts)}. Тяну метрики по каждому...")
    metrics = insights.metrics_for(ids)
    rows = [_merge_post(p, metrics.get(p["id"], {})) for p in posts]
    errs = sum(1 for r in rows if r["metrics_error"])
    if errs:
        print(f"⚠ метрики не пришли для {errs}/{len(rows)} постов "
              f"(норма для постов старше апреля 2024 или без прав insights).")

    # Живой отклик: тянем комменты только там, где ответы вообще есть (экономим запросы —
    # если replies==0, чужих комментов заведомо нет). Отделяем людей от self-тредов.
    todo = [r for r in rows if r["replies"] > 0]
    print(f"Разбираю комменты (люди vs self-треды) по {len(todo)} постам с ответами...")
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
    except Exception as e:  # noqa: BLE001 — сводка не критична, посты важнее
        out["account"] = {"error": str(e)}
    out["demographics"] = {
        b: insights.follower_demographics(breakdown=b)
        for b in ("country", "city", "age", "gender")
    }
    return out


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 500
    DATA.mkdir(exist_ok=True)

    rows = collect_posts(limit)
    # merge со старым файлом: свежие метрики перекрывают, посты не теряем
    old = {}
    if POSTS_OUT.exists():
        try:
            old = {p["id"]: p for p in json.loads(POSTS_OUT.read_text(encoding="utf-8"))}
        except Exception:  # noqa: BLE001
            old = {}
    for r in rows:
        old[r["id"]] = r
    merged = sorted(old.values(), key=lambda r: r.get("date", ""))
    POSTS_OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    stats = collect_stats()
    STATS_OUT.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    total_views = sum(r["views"] for r in merged)
    print(f"\n✅ Постов в базе: {len(merged)} (просмотров суммарно: {total_views})")
    print(f"   Посты → {POSTS_OUT}")
    print(f"   Сводка аккаунта → {STATS_OUT}")
    print("Дальше: python -m connectors.threads.enrich_topics  (темы)  →  "
          "python -m connectors.threads.build_table  (таблица)")


if __name__ == "__main__":
    main()
