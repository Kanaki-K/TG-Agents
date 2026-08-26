"""Достать картинку первоисточника: кадры со страницы повода → скачать в data/source_media/.

Кандидаты: og:image (шапка) + картинки из ТЕЛА статьи (график/схема/скрин/фото). Одной шапки
мало — она декоративная по назначению, и пул из одних шапок даёт только ИИ-сток (26.08).

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


def _page_html(page_url: str) -> str:
    got = feeds.fetch_bytes(page_url)
    return got[0].decode("utf-8", errors="replace") if got else ""


def _og_from_html(html: str, page_url: str) -> str | None:
    for rx in (_META_A, _META_B):
        m = rx.search(html)
        if m:
            return urljoin(page_url, m.group(1).strip())
    return None


def og_image_url(page_url: str) -> str | None:
    """URL главной картинки страницы (og:image/twitter:image), абсолютный. None — нет/недоступна."""
    html = _page_html(page_url)
    return _og_from_html(html, page_url) if html else None


# ══ КАДРЫ ИЗ ТЕЛА СТАТЬИ, А НЕ ТОЛЬКО ШАПКА (26.08) ══
# og:image — это картинка-превью для соцсетей, то есть по построению ДЕКОРАТИВНАЯ шапка. У крипто-медиа
# шапка сегодня и есть ИИ-рендер, поэтому пул из одних шапок структурно не может дать ничего, кроме
# ИИ-стока: 26.08 в выборе стояли три генерика (неоновый банк, пиксельный доллар, Франклин в «матрице»),
# и победил самый «в тему» из них. Владелец: «ии-сток не берём, стараемся по теме всё-таки найти».
# Искать надо там, где лежит содержание: график, схема, скрин, фото события — они внутри статьи, а не
# в мета-теге. Это ровно то, что `_MEDIA_CRITERIA` уже ставит выше генерика («график/дашборд/отчёт
# ПЕРВОИСТОЧНИКА») — до сегодня такой кандидат просто не мог попасть в пул.
_IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
_IMG_SRC = re.compile(r"""\b(?:src|data-src|data-original|data-lazy-src)\s*=\s*["']([^"']+)["']""", re.I)
_ARTICLE = re.compile(r"<(article|main)\b[^>]*>(.*?)</\1>", re.I | re.S)
# Мусор по URL: элементы интерфейса и трекеры. Это НЕ бан-лист доменов и не вкусовая фильтрация —
# только служебная графика, которая обложкой не бывает никогда.
_JUNK_URL = re.compile(r"(logo|favicon|icon|avatar|sprite|badge|button|pixel|tracking|spacer|"
                       r"placeholder|1x1|blank|share|subscribe|newsletter)", re.I)
_SKIP_EXT = (".svg", ".gif", ".ico")
ARTICLE_IMG_CAP = 3          # кадров с ОДНОЙ страницы: дальше растёт цена vision, а отдача падает


def article_images(page_url: str, limit: int = ARTICLE_IMG_CAP) -> list[str]:
    """URL(ы) картинок из ТЕЛА статьи — график/схема/скрин/фото, в порядке появления. Без og:image.

    Сначала сужаемся до <article>/<main>, если они есть: это одним движением выкидывает шапку сайта,
    навигацию и подвал вместе с их логотипами. Дальше — только служебный отсев по URL; «годная ли
    картинка по смыслу» решает vision, а «не мелкая ли» — гейт разрешения в _normalize.
    """
    html = _page_html(page_url)
    return _body_images(html, page_url, limit) if html else []


def _body_images(html: str, page_url: str, limit: int = ARTICLE_IMG_CAP) -> list[str]:
    m = _ARTICLE.search(html)
    body = m.group(2) if m else html
    og = _og_from_html(html, page_url)
    out: list[str] = []
    for tag in _IMG_TAG.findall(body):
        src = _IMG_SRC.search(tag)
        if not src:
            continue
        raw = src.group(1).strip()
        if raw.startswith("data:") or _JUNK_URL.search(raw):
            continue
        url = urljoin(page_url, raw)
        if url.split("?")[0].lower().endswith(_SKIP_EXT) or url == og or url in out:
            continue
        out.append(url)
        if len(out) >= max(1, limit):
            break
    return out


_MAX_SIDE = 1600  # ресайз до этой макс.стороны: Telegram отклоняет большие фото (PhotoInvalidDimensionsError)
_MIN_SIDE = 800   # МЕНЬШЕ по длинной стороне — мелкий thumbnail/битый кроп, не обложка (баг 24.07: 8.5КБ og:image
                  # ушла в канал «обрезанной и корявой» — vision судит смысл, не пиксели; ловим детерминированно)
# ══ ПОРОГ ПО РОЛИ КАДРА, А НЕ ОДИН НА ВСЁ (26.08) ══
# 24.07 порог 800 поставили по декоративной шапке — и он верен ДЛЯ ШАПКИ: картинка-украшение в низком
# разрешении это просто битый thumbnail, смотреть в ней нечего. Но кадр из тела статьи — это ИНФОРМАЦИЯ
# (график, схема, скрин), и она остаётся информацией и в меньшем разрешении. 26.08 порог сработал ровно
# наоборот задуманному: выбросил кандидата 345x230 и оставил в пуле три больших красивых ИИ-рендера.
# У регуляторов, ФРБ и научных страниц картинки как раз мелкие — то есть общий порог бил по самому
# ценному классу источников. Ниже 500px подписи на графике не переживают растяжение в ленте Telegram,
# поэтому пол у информационного кадра свой, а не «никакого».
_MIN_SIDE_BODY = 500


def _normalize(path: Path, min_side: int = _MIN_SIDE) -> Path | None:
    """Привести к Telegram-safe ФОТО: RGB, макс сторона 1600px, JPEG q85. Так Telegram не отклоняет 'photo'
    по размерам (частая ошибка на больших PNG) + меньше вес (дешевле vision). Pillow нет → отдаём как есть
    (publish подстрахует документом). Заодно уменьшенная картинка удешевляет vision-вызов.
    None — картинка МЕЛКАЯ (длинная сторона < min_side): отклоняем кандидата, пусть сработает фолбэк
    «уйдём текстом» (обложка-мусор хуже отсутствия обложки — баг 24.07). Порог зависит от РОЛИ кадра:
    шапке нужен _MIN_SIDE, кадру из тела статьи хватает _MIN_SIDE_BODY (см. блок выше)."""
    try:
        from PIL import Image
    except Exception:
        logging.info("source_media: Pillow не установлен — картинку не нормализую (pip install pillow)")
        return path
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            small = max(w, h) < min_side    # порог качества по РАЗРЕШЕНИЮ (байты обманывают: JPEG q85 сильно жмёт)
            if not small:
                longest = max(w, h)
                if longest > _MAX_SIDE:
                    s = _MAX_SIDE / longest
                    im = im.resize((max(1, round(w * s)), max(1, round(h * s))))
                out = path.with_suffix(".jpg")
                im.save(out, "JPEG", quality=85, optimize=True)
        if small:
            logging.info("source_media: кадр %dx%d < %dpx по длинной стороне — отклоняю (мелкий/битый)",
                         w, h, min_side)
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


def download(img_url: str, name: str = "scope", min_side: int = _MIN_SIDE) -> Path | None:
    """Скачать картинку в data/source_media/<name>.jpg (нормализованную под Telegram-фото). None — не
    картинка/битая/размер вне гейта. min_side — пол разрешения по РОЛИ кадра (шапка/тело статьи)."""
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
    return _normalize(dest, min_side)  # ресайз/JPEG → валидное Telegram-фото (Pillow нет → как есть)


def fetch_source_image(page_url: str, name: str = "scope") -> Path | None:
    """Полный путь: страница повода → её og:image → скачать. None, если картинки нет/не годна."""
    iu = og_image_url(page_url)
    if not iu:
        return None
    return download(iu, name)


def fetch_source_images(page_url: str, name: str = "scope", limit: int = 1 + ARTICLE_IMG_CAP) -> list[Path]:
    """Все кандидаты со страницы: шапка (og:image) + кадры из ТЕЛА статьи. Пустой список — ничего годного.

    Порядок сохраняем «шапка первой»: она чаще целая и нужного размера, а кадры из тела — это шанс на
    конкретику (график/схема/скрин), которой в шапке не бывает. Кто из них лучше по СМЫСЛУ, решает
    vision в scope_writer; наше дело — принести выбор, а не единственный вариант.
    """
    html = _page_html(page_url)          # страницу тянем ОДИН раз: и шапка, и тело — из этого же HTML
    if not html:
        return []
    urls: list[tuple[str, int]] = []          # (url, пол разрешения по роли кадра)
    og = _og_from_html(html, page_url)
    if og:
        urls.append((og, _MIN_SIDE))
    urls += [(u, _MIN_SIDE_BODY) for u in _body_images(html, page_url) if u != og]
    out: list[Path] = []
    for j, (u, floor) in enumerate(urls[:max(1, limit)]):
        p = download(u, name=f"{name}_{j}", min_side=floor)
        if p:
            out.append(p)
    return out
