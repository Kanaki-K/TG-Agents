"""Достать картинку первоисточника: og:image страницы → скачать в data/source_media/.

Почему так, а не GPT-обложка (как у флагмана):
  - scope 🔭 — быстрая реакция на новость; уместнее «живое» медиа из самого повода;
  - дёшево и быстро (один GET), без браузера/лимитов ChatGPT-бёрнера;
  - изоляция форматов: не тащим флагман-make_image в путь scope (выстраданный урок).

Безопасность: сеть идёт через feeds.fetch_bytes — там SSRF-защита (приватные адреса + редиректы).
Гарды скачивания: только image/*, минимальный и максимальный размер. Любой сбой → None (уйдём текстом).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urljoin

from connectors.web_sources import feeds
from core import config

OUT_DIR = config.ROOT / "data" / "source_media"  # вне git (data/)

# og:image / twitter:image в любом порядке атрибутов (content до/после property/name).
_META_A = re.compile(
    r"""<meta[^>]+?(?:property|name)\s*=\s*["'](?:og:image(?::url)?|twitter:image(?::src)?)["'][^>]*?"""
    r"""\bcontent\s*=\s*["']([^"']+)["']""", re.I)
_META_B = re.compile(
    r"""<meta[^>]+?\bcontent\s*=\s*["']([^"']+)["'][^>]*?"""
    r"""(?:property|name)\s*=\s*["'](?:og:image(?::url)?|twitter:image(?::src)?)["']""", re.I)

_CTYPE_EXT = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
    "image/webp": ".webp", "image/gif": ".gif",
}
_MIN_BYTES = 2_048       # меньше — почти наверняка заглушка/битьё, не обложка
_MAX_IMG_BYTES = 9_000_000  # Telegram-фото до ~10МБ; больше не тянем


def og_image_url(page_url: str) -> str | None:
    """URL главной картинки страницы (og:image/twitter:image), абсолютный. None — нет/недоступна."""
    got = feeds.fetch_bytes(page_url)
    if not got:
        return None
    html = got[0].decode("utf-8", errors="replace")
    for rx in (_META_A, _META_B):
        m = rx.search(html)
        if m:
            return urljoin(page_url, m.group(1).strip())
    return None


_MAX_SIDE = 1600  # ресайз до этой макс.стороны: Telegram отклоняет большие фото (PhotoInvalidDimensionsError)
_MIN_SIDE = 800   # МЕНЬШЕ по длинной стороне — мелкий thumbnail/битый кроп, не обложка (баг 24.07: 8.5КБ og:image
                  # ушла в канал «обрезанной и корявой» — vision судит смысл, не пиксели; ловим детерминированно)


def _normalize(path: Path) -> Path | None:
    """Привести к Telegram-safe ФОТО: RGB, макс сторона 1600px, JPEG q85. Так Telegram не отклоняет 'photo'
    по размерам (частая ошибка на больших PNG) + меньше вес (дешевле vision). Pillow нет → отдаём как есть
    (publish подстрахует документом). Заодно уменьшенная картинка удешевляет vision-вызов.
    None — картинка МЕЛКАЯ (длинная сторона < _MIN_SIDE): отклоняем кандидата, пусть сработает фолбаг
    «уйдём текстом» (обложка-мусор хуже отсутствия обложки — баг 24.07)."""
    try:
        from PIL import Image
    except Exception:
        logging.info("source_media: Pillow не установлен — картинку не нормализую (pip install pillow)")
        return path
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            small = max(w, h) < _MIN_SIDE   # порог качества по РАЗРЕШЕНИЮ (байты обманывают: JPEG q85 сильно жмёт)
            if not small:
                longest = max(w, h)
                if longest > _MAX_SIDE:
                    s = _MAX_SIDE / longest
                    im = im.resize((max(1, round(w * s)), max(1, round(h * s))))
                out = path.with_suffix(".jpg")
                im.save(out, "JPEG", quality=85, optimize=True)
        if small:
            logging.info("source_media: обложка %dx%d < %dpx по длинной стороне — отклоняю (мелкая/битая, "
                         "уйдём текстом)", w, h, _MIN_SIDE)
            try:
                path.unlink()
            except Exception:
                pass
            return None
        if out != path:
            try:
                path.unlink()
            except Exception:
                pass
        return out
    except Exception:
        logging.exception("source_media: нормализация не удалась — отдаю оригинал")
        return path


def download(img_url: str, name: str = "scope") -> Path | None:
    """Скачать картинку в data/source_media/<name>.jpg (нормализованную под Telegram-фото). None — не
    картинка/битая/размер вне гейта."""
    got = feeds.fetch_bytes(img_url, max_bytes=_MAX_IMG_BYTES)
    if not got:
        return None
    body, ctype = got
    ext = _CTYPE_EXT.get(ctype.split(";")[0].strip().lower())
    if not ext or not (_MIN_BYTES <= len(body) <= _MAX_IMG_BYTES):
        return None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / f"{name}{ext}"
    dest.write_bytes(body)
    return _normalize(dest)  # ресайз/JPEG → валидное Telegram-фото (Pillow нет → как есть)


def fetch_source_image(page_url: str, name: str = "scope") -> Path | None:
    """Полный путь: страница повода → её og:image → скачать. None, если картинки нет/не годна."""
    iu = og_image_url(page_url)
    if not iu:
        return None
    return download(iu, name)
