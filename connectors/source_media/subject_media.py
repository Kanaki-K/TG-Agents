"""ПОИСК кадра по ОБЪЕКТУ повода — недостающее звено обложки 🔭.

Зачем это появилось (31.08). До сегодня обложка добывалась ровно одним способом: взять 3-4 ссылки,
которые писатель перечислил в мете `[[MEDIA_SRC]]`, и снять картинки с этих страниц. То есть код
НИКОГДА НЕ ИСКАЛ кадр — он подбирал то, что случайно оказалось в новостных статьях. Человек на его
месте делает другое: идёт и ищет «логотип Robinhood», «штаб-квартира SEC», «фото Сэйлора».
31.08 это выстрелило наглядно: обе статьи-первоисточника кадров не дали вовсе, в пул попали два
одинаковых ИИ-рендера с crypto.news и стоковое фото рук с монетами — обложки не вышло, хотя
официальное лого Robinhood лежит в открытом доступе.

Что ищем и почему именно это. 31.08 пересмотрены ВСЕ 23 опубликованные обложки. Через них проходит
одно: обложка — это либо СНЯТЫЙ кадр, либо ДИЗАЙНЕРСКОЕ ПОЛОТНО с цветом и фактурой; плоского
вектора на белом нет ни одного. Три верхних типа — 18 кадров из 23 — ищутся по ИМЕНИ объекта:
  • снятый объект компании/института, 7 из 23 (вход BNY, надпись J.P.Morgan, печать SEC)
    → фото из Wikidata (P18), картинка статьи Википедии, поиск фото штаб-квартиры по Commons;
  • фирменное полотно бренда, 7 из 23 (Bitmine на чёрном, Stripe с градиентом) → og:image
    официального сайта объекта (P856);
  • человек из повода, 4 из 23 → те же фото-маршруты (у персон это портрет).
Голое лого (P154) идёт ПОСЛЕДНИМ и только как страховка: владелец 31.08 — «просто логотип на белом
фоне, можно же немного интереснее подобрать». Оно лучше, чем пост без обложки, но хуже всего живого.

Почему Wikidata, а не поиск по названию. Поиск по строке путает однофамильцев: 31.08 запрос
«Robinhood Chain» в Википедии первым отдал суринамский футбольный клуб SV Robinhood. Wikidata
опознаёт СУЩНОСТЬ («Robinhood — американская финансовая компания») и хранит у неё официальное лого
(P154), заглавное изображение (P18) и адрес сайта (P856) — то есть отвечает не «что похоже
называется», а «что это за объект». Плюс её API умеет отдавать SVG растром (iiurlwidth), а на
Commons фирменные лого почти все векторные — без этого мы бы их выбрасывали.

Почему не картиночный поиск Google/Bing: нет ключа, нет лицензии, и выдача вернёт те же ИИ-шапки
крипто-медиа. Wikimedia и официальный сайт дают ИМЕННО объект, отдают всем и без блокировок
(крипто-медиа режут ботов: coindesk отвечает 429, theblock — 403), лицензия у Commons свободная.

Кадр отсюда — КАНДИДАТ, а не решение: годен он или нет, по-прежнему судит vision по критериям
`_MEDIA_CRITERIA` в core/scope_writer. Наше дело — чтобы ему было из чего выбирать.

Сеть идёт через feeds.fetch_bytes → там SSRF-защита и проверка редиректов.
"""
from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import quote, urljoin

from connectors.web_sources import feeds

_WIKI_API = "https://en.wikipedia.org/w/api.php"
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# Годные расширения ФАЙЛА-ИСТОЧНИКА. SVG сюда входит: Commons отдаёт его растром через iiurlwidth
# (см. _commons_file_url), а вот Telegram вектор фотографией не принял бы.
_FILE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".svg")
# Ширина растра, который просим у Commons. 1200 — с запасом под телеграмный кроп и под наш ресайз
# до 1600 в fetch._normalize; больше просить незачем, это лишний вес и лишние токены vision.
THUMB_WIDTH = 1200
# Лого часто небольшое, общий пол разрешения (500/800px) выбросил бы его целиком. 400px — граница,
# ниже которой вордмарк в ленте Telegram уже мылит.
MIN_LOGO_SIDE = 400
# Сколько сущностей повода отрабатываем: писатель перечисляет их по важности, дальше третьей идут
# второстепенные тикеры, а каждый лишний кадр стоит vision-токенов.
SUBJECT_CAP = 3
# Пауза перед повтором к Wikimedia: их лимитер отпускает за секунду-две, а прогон обложки и так
# не в горячем пути (пост уже написан).
_RETRY_PAUSE_SEC = 1.5
# Минимальный зазор между обращениями к Wikimedia — их лимитер отпускает примерно с такой частотой.
_MIN_GAP_SEC = 0.6


_last_call = 0.0


def _throttle() -> None:
    """Не долбить Wikimedia очередью запросов. Их лимитер отвечает 429 именно на пачку: поодиночке
    «Michael Saylor» и «Federal Reserve» находятся мгновенно, а десятым запросом подряд — уже нет.
    Пауза между обращениями дешевле повторов и делает обложку предсказуемой, а не везучей."""
    global _last_call
    wait = _MIN_GAP_SEC - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _api_json(url: str) -> dict:
    """GET → JSON. Любой сбой (сеть/битый ответ) — пустой словарь: обложка не должна ронять прогон.

    ОДИН ПОВТОР ПОСЛЕ ПАУЗЫ (31.08). Wikimedia режет частые обращения, и на прогоне это выглядело как
    «объект не опознан»: «Michael Saylor» и «Federal Reserve» поодиночке находились мгновенно, а в
    очереди из десятка запросов молча отваливались. Без повтора обложка зависела бы от везения."""
    for attempt in (0, 1):
        _throttle()
        got = feeds.fetch_bytes(url, max_bytes=400_000)
        if got:
            try:
                return json.loads(got[0].decode("utf-8", errors="replace")) or {}
            except Exception:
                logging.info("subject_media: ответ API не разобрался (%s)", url.split("?")[0])
                return {}
        if not attempt:
            logging.info("subject_media: %s не ответил (%s) — повтор через паузу",
                         url.split("?")[0], feeds.last_error(url) or "?")
            time.sleep(_RETRY_PAUSE_SEC)
    return {}


def split_subject(subject: str) -> list[str]:
    """Строка [[MEDIA_SUBJECT]] → список сущностей. «Michael Saylor, Strategy, MSTR» → три штуки.

    Отсеиваем мусор: пустое, слишком короткое (тикер из двух букв ничего не опознает) и слишком
    длинное (писатель иногда вписывает целую фразу вместо имени)."""
    parts = re.split(r"[,;/|]|\s+—\s+|\s+-\s+", subject or "")
    out: list[str] = []
    for p in parts:
        name = " ".join(p.split()).strip("«»\"'.()")
        if 3 <= len(name) <= 60 and name.lower() not in {n.lower() for n in out}:
            out.append(name)
    return out


def _commons_file_url(filename: str) -> str | None:
    """Имя файла на Commons → прямой URL картинки нужной ширины. SVG приходит уже растром (PNG).

    Через imageinfo, а не через Special:FilePath: FilePath отдал бы вектор как есть, а Telegram
    вектор фотографией не примет. Заодно тут же видим размер и отсекаем мелочь."""
    if not filename or not filename.split("?")[0].lower().endswith(_FILE_EXT):
        return None
    data = _api_json(f"{_COMMONS_API}?action=query&titles={quote('File:' + filename)}"
                     f"&prop=imageinfo&iiprop=url|size&iiurlwidth={THUMB_WIDTH}&format=json")
    for page in ((data.get("query") or {}).get("pages") or {}).values():
        for info in page.get("imageinfo") or []:
            url = info.get("thumburl") or info.get("url") or ""
            # У растра меряем отданный размер, у вектора — то, во что его отрендерили.
            side = max(int(info.get("thumbwidth") or info.get("width") or 0),
                       int(info.get("thumbheight") or info.get("height") or 0))
            if url and side >= MIN_LOGO_SIDE:
                return url
    return None


# ══ ПРОВЕРКА СМЫСЛА: ТА ЛИ ЭТО СУЩНОСТЬ (31.08) ══
# Wikidata отлично различает однофамильцев, но на АББРЕВИАТУРАХ выдаёт мусор с полной уверенностью:
# «SEC» → «секунда, единица времени СИ», «FOMC» → «бывший военный форт», «Robinhood Chain» →
# суринамский футбольный клуб. Обложка при этом получалась бы идеально «по объекту» и абсолютно не по
# теме. Дешёвая защита — прочитать ОПИСАНИЕ сущности: наши поводы это компании, институты, рынки и
# люди из бизнеса, а не единицы измерения, сёла, виды жуков и альбомы.
_OFFTOPIC = re.compile(
    r"\b(unit of|SI unit|fort\b|football|soccer|basketball|village|municipalit|commune|river|"
    r"mountain|island|species|genus|moth|beetle|plant|film|movie|album|song|band\b|novel|manga|"
    r"video game|given name|surname|family name|census-designated|crater|asteroid|painting|"
    r"church|monastery|railway station|ratio of|trigonometr|mathematic|geometr|chemical|"
    r"disambiguation|Wikimedia)", re.I)
_ONTOPIC = re.compile(
    r"\b(compan|corporation|corporate|exchange|bank|financ|cryptocurrenc|crypto|blockchain|"
    r"platform|protocol|agenc|regulator|government|institution|business|technolog|software|"
    r"fintech|broker|fund\b|organization|organisation|entrepreneur|executive|investor|"
    r"politician|economist|stablecoin|token)", re.I)


def _is_acronym(entity: str) -> bool:
    """«SEC», «FOMC», «MSTR» — короткое сокращение из одних заглавных, без пробелов."""
    e = (entity or "").strip()
    return len(e) <= 5 and e.isupper() and " " not in e


def entity_id(entity: str) -> tuple[str, str]:
    """Опознать объект в Wikidata: (QID, описание) или ('', ''). Описание не только для лога — по нему
    отсеиваются чужие сущности (см. блок выше): среди пяти кандидатов берём первый, чьё описание
    похоже на бизнес/институт/человека из деловой среды, а очевидно чужие пропускаем.

    Ничего подходящего → ('', ''), и маршрут уходит на текстовый поиск по Commons, который требует
    имя объекта в ИМЕНИ ФАЙЛА — там промахнуться сложнее."""
    found = _api_json(f"{_WIKIDATA_API}?action=wbsearchentities&search={quote(entity)}"
                      f"&language=en&format=json&limit=5")
    fallback = ("", "")
    for hit in found.get("search") or []:
        qid, descr = hit.get("id") or "", (hit.get("description") or "")
        if not re.fullmatch(r"Q\d+", qid):
            continue
        if _OFFTOPIC.search(descr):
            logging.info("subject_media: «%s» → %s отброшен как не по теме (%s)", entity, qid, descr)
            continue
        if _ONTOPIC.search(descr):
            return qid, descr
        # НЕЙТРАЛЬНОЕ ОПИСАНИЕ — ТОЛЬКО ДЛЯ ПОЛНОГО ИМЕНИ, НЕ ДЛЯ АББРЕВИАТУРЫ (31.08). У «Robinhood»
        # или «Michael Saylor» промахнуться сложно. А голая аббревиатура совпадает с чем угодно:
        # «SEC» подряд дал секунду, секанс и грамматический падеж — и каждый следующий запрет ловил
        # ровно один из них. Поэтому для коротких заглавных сокращений принимаем ТОЛЬКО явно
        # профильное описание, а иначе отдаём поиску по Commons — там имя должно стоять в файле.
        if not fallback[0] and not _is_acronym(entity):
            fallback = (qid, descr)
    return fallback


def _claims(qid: str) -> dict:
    return (_api_json(f"{_WIKIDATA_API}?action=wbgetclaims&entity={qid}&format=json")
            .get("claims") or {})


def _claim_values(claims: dict, prop: str) -> list:
    out = []
    for c in claims.get(prop) or []:
        val = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if val:
            out.append(val)
    return out


_META_OG = re.compile(
    r"""<meta[^>]*?(?:property|name)\s*=\s*["']og:image(?::url)?["'][^>]*?\bcontent\s*=\s*["']([^"']+)["']""",
    re.I)
_META_OG_REV = re.compile(
    r"""<meta[^>]*?\bcontent\s*=\s*["']([^"']+)["'][^>]*?(?:property|name)\s*=\s*["']og:image(?::url)?["']""",
    re.I)


def _og_image(site: str) -> str | None:
    """og:image страницы — «бренд-полотно» официального сайта (тип 1)."""
    got = feeds.fetch_bytes(site)
    if not got:
        return None
    html = got[0].decode("utf-8", errors="replace")
    for rx in (_META_OG, _META_OG_REV):
        m = rx.search(html)
        if m:
            return urljoin(site, m.group(1).strip())
    return None


def _commons_search(query: str, entity: str) -> str | None:
    """Текстовый поиск кадра по Commons — для объектов, которых нет в Wikidata, и для фото зданий.

    Требуем, чтобы объект встречался в ИМЕНИ ФАЙЛА: иначе поиск подсовывает случайные документы по
    совпадению слов в описании (реальный ответ 31.08 первым отдал PDF про выборы)."""
    url = (f"{_COMMONS_API}?action=query&generator=search&gsrsearch={quote(query)}"
           f"&gsrnamespace=6&gsrlimit=8&prop=imageinfo&iiprop=url|size&iiurlwidth={THUMB_WIDTH}"
           f"&format=json")
    pages = ((_api_json(url).get("query") or {}).get("pages") or {})
    # СОВПАДЕНИЕ ПО ГРАНИЦЕ СЛОВА, А НЕ ПО ПОДСТРОКЕ (31.08). Аббревиатуры коротки, и подстрочный
    # поиск на них врёт: «SEC» находился внутри «Secant.svg». Границей слова такой промах отсекается.
    key = re.escape(" ".join((entity or "").split()).lower())
    rx = re.compile(rf"(?<![a-z0-9]){key}(?![a-z0-9])", re.I) if key else None
    for page in pages.values():
        title = (page.get("title") or "").lower()
        if rx and not rx.search(title):
            continue
        for info in page.get("imageinfo") or []:
            url_ = info.get("thumburl") or info.get("url") or ""
            side = max(int(info.get("thumbwidth") or info.get("width") or 0),
                       int(info.get("thumbheight") or info.get("height") or 0))
            if url_ and side >= MIN_LOGO_SIDE:
                return url_
    return None


def wiki_page_image(qid: str) -> str | None:
    """Главная картинка статьи Википедии — здание/печать института (тип 2) или портрет человека
    (тип 3). Статью берём по СВЯЗИ из Wikidata (sitelink), а не поиском по строке: поиск и приводил
    к футбольному клубу вместо брокера."""
    data = _api_json(f"{_WIKIDATA_API}?action=wbgetentities&ids={qid}&props=sitelinks&format=json")
    title = (((data.get("entities") or {}).get(qid) or {}).get("sitelinks") or {}) \
        .get("enwiki", {}).get("title", "")
    if not title:
        return None
    page_data = _api_json(f"{_WIKI_API}?action=query&prop=pageimages&piprop=original"
                          f"&titles={quote(title)}&redirects=1&format=json")
    for page in ((page_data.get("query") or {}).get("pages") or {}).values():
        src = (page.get("original") or {}).get("source") or ""
        if src.split("?")[0].lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            return src
    return None


def commons_photo(entity: str) -> str | None:
    """Живое ФОТО объекта с Commons: штаб-квартира, вывеска, офис (тип 2 — 7 кадров из 23).

    Отдельный маршрут от лого, потому что ищется другим запросом. Фото интереснее вордмарка, поэтому
    в порядке предпочтения оно стоит ВЫШЕ лого (владелец 31.08: «просто логотип на белом фоне —
    можно же немного интереснее подобрать»)."""
    return _commons_search(f"{entity} headquarters", entity) or _commons_search(f"{entity} building",
                                                                                entity)


def subject_image_urls(subject: str, limit: int = 4) -> list[str]:
    """Кадры-кандидаты, НАЙДЕННЫЕ по объекту повода.

    ПОРЯДОК = ОТ ИНТЕРЕСНОГО К СТРАХОВОЧНОМУ (владелец 31.08). Сперва живая композиция — бренд-полотно
    официального сайта и настоящее фото (штаб-квартира, человек, продукт), и только последним голое
    лого. Замер 23 обложек показывает, что лого — самый ЧАСТЫЙ тип, но частый он был не от хорошей
    жизни: сложное искать было нечем. Голый вордмарк на белом работает как страховка «лучше он, чем
    ничего», а не как цель.

    Первой сущности приоритет: писатель перечисляет их по важности, и кадр главного героя повода
    ценнее второстепенного. Сбой одного маршрута не отменяет остальные — обложка не должна зависеть
    от одного сервиса. Кто из принесённых кадров годится, решает vision в core/scope_writer."""
    rich: list[str] = []      # живое: полотно бренда, фото здания/человека
    plain: list[str] = []     # страховка: голое лого
    seen: set[str] = set()

    def add(bucket: list, url: str | None, what: str, entity: str) -> None:
        if url and url not in seen:
            seen.add(url)
            bucket.append(url)
            logging.info("subject_media: «%s» → %s", entity, what)

    for entity in split_subject(subject)[:SUBJECT_CAP]:
        if len(rich) >= max(1, limit):
            break
        try:
            qid, descr = entity_id(entity)
            if not qid:
                logging.info("subject_media: «%s» — в Wikidata не опознан, иду поиском по Commons",
                             entity)
                add(rich, commons_photo(entity), "фото (поиск Commons)", entity)
                add(plain, _commons_search(f"{entity} logo", entity), "лого (поиск Commons)", entity)
                continue
            logging.info("subject_media: «%s» = %s (%s)", entity, qid, descr or "без описания")
            claims = _claims(qid)
            for site in _claim_values(claims, "P856")[:1]:       # официальный сайт → бренд-полотно
                if isinstance(site, str) and site.startswith("http"):
                    add(rich, _og_image(site), f"бренд-полотно {site}", entity)
            for fname in _claim_values(claims, "P18")[:1]:       # заглавное фото (здание/лицо/продукт)
                add(rich, _commons_file_url(fname), f"фото Wikidata ({fname})", entity)
            add(rich, wiki_page_image(qid), "картинка статьи Википедии", entity)
            add(rich, commons_photo(entity), "фото штаб-квартиры (Commons)", entity)
            # ЛОГО БЕРЁМ ЛУЧШЕЕ ИЗ ВСЕХ, А НЕ ПЕРВОЕ (31.08). У Robinhood в P154 два файла: первым
            # лежит растр 287x72 (мелочь, отбраковка по разрешению), вторым — вектор, который Commons
            # рендерит в 1200px. Брали первый и теряли лого целиком. Вектор вперёд: он масштабируется.
            for fname in sorted(_claim_values(claims, "P154")[:3],
                                key=lambda f: not str(f).lower().endswith(".svg")):
                url = _commons_file_url(fname)
                if url:
                    add(plain, url, f"лого Wikidata ({fname})", entity)
                    break
        except Exception:
            logging.info("subject_media: поиск по «%s» не отработал — иду дальше", entity)
    out = (rich + plain)[:limit]
    if not out:
        logging.info("subject_media: по объекту «%s» кадров не нашлось", (subject or "")[:80])
    return out
