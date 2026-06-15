"""Чтение RSS/Atom-фидов Тир-2 (по трекам crypto/ai) — «руки» Скаута для разведки тезисов.

Список фидов — в sources.yaml рядом (сгруппирован по трекам). Каждый фид читается
изолированно: сломанный/недоступный не роняет остальные.
"""
from __future__ import annotations

import re
import urllib.request
from pathlib import Path

import feedparser
import yaml

HERE = Path(__file__).resolve().parent
SOURCES_FILE = HERE / "sources.yaml"
TRACKS = ("crypto", "ai")

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(html_text: str, limit: int = 500) -> str:
    """Снять HTML-теги и схлопнуть пробелы; обрезать длинную аннотацию."""
    text = _TAG_RE.sub(" ", html_text or "")
    text = _WS_RE.sub(" ", text).strip()
    return text[:limit]


def fetch_page(url: str, limit: int = 4000) -> str:
    """Скачать страницу по ссылке и вернуть очищенный текст.

    «Рука» для Скаута: прочитать источник и вытащить ТОЧНЫЕ цифры/цитаты, а не только
    сниппет из поиска. Клиентская загрузка (urllib) — без серверных контейнеров.
    """
    if not url.lower().startswith(("http://", "https://")):
        return "Некорректный URL (нужен http/https)."
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (KanakiScout)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read(800_000)  # кап на размер тела
            charset = resp.headers.get_content_charset() or "utf-8"
            html = raw.decode(charset, errors="replace")
    except Exception as e:  # таймаут/403/404/сеть — отдаём как текст, не роняем агента
        return f"Не удалось открыть страницу: {e}"
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)  # вырезать код/стили
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", html)).strip()
    return text[:limit] or "(страница без читаемого текста — возможно, требует JS)"


def load_sources() -> list[dict]:
    """Плоский список фидов с треком: [{name, url, track}, ...]."""
    if not SOURCES_FILE.exists():
        return []
    data = yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8")) or {}
    out: list[dict] = []
    for track in TRACKS:
        for feed in data.get(track, []) or []:
            out.append({**feed, "track": track})
    return out


def fetch_recent(per_source: int = 4, source: str = "", track: str = "") -> list[dict]:
    """Свежие записи из фидов Тир-2.

    track — фильтр по треку ('crypto' | 'ai'), source — по имени источника (подстрока).
    Возвращает items: {name, track, title, link, published, summary} или {name, track, error}.
    """
    items: list[dict] = []
    for feed in load_sources():
        name, url, ftrack = feed.get("name", "?"), feed.get("url", ""), feed.get("track", "")
        if track and track.lower() != ftrack:
            continue
        if source and source.lower() not in name.lower():
            continue
        try:
            parsed = feedparser.parse(url)
        except Exception as e:  # фид недоступен/битый — не роняем остальные
            items.append({"name": name, "track": ftrack, "error": str(e)})
            continue
        if getattr(parsed, "bozo", 0) and not parsed.entries:
            items.append({"name": name, "track": ftrack, "error": "фид не распарсился"})
            continue
        for entry in parsed.entries[:per_source]:
            items.append({
                "name": name,
                "track": ftrack,
                "title": entry.get("title", "(без заголовка)"),
                "link": entry.get("link", ""),
                "published": entry.get("published", entry.get("updated", "")),
                "summary": _clean(entry.get("summary", "")),
            })
    return items
