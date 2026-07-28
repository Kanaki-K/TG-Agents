"""Обогащение постов Threads: заголовок/тема/КАТЕГОРИЯ/угол/суть (через Claude).

Каркас общий с Telegram — connectors.enrich_common (чтобы не дрейфовать, N-49). Здесь только
специфика площадки: свои посты (data/threads_posts.json), преамбула, out-файл.

    python -m connectors.threads.enrich_topics          # только новые
    python -m connectors.threads.enrich_topics --all    # пересчитать всё
"""
from __future__ import annotations

import sys
from pathlib import Path

from core import io_safe
from connectors import enrich_common

ROOT = Path(__file__).resolve().parents[2]
POSTS_JSON = ROOT / "data" / "threads_posts.json"
OUT = ROOT / "data" / "threads_topics.json"
PREAMBLE = "Ты — аналитик Threads-аккаунта про крипту."


def _load_posts() -> list[dict]:
    return io_safe.load_json(POSTS_JSON, [])   # нет файла → [] + INFO-лог (io_safe); enrich_common скажет «0 постов»


def main() -> None:
    enrich_common.run(_load_posts(), OUT, PREAMBLE, "--all" in sys.argv)


if __name__ == "__main__":
    main()
