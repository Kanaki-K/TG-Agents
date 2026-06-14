"""Снапшоты метрик постов во времени (для динамики первых 7 дней).

Идея: просмотры/реакции растут несколько дней после публикации. Пишем «снимок»
метрик каждый день, пока посту < 7 дней. Потом смысла нет — только по запросу.

Берёт текущие метрики из data/channel_posts.json (его обновляет collect) и
дописывает строки в data/snapshots.json (append-only, по снимку на пост в день).

Запуск:
    python -m connectors.telegram_export.snapshot          # авто: только посты младше 7 дней
    python -m connectors.telegram_export.snapshot --all    # «обновить»: свежий снимок по ВСЕМ постам
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
POSTS_JSON = DATA / "channel_posts.json"
SNAPS = DATA / "snapshots.json"

FRESH_DAYS = 7   # пока посту меньше — снимаем автоматически


def _now():
    return datetime.now(timezone.utc)


def main() -> None:
    force_all = "--all" in sys.argv
    if not POSTS_JSON.exists():
        print("Нет channel_posts.json — сначала собери (collect)."); return
    posts = [p for p in json.loads(POSTS_JSON.read_text(encoding="utf-8"))
             if p.get("views") is not None]
    snaps = json.loads(SNAPS.read_text(encoding="utf-8")) if SNAPS.exists() else []

    now = _now()
    today = now.strftime("%Y-%m-%d")
    # уже снятые сегодня (чтобы не дублировать при авто-запуске)
    taken_today = {s["post_id"] for s in snaps if s.get("date") == today}

    added = 0
    for p in posts:
        if not p.get("date"):
            continue
        dt = datetime.fromisoformat(p["date"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (now - dt).days
        if not force_all:
            if age > FRESH_DAYS:        # старые посты авто не трогаем
                continue
            if p["id"] in taken_today:  # сегодня уже сняли
                continue
        reactions = p.get("likes_total") or sum(r.get("count", 0) for r in p.get("reactions", []))
        snaps.append({
            "date": today,
            "ts": now.isoformat(timespec="seconds"),
            "post_id": p["id"],
            "age_days": age,
            "views": p.get("views") or 0,
            "reactions": reactions,
            "comments": p.get("comments") or 0,
            "forwards": p.get("forwards") or 0,
        })
        added += 1

    SNAPS.write_text(json.dumps(snaps, ensure_ascii=False, indent=2), encoding="utf-8")
    mode = "ВСЕ посты (обновить)" if force_all else f"посты младше {FRESH_DAYS} дн."
    print(f"Снапшот ({mode}): добавлено {added} записей. Всего в истории: {len(snaps)}.")


if __name__ == "__main__":
    main()
