"""Категория темы флагмана = её МАКРО-СЛОЙ в банке (memory/flagship_topics.md).

Зачем категория, а не отдельная тема: перформанс-сигнал «какой РАЗРЯД тем заходит» копится
по ~6 бакетам, а не по 200 темам — статистика набирается в разы быстрее и не застревает в
2-3 темах. Тег НЕ проставляется у темы руками: категория выводится из заголовка «## Слой N.M …»,
под которым тема стоит. Опубликованный флагман хранит в журнале ТОЧНУЮ строку банка
(run_pipeline._pick_timely_theme → flagship_journal.record), поэтому join
«тема → строка банка → слой → категория» точный.

Группировка 17 подслоёв → 6 категорий (CATEGORIES) — ЕДИНСТВЕННАЯ ручка настройки; правь её,
не трогая парсер. Слой N.* → категория N. Тема не из банка → UNKNOWN (скоринг её пропускает,
а не приписывает случайной категории — честнее промолчать).
"""
from __future__ import annotations

import logging
import re

from core import config

BANK_FILE = config.ROOT / "memory" / "flagship_topics.md"

# Макро-слой N → (slug, имя). Ручка настройки категорий (парсер не трогается).
CATEGORIES = {
    "1": ("применение", "Применение и принятие (индустрия, риски)"),
    "2": ("психология", "Психология инвестора"),
    "3": ("рынок", "Рынок, on-chain, математика, макро"),
    "4": ("философия", "Философия и построение капитала"),
    "5": ("антиказино", "Антиказино и безопасность"),
    "6": ("словарь", "Разборы концепций и словарь"),
}
# Подслой N.M, вынесенный в СВОЮ категорию (перекрывает макро-слой). AI×крипта — «уникальное
# ядро» (держать ≥30%): хотим видеть отдельно, стреляет ли он, а не топить в «применении».
SUBLAYER_OVERRIDES = {
    "1.2": ("ai-крипта", "AI × крипта (уникальное ядро)"),
}
UNKNOWN = "unknown"

_HEADER_RE = re.compile(r"^##\s*Слой\s*(\d)(?:\.(\d+))?")  # «## Слой 1.2 — …» → (макро, подслой|None)
_USED_RE = re.compile(r"^\[вышло[^\]]*\]\s*(.*)$")   # «[вышло 2026-07-07] текст» → текст (как в core/dedup)


def _norm(theme: str) -> str:
    """Ключ сравнения: без «- », без маркера [вышло], нижний регистр, схлопнутые пробелы.
    Совпадает с тем, как dedup._bank_lines чистит строку → journal-тема матчится с банком."""
    t = (theme or "").strip()
    if t.startswith("- "):
        t = t[2:].strip()
    m = _USED_RE.match(t)
    if m:
        t = m.group(1).strip()
    return re.sub(r"\s+", " ", t).lower()


def _parse_bank(text: str) -> dict[str, str]:
    """{нормализованная_тема → slug категории} из текста банка."""
    out: dict[str, str] = {}
    slug: str | None = None
    for ln in text.splitlines():
        h = _HEADER_RE.match(ln.strip())
        if h:
            macro, minor = h.group(1), h.group(2)
            sub = f"{macro}.{minor}" if minor else ""
            slug = (SUBLAYER_OVERRIDES.get(sub) or CATEGORIES.get(macro, (UNKNOWN, "")))[0]
            continue
        s = ln.strip()
        if slug and s.startswith("- "):
            key = _norm(s)
            if key:
                out[key] = slug
    return out


_cache: dict = {"key": None, "map": {}}


def _bank_map() -> dict[str, str]:
    """Карта тема→категория с кэшем по (путь, mtime): перечитываем банк ТОЛЬКО при его правке.
    Раньше парсили на КАЖДУЮ тему пула (~200×/прогон пикера — регресс N-15). Кэш по mtime, а не
    навсегда: правка банка подхватывается сама (иначе была бы новая тихая деградация — устаревшая карта);
    путь в ключе — чтобы смена BANK_FILE (тесты) не отдала чужую карту.
    Ошибка чтения/парсинга ЛОГИРУЕТСЯ (N-11): иначе битый банк → все UNKNOWN → наклон пикера тихо off."""
    try:
        key = (str(BANK_FILE), BANK_FILE.stat().st_mtime)
    except OSError:
        logging.warning("Банк тем не читается (%s) — категории UNKNOWN, наклон пикера выключится", BANK_FILE)
        return {}
    if _cache["key"] != key:
        try:
            _cache["map"] = _parse_bank(BANK_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logging.warning("Банк тем не распарсился (%s) — категории UNKNOWN", BANK_FILE, exc_info=True)
            _cache["map"] = {}
        _cache["key"] = key
    return _cache["map"]


def category_of(theme: str) -> str:
    """Категория темы (slug) по банку. Не найдена → UNKNOWN."""
    if not theme:
        return UNKNOWN
    return _bank_map().get(_norm(theme), UNKNOWN)


def label(slug: str) -> str:
    """Человекочитаемое имя категории по slug (или сам slug, если неизвестен)."""
    for s, name in list(CATEGORIES.values()) + list(SUBLAYER_OVERRIDES.values()):
        if s == slug:
            return name
    return slug


def all_slugs() -> list[str]:
    """Все slug'и категорий — для инициализации рейтинга (все с нуля)."""
    return [s for s, _ in CATEGORIES.values()] + [s for s, _ in SUBLAYER_OVERRIDES.values()]
