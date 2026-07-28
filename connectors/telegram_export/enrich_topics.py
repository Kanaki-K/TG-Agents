"""Обогащение постов Telegram-канала: заголовок/тема/КАТЕГОРИЯ/угол/суть (через Claude).

Каркас общий с Threads — connectors.enrich_common (чтобы не дрейфовать, N-49). Здесь только
специфика площадки: свои посты (без служебных сообщений), преамбула, out-файл.

    python -m connectors.telegram_export.enrich_topics          # только новые
    python -m connectors.telegram_export.enrich_topics --all    # пересчитать всё
"""
from __future__ import annotations

import sys
from pathlib import Path

from core import io_safe
from connectors import enrich_common

ROOT = Path(__file__).resolve().parents[2]
POSTS_JSON = ROOT / "data" / "channel_posts.json"
OUT = ROOT / "data" / "post_topics.json"
PREAMBLE = "Ты — аналитик Telegram-канала про крипту."


def _load_posts() -> list[dict]:
    return [p for p in io_safe.load_json(POSTS_JSON, []) if p.get("views") is not None]  # без служебных


def main() -> None:
    enrich_common.run(_load_posts(), OUT, PREAMBLE, "--all" in sys.argv)


if __name__ == "__main__":
    main()
