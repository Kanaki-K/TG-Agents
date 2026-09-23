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
from urllib.parse import urljoin, urlparse

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


def page_html(page_url: str) -> str:
    """HTML страницы повода — нужен и subject_media, чтобы вытащить оттуда ссылку на официальный
    сайт объекта.

    Кэша тут НЕТ намеренно. Я его завёл (одну страницу спрашивают и кадры статьи, и поиск сайта —
    выходит два одинаковых GET) и сразу же убрал: кэш без срока жизни в долгоживущем процессе бота
    отдаёт вчерашнюю страницу как сегодняшнюю, а это ровно тот класс ошибок, из-за которого пост
    31.08 вышел с июльской цифрой. Лишний GET дешевле стухших данных."""
    return _page_html(page_url)


def _og_from_html(html: str, page_url: str) -> str | None:
    for rx in (_META_A, _META_B):
        m = rx.search(html)
        if m:
            return urljoin(page_url, m.group(1).strip())
    return None


# ── МУСОР ПО ИМЕНИ ФАЙЛА (стоп-лист владельца 07.09) ────────────────────────────────────────────
# Wikimedia честно отдаёт всё, что подписано именем объекта: у Binance это оказалась ФУТБОЛКА и
# сумка с логотипом, у Bitcoin — СКРИНШОТ окна Bitcoin Core Wallet. Оба уехали в демо-прогон 07.09
# как обложки. Судья их отсекает не всегда (формально «объект повода на кадре»), а стоит это
# vision-токенов на каждом прогоне — дешевле не тащить вовсе.
_JUNK_NAME = re.compile(
    r"(t[-_ ]?shirt|tshirt|hoodie|sweatshirt|mug|cup|sticker|merch|tote|cap[-_ ]|badge|lanyard"
    r"|screenshot|screen[-_ ]?shot|wallet[-_ ]?screen|receipt|invoice|statement"
    r"|qr[-_ ]?code|favicon|placeholder|avatar|thumb(nail)?[-_ ]?\d*\.)", re.I)


def looks_like_junk(url: str) -> bool:
    """Мерч, скриншот интерфейса, квитанция, аватарка — по имени файла. Стоп-лист мануала §5."""
    try:
        return bool(_JUNK_NAME.search(urlparse(url).path))
    except Exception:
        return False


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
# То же, но БЕЗ `logo`/`icon` — для случая, когда мы уже сузились до <article>/<main> и шапку сайта
# с её логотипом отрезали структурно (см. _body_images). Лого КОМПАНИИ/СЕТИ внутри статьи — законный
# кандидат в обложку 🔭; годен он или нет, решает vision, а не совпадение подстроки в адресе.
_JUNK_URL_BODY = re.compile(r"(favicon|avatar|sprite|badge|button|pixel|tracking|spacer|"
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
    # ЛОГОТИП ТЕМЫ — ЗАКОННАЯ ОБЛОЖКА, А НЕ МУСОР (владелец 28.08). На канале лого компании/сети —
    # один из самых частых кадров под 🔭: «логотип вот компании или просто логотип на фоне». А фильтр
    # `_JUNK_URL` выбрасывал ЛЮБОЙ адрес со словом logo/icon — то есть ровно этот кадр, ещё до vision.
    # Отсюда и расхождение: в критериях отбора написано «лого первоисточника — БЕРЁМ», а до выбора оно
    # не доезжало никогда. 28.08 владелец поставил обложкой лого Solana РУКАМИ — пул его не предлагал.
    #
    # Почему послабление безопасное: `logo`/`icon` в списке стоят против ШАПКИ САЙТА и фавиконки, а от
    # них нас уже спас `<article>`/`<main>` — сужение выкидывает навигацию с подвалом целиком. Значит
    # послабление даём ТОЛЬКО когда сужение реально случилось; не нашли статью (body = вся страница) —
    # фильтр остаётся строгим, иначе в пул хлынут логотипы самого издания.
    junk = _JUNK_URL_BODY if m else _JUNK_URL
    og = _og_from_html(html, page_url)
    out: list[str] = []
    for tag in _IMG_TAG.findall(body):
        src = _IMG_SRC.search(tag)
        if not src:
            continue
        raw = src.group(1).strip()
        if raw.startswith("data:") or junk.search(raw):
            continue
        url = urljoin(page_url, raw)
        if url.split("?")[0].lower().endswith(_SKIP_EXT) or url == og or url in out:
            continue
        out.append(url)
        if len(out) >= max(1, limit):
            break
    return out


# ══ ФОРМАТ ОБЛОЖКИ — ЗАМЕР 23 ОПУБЛИКОВАННЫХ 🔭 (31.08) ══
# Владелец: «на канале четко есть 20+ примеров утверждённого визуала — понять формат и чтобы впредь
# было так же». Померили все обложки июнь–август 2026 (data/published_covers):
#   • горизонталь 21 из 23 (квадрат 1, вертикаль 1);
#   • пропорция: медиана 1.78 (те самые 16:9), 20 из 23 укладываются в 1.5–2.0;
#   • длинная сторона: медиана 1024, максимум 1600; формат файла — JPEG.
# Раньше код пропорцию не приводил вообще: он только ужимал до 1600 и отбраковывал мелочь. Поэтому
# квадратное лого уходило квадратом, а вордмарк-полоска 831x163 — полоской, и лента канала выглядела
# рвано. Теперь кадр вне диапазона 1.5–2.0 достраивается до 16:9 полем ФОНОВОГО цвета самого кадра
# (не чёрным): у лого на белом это даёт ровно «логотип на фирменном фоне» — тип 1, самый частый на
# канале. Кадр, который уже в диапазоне, НЕ трогаем — своя композиция фотографии дороже ровной цифры.
# ГРАНИЦЫ = ГРАНИЦЫ ОТБОРА (23.09.2026). Было 1.5–2.0, а отбор (LANDSCAPE_MIN/MAX ниже) пускал 1.45–2.4.
# Кадр между ними признавался «горизонталью» и тут же обрастал полями: 23.09 фото 1345x900 (1.49) ушло
# в канал с серыми полосами по бокам — владелец: «выбрало изображение обрезанное». Тот же класс, что
# 14.09 («обрезано сверху снизу»). Годную для канала горизонталь не достраиваем вообще — поля только
# у того, что отбор всё равно ставит в конец очереди (квадрат, вертикаль, полоска). Принятые владельцем
# обложки лежат в 1.4988–2.333 — все внутри.
_RATIO_MIN, _RATIO_MAX = 1.45, 2.4
_RATIO_TARGET = 16 / 9              # медиана канала 1.78 — к ней и достраиваем
_MAX_SIDE = 1600  # ресайз до этой макс.стороны: Telegram отклоняет большие фото (PhotoInvalidDimensionsError)
# ПОЛ РАЗРЕШЕНИЯ ВЗЯТ ИЗ ПРИНЯТЫХ ОБЛОЖЕК, А НЕ ИЗ ГОЛОВЫ (07.09). Порог 800 стоял с 24.07 по одному
# багу (8.5КБ og:image ушла «обрезанной и корявой»). Замер 23 опубликованных обложек показал, что он
# бьёт по своим: #440 (Chainlink/Pangea) вышел в канал в 499x281, #454 (ORANGE JUICE) — 700x300,
# #489 (печать ФРС) — 700x450. То есть порог 800 выбросил бы три ПРИНЯТЫЕ владельцем обложки, включая
# самый частый класс кадра — фирменное полотно бренда. Новый пол — чуть ниже самой мелкой принятой.
_MIN_SIDE = 460
# ══ ПОРОГ ПО РОЛИ КАДРА, А НЕ ОДИН НА ВСЁ (26.08) ══
# 24.07 порог 800 поставили по декоративной шапке — и он верен ДЛЯ ШАПКИ: картинка-украшение в низком
# разрешении это просто битый thumbnail, смотреть в ней нечего. Но кадр из тела статьи — это ИНФОРМАЦИЯ
# (график, схема, скрин), и она остаётся информацией и в меньшем разрешении. 26.08 порог сработал ровно
# наоборот задуманному: выбросил кандидата 345x230 и оставил в пуле три больших красивых ИИ-рендера.
# У регуляторов, ФРБ и научных страниц картинки как раз мелкие — то есть общий порог бил по самому
# ценному классу источников. Ниже 500px подписи на графике не переживают растяжение в ленте Telegram,
# поэтому пол у информационного кадра свой, а не «никакого».
# Роль кадра больше не меняет порог: пол теперь выведен из опубликованных обложек и одинаково верен
# и для шапки, и для кадра из тела статьи. Имя оставлено — на него ссылаются места вызова.
_MIN_SIDE_BODY = _MIN_SIDE


def _bg_color(im) -> tuple:
    """Фоновый цвет кадра = самый частый цвет по его РАМКЕ (полоски по краям).

    Нужен для двух вещей сразу: подложить под прозрачность (иначе RGB-конверт красит её в ЧЁРНЫЙ и
    тёмное лого исчезает) и залить поля при достройке до 16:9. Берём именно рамку, потому что у лого
    и пресс-полотен края — это и есть фирменный фон, и достроенный кадр выглядит цельным, а не
    «картинкой в чёрной коробке»."""
    try:
        w, h = im.size
        rgba = im.convert("RGBA")
        px = rgba.load()
        step = max(1, min(w, h) // 40)
        counts: dict = {}
        clear = 0
        border = []
        for x in range(0, w, step):
            border += [(x, 0), (x, h - 1)]
        for y in range(0, h, step):
            border += [(0, y), (w - 1, y)]
        for x, y in border:
            r, g, b, a = px[x, y]
            if a < 32:                    # прозрачный край — цвета у него нет, считаем отдельно
                clear += 1
            else:
                counts[(r, g, b)] = counts.get((r, g, b), 0) + 1
        # ПРОЗРАЧНАЯ РАМКА → ФОН ПО КОНТРАСТУ С САМИМ ЛОГО, А НЕ ПО ЦВЕТУ КРАЯ (31.08). На Commons почти
        # все лого лежат с прозрачным фоном, и «самый частый цвет края» у них — чёрный ноль из-под альфы.
        # Для розового Uniswap это случайно красиво, а тёмное лого так становится чёрным по чёрному и
        # обложка мертва. Поэтому: смотрим, светлые чернила у лого или тёмные, и подкладываем обратное.
        if clear > len(border) // 2 or not counts:
            ink = [px[x, y] for x in range(0, w, step) for y in range(0, h, step) if px[x, y][3] > 128]
            if not ink:
                return (255, 255, 255)
            lum = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b, _ in ink) / len(ink)
            return (17, 17, 17) if lum > 140 else (255, 255, 255)
        return max(counts, key=counts.get)
    except Exception:
        return (255, 255, 255)


# ИСХОДНАЯ пропорция кадра, по пути готового файла. Нужна ОТБОРУ, а не нормализации: после
# _to_channel_format всё лежит в 16:9, и вертикальный портрет с синими полями по бокам внешне не
# отличим от снятой горизонтали. Владелец 07.09: «нам нужно горизонтальное фото, как было раньше —
# если я прошу провести анализ того, что было, то и формат должен быть такой же». Замер: горизонталь
# 21 из 23. Живёт в памяти процесса — отбор идёт в том же прогоне, что и скачивание.
_ORIG_RATIO: dict[str, float] = {}
# Длинная сторона ИСХОДНИКА — для предпочтения качества. Пол (_MIN_SIDE) отсекает битое, а это
# ранжирование: владелец 07.09 — «качество картинок должно быть выше среднего, высокое». Медиана
# длинной стороны у 23 принятых обложек — 1024, максимум 1600.
_LONG_SIDE: dict[str, int] = {}
QUALITY_SIDE = 1000     # «высокое» = не ниже медианы канала
# Порог горизонтали = минимальная пропорция среди 23 ПРИНЯТЫХ обложек (1.4988 у #451, сенаторы).
# Ниже — кадр поедет в поля, а поля владелец запретил прямо: «вертикальные фото в горизонтальном
# формате» стоят первым пунктом стоп-листа. 4:3 (1.33) сюда не проходит намеренно: достройка до 16:9
# съела бы треть ширины полями, и в ленте это читается как чужой формат.
LANDSCAPE_MIN = _RATIO_MIN
# ПАНОРАМА — ТОЖЕ НЕ ФОРМАТ КАНАЛА (14.09). Нижняя граница была, верхней не было: вагон электрички
# с пропорцией ~3.4 прошёл как «горизонталь», был достроен до 16:9 серыми полями сверху и снизу и
# уехал в отложку. Владелец: «так ещё и обрезано сверху снизу». Граница = самая широкая из 23 ПРИНЯТЫХ
# обложек (2.333 у #454, баннер ORANGE JUICE) с небольшим запасом.
LANDSCAPE_MAX = _RATIO_MAX


def long_side(path) -> int:
    """Длинная сторона ИСХОДНОГО кадра. 0 — не мерился (нет Pillow)."""
    return _LONG_SIDE.get(str(path), 0)


def is_sharp(path) -> bool:
    """Кадр «высокого» качества по меркам канала. Неизмеренный считаем годным (см. is_landscape)."""
    v = long_side(path)
    return v >= QUALITY_SIDE or v == 0


def orig_ratio(path) -> float:
    """Пропорция кадра ДО достройки до 16:9. 0.0 — файл не наш/не мерился."""
    return _ORIG_RATIO.get(str(path), 0.0)


def is_landscape(path) -> bool:
    """Кадр был снят горизонтальным в формате канала (а не достроен полями из вертикали, квадрата
    или слишком широкой панорамы).

    НЕИЗМЕРЕННЫЙ КАДР СЧИТАЕТСЯ ГОДНЫМ. Пропорция пишется в _normalize, а он молча пропускает всё,
    если не установлен Pillow. Строгая трактовка «не измерено — значит не горизонталь» в такой
    сборке выбросила бы ВЕСЬ пул и оставила канал без обложек вообще — то есть страховка от полей
    убила бы саму обложку. Без Pillow полей и не бывает: достраивает их тот же код, что и меряет."""
    r = orig_ratio(path)
    return LANDSCAPE_MIN <= r <= LANDSCAPE_MAX or r == 0.0


# ── РОЛЬ КАДРА НА СТРАНИЦЕ: ШАПКА ИЛИ КАРТИНКА ИЗ ТЕЛА (07.09) ──────────────────────────────────
# Владелец, сравнив data/source_media с data/published_covers: «соурс медиа папка — низкокачественное
# дерьмо, публишед коверс — отличный формат. Он продолжает делать дерьмо, когда есть отличный формат».
# Разница ровно здесь. Все 23 принятые обложки — это ШАПКА материала: og:image статьи, пресс-фото,
# полотно с официального сайта. Ни одна не пришла из ТЕЛА статьи. А кадры из тела мы начали собирать
# 26.08 (a3e2cce), чтобы пул не состоял из одних ИИ-шапок, — и вместе с полезным втянули то, что в
# теле и живёт: аватарки колумнистов Cointelegraph, инлайн-инфографику с цифрами, превью соседних
# новостей. Роль кадра нужна отбору: тело идёт только тогда, когда шапок не набралось.
_ROLE: dict[str, str] = {}


def is_header(path) -> bool:
    """Кадр — ШАПКА материала (og:image), а не картинка из тела статьи."""
    return _ROLE.get(str(path), "шапка") == "шапка"


def _to_channel_format(im):
    """Привести кадр к формату обложек канала: горизонталь с пропорцией 1.45-2.4 (см. замер выше).

    Внутри диапазона — не трогаем. Вне (квадратное лого, вордмарк-полоска, вертикальный портрет) —
    достраиваем до 16:9 полем фонового цвета кадра, кадр по центру. Именно достраиваем, а НЕ
    обрезаем: обрезка у лого срезала бы половину вордмарка, а у портрета — лицо."""
    from PIL import Image
    w, h = im.size
    if h and _RATIO_MIN <= w / h <= _RATIO_MAX:
        return im
    bg = _bg_color(im)
    if w / max(1, h) < _RATIO_TARGET:          # уже/квадратнее целевой — добираем ШИРИНУ
        cw, ch = max(w, round(h * _RATIO_TARGET)), h
    else:                                      # шире целевой (полоска) — добираем ВЫСОТУ
        cw, ch = w, max(h, round(w / _RATIO_TARGET))
    canvas = Image.new("RGB", (cw, ch), bg)
    canvas.paste(im, ((cw - w) // 2, (ch - h) // 2))
    return canvas


def _normalize(path: Path, min_side: int = _MIN_SIDE) -> Path | None:
    """Привести к Telegram-safe ФОТО В ФОРМАТЕ КАНАЛА: RGB (прозрачность — на фон кадра, не в чёрный),
    пропорция 1.5-2.0 как у 23 опубликованных обложек, макс сторона 1600px, JPEG q88. Так Telegram не
    отклоняет 'photo' по размерам (частая ошибка на больших PNG), лента канала выглядит единообразно,
    и вес меньше (дешевле vision). Pillow нет → отдаём как есть (publish подстрахует документом).
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
            w, h = im.size
            small = max(w, h) < min_side    # порог качества по РАЗРЕШЕНИЮ (байты обманывают: JPEG q85 сильно жмёт)
            if not small:
                # ПРОЗРАЧНОСТЬ — НА ФОН КАДРА, А НЕ В ЧЁРНЫЙ. Голый convert('RGB') красил альфу чёрным,
                # и тёмное лого с Commons (а там почти все лого прозрачные) уезжало чёрным по чёрному.
                if im.mode in ("RGBA", "LA", "P"):
                    rgba = im.convert("RGBA")
                    plate = Image.new("RGB", rgba.size, _bg_color(rgba))
                    plate.paste(rgba, mask=rgba.split()[-1])
                    im = plate
                else:
                    im = im.convert("RGB")
                _ORIG_RATIO[str(path.with_suffix(".jpg"))] = w / h if h else 0.0
                _LONG_SIDE[str(path.with_suffix(".jpg"))] = max(w, h)
                im = _to_channel_format(im)
                w, h = im.size
                longest = max(w, h)
                if longest > _MAX_SIDE:
                    s = _MAX_SIDE / longest
                    im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
                out = path.with_suffix(".jpg")
                im.save(out, "JPEG", quality=88, optimize=True)
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


_FP_DEADBAND = 2   # разница яркости, ниже которой соседей считаем равными (устойчивость к ресайзу)


def frame_fingerprint(path: Path) -> int | None:
    """Отпечаток КАРТИНКИ (не файла) — чтобы одинаковый кадр в двух размерах не занимал два места.

    Зачем: 31.08 в пуле из «трёх кандидатов» два были ОДНОЙ И ТОЙ ЖЕ картинкой с crypto.news —
    шапка страницы и она же из тела статьи, отданные в разной ширине. Хеш файла их не сроднит
    (байты разные), поэтому берём dHash: серый 9x9, бит на каждую пару соседних пикселей.

    СРАВНИВАЕМ И ПО ГОРИЗОНТАЛИ, И ПО ВЕРТИКАЛИ (128 бит). Классический горизонтальный dHash на
    наших кадрах врёт: у сплошной заливки и у вертикального градиента ВСЕ горизонтальные пары равны,
    отпечаток у обоих нулевой — то есть фирменное полотно одного бренда «совпало» бы с полотном
    другого. Вертикальная половина такие кадры разводит.

    None — отпечатка нет (Pillow нет, картинка битая, либо кадр вырожденно ровный: у заливки
    сравнивать нечего). Тогда просто НЕ дедуплицируем: потерять кандидата хуже, чем оставить дубль.
    """
    try:
        from PIL import Image
        with Image.open(path) as im:
            small = im.convert("L").resize((9, 9), Image.LANCZOS)
            px = small.load()
            # ЗАЗОР В СРАВНЕНИИ (_FP_DEADBAND). Строгое «больше» на почти равных соседях —
            # монета орлом: у ровной заливки и градиента пары равны, и любое округление ресайза
            # переворачивает бит. Из-за этого один и тот же кадр в 1600px и 800px давал РАЗНЫЕ
            # отпечатки. С зазором ровные участки стабильно дают ноль, а реальный перепад — единицу.
            bits = 0
            for y in range(8):
                for x in range(8):
                    bits = (bits << 1) | (px[x, y] > px[x + 1, y] + _FP_DEADBAND)   # по горизонтали
            for x in range(8):
                for y in range(8):
                    bits = (bits << 1) | (px[x, y] > px[x, y + 1] + _FP_DEADBAND)   # по вертикали
            ones = bin(bits).count("1")
            if ones == 0 or ones == 128:
                return None          # ровная заливка: отпечаток ничего не различает, дедуп выключаем
            return bits
    except Exception:
        return None


def looks_same(a: int | None, b: int | None, tolerance: int = 8) -> bool:
    """Два отпечатка — это один и тот же кадр? Допуск в битах из 128: пережатие и ресайз дают
    расхождение в единицы. None (нет отпечатка) — не сравниваем: лучше лишний кандидат, чем потеря."""
    if a is None or b is None:
        return False
    return bin(a ^ b).count("1") <= tolerance


def download(img_url: str, name: str = "scope", min_side: int = _MIN_SIDE) -> Path | None:
    """Скачать картинку в data/source_media/<name>.jpg (нормализованную под Telegram-фото). None — не
    картинка/битая/размер вне гейта. min_side — пол разрешения по РОЛИ кадра (шапка/тело статьи)."""
    if looks_like_junk(img_url):
        logging.info("source_media: %s — мерч/скриншот/квитанция по имени файла, не тяну (стоп-лист §5)",
                     img_url.split("/")[-1][:60])
        return None
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


# ══ ТИР-1 ЗАКРЫТ ДЛЯ СТРАНИЦ, НО ОТКРЫТ ДЛЯ RSS (07.09) ══
# coindesk отдаёт 429, theblock — 403, и это не заголовки: у них защита от ботов на самой странице.
# Замер 31.08 списал их в потери, и с тех пор пул кормили издания послабее — а лучшая художка в 23
# принятых обложках была как раз оттуда. Но лента у обоих открыта БЕЗ ограничений, и в ней лежит
# ровно тот кадр, что стоит в шапке статьи: 1732x974 у coindesk, 1200x675 у theblock (в живой
# проверке 07.09 вторым элементом ленты theblock лежало пресс-фото DBS — ровно того класса, что
# владелец ставит руками). Значит страница нам и не нужна: заблокирована — идём в ленту.
# Лента отдаёт 20-25 свежих материалов, а скоуп пишет о поводе возрастом 1-3 дня — попадание есть.
_FEED_BY_HOST = {
    "coindesk.com": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "theblock.co": "https://www.theblock.co/rss.xml",
    "cointelegraph.com": "https://cointelegraph.com/rss",
    "decrypt.co": "https://decrypt.co/feed",
    "cryptoslate.com": "https://cryptoslate.com/feed/",
    "coingape.com": "https://coingape.com/feed/",
    "crypto.news": "https://crypto.news/feed/",
    "thedefiant.io": "https://thedefiant.io/api/feed",
    "blockworks.co": "https://blockworks.co/feed",
}
_ITEM_SPLIT = re.compile(r"<item\b", re.I)
_LINK_RE = re.compile(r"<link[^>]*>\s*(?:<!\[CDATA\[)?([^<\]]+)", re.I)
_FEED_IMG_RE = re.compile(
    r"""<(?:media:content|media:thumbnail|enclosure)[^>]*?\burl\s*=\s*["']([^"']+)["']""", re.I)


def _url_key(url: str) -> str:
    """Ключ сравнения ссылок: хост+путь без query, слэшей и www — ленты и статьи их пишут по-разному."""
    try:
        u = urlparse(url)
        return (u.netloc.lower().removeprefix("www.") + u.path.rstrip("/")).lower()
    except Exception:
        return (url or "").lower()


def feed_image_url(page_url: str) -> str | None:
    """Кадр статьи из RSS её издания. Нужен, когда сама страница закрыта (429/403).

    Ищем в ленте элемент с той же ссылкой и берём его media:content/enclosure. Не нашли элемент —
    None: чужую картинку из соседней новости подставлять нельзя, это хуже отсутствия обложки."""
    host = _url_key(page_url).split("/")[0]
    feed = next((f for h, f in _FEED_BY_HOST.items() if host == h or host.endswith("." + h)), None)
    if not feed:
        return None
    got = feeds.fetch_bytes(feed, max_bytes=800_000)
    if not got:
        logging.info("source_media: лента %s не ответила (%s)", feed, feeds.last_error(feed) or "?")
        return None
    xml = got[0].decode("utf-8", errors="replace")
    want = _url_key(page_url)
    for chunk in _ITEM_SPLIT.split(xml)[1:]:
        m = _LINK_RE.search(chunk)
        if not m or _url_key(m.group(1).strip()) != want:
            continue
        img = _FEED_IMG_RE.search(chunk)
        if img:
            logging.info("source_media: страница закрыта, кадр статьи взят из ленты %s", host)
            return img.group(1)
        return None
    logging.info("source_media: в ленте %s этой статьи нет (лента отдаёт только свежие)", host)
    return None


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
        # СТРАНИЦА ЗАКРЫТА (429/403 у тир-1) — идём за кадром статьи в её же ленту.
        alt = feed_image_url(page_url)
        p = download(alt, name=f"{name}_0", min_side=_MIN_SIDE) if alt else None
        if p:
            _ROLE[str(p)] = "шапка"
            return [p]
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
            _ROLE[str(p)] = "шапка" if (og and u == og) else "тело"
            out.append(p)
    return out
