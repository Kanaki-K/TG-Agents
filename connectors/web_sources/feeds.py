"""Чтение RSS/Atom-фидов Тир-2 — «руки» Скаута для разведки тезисов.

Список фидов — в sources.yaml рядом. Каждый фид читается изолированно:
сломанный/недоступный не роняет остальные.
"""
from __future__ import annotations

import re
from pathlib import Path

import feedparser
import yaml

HERE = Path(__file__).resolve().parent
SOURCES_FILE = HERE / "sources.yaml"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(html_text: str, limit: int = 500) -> str:
    """Снять HTML-теги и схлопнуть пробелы; обрезать длинную аннотацию."""
    text = _TAG_RE.sub(" ", html_text or "")
    text = _WS_RE.sub(" ", text).strip()
    return text[:limit]


def load_sources() -> list[dict]:
    if not SOURCES_FILE.exists():
        return []
    data = yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8")) or {}
    return data.get("feeds", [])


def fetch_recent(per_source: int = 4, source: str = "") -> list[dict]:
    """Свежие записи из фидов Тир-2.

    source — необязательный фильтр по имени источника (подстрока).
    Возвращает items: {name, title, link, published, summary}
    или {name, error} для нечитаемого фида.
    """
    items: list[dict] = []
    for feed in load_sources():
        name, url = feed.get("name", "?"), feed.get("url", "")
        if source and source.lower() not in name.lower():
            continue
        try:
            parsed = feedparser.parse(url)
        except Exception as e:  # фид недоступен/битый — не роняем остальные
            items.append({"name": name, "error": str(e)})
            continue
        if getattr(parsed, "bozo", 0) and not parsed.entries:
            items.append({"name": name, "error": "фид не распарсился"})
            continue
        for entry in parsed.entries[:per_source]:
            items.append({
                "name": name,
                "title": entry.get("title", "(без заголовка)"),
                "link": entry.get("link", ""),
                "published": entry.get("published", entry.get("updated", "")),
                "summary": _clean(entry.get("summary", "")),
            })
    return items
