"""Чтение RSS/Atom-фидов Тир-2 (по трекам crypto/ai) — «руки» Скаута для разведки тезисов.

Список фидов — в sources.yaml рядом (сгруппирован по трекам). Каждый фид читается
изолированно: сломанный/недоступный не роняет остальные.
"""
from __future__ import annotations

import gzip
import ipaddress
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

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


# --- SSRF-защита: fetch_page берёт URL из веб-контента (недоверенный вход), поэтому НЕ пускаем
# запросы на приватные/локальные адреса (метаданные облака 169.254.169.254, 127.0.0.1, внутренняя сеть). ---
def _ip_is_blocked(ip_str: str) -> bool:
    """True для приватных/loopback/link-local/reserved/multicast адресов (и для не-IP)."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def _host_is_blocked(host: str) -> bool:
    """True, если хост сам является или резолвится в заблокированный адрес. Не резолвится → блок."""
    if not host:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True
    return any(_ip_is_blocked(info[4][0]) for info in infos)


def _url_blocked_reason(url: str) -> str | None:
    """Причина блокировки URL или None если безопасен (http/https + публичный адрес)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return "нужен http/https"
    if _host_is_blocked(p.hostname or ""):
        return "приватный/локальный адрес (SSRF-защита)"
    return None


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Перепроверяет КАЖДЫЙ редирект: открытый хост может увести на внутренний адрес."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        reason = _url_blocked_reason(newurl)
        if reason:
            raise urllib.error.HTTPError(newurl, code, f"редирект заблокирован ({reason})", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_SAFE_OPENER = urllib.request.build_opener(_SafeRedirect())


def fetch_page(url: str, limit: int = 4000) -> str:
    """Скачать страницу по ссылке и вернуть очищенный текст.

    «Рука» для Скаута: прочитать источник и вытащить ТОЧНЫЕ цифры/цитаты, а не только
    сниппет из поиска. Клиентская загрузка (urllib) — без серверных контейнеров.
    SSRF-защита: блокируем приватные/локальные адреса и проверяем редиректы.
    """
    reason = _url_blocked_reason(url)
    if reason:
        return f"Ссылку не открыл ({reason})."
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ScoutBot)"})
    try:
        with _SAFE_OPENER.open(req, timeout=15) as resp:
            raw = resp.read(800_000)  # кап на размер тела
            charset = resp.headers.get_content_charset() or "utf-8"
            html = raw.decode(charset, errors="replace")
    except Exception as e:  # таймаут/403/404/сеть — отдаём как текст, не роняем агента
        return f"Не удалось открыть страницу: {e}"
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)  # вырезать код/стили
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", html)).strip()
    return text[:limit] or "(страница без читаемого текста — возможно, требует JS)"


# ══ ЗАБОР В ДВА ЗАХОДА: «бот» → «браузер» (31.08) ══
# Крипто-медиа режут очевидных ботов, и режут именно там, где кадры лучше всего: замер 31.08 —
# coindesk.com отвечает 429, theblock.co 403, а decrypt/coingape/cointelegraph/crypto.news 200.
# То есть пул обложки набивался вторым эшелоном (у которого шапки нарисованы нейросетью), а тир-1
# выпадал молча. Отсюда две правки: (1) на отказе повторяем запрос браузерными заголовками;
# (2) причина отказа больше не проглатывается — она пишется в лог и её видно в прогоне.
# ЗАГОЛОВКИ РЕШАЮТ БОЛЬШЕ, ЧЕМ КАЗАЛОСЬ (замер 31.08). urllib по умолчанию не шлёт ни `Accept`, ни
# `Accept-Encoding`, и на этом Wikimedia отдавала 429 с ТРЕТЬЕГО запроса подряд — тот же самый запрос
# из curl проходил 8 из 8. В прогоне это выглядело как «объект не опознан», то есть обложка молча
# зависела от везения. С `Accept: */*` и `Accept-Encoding: gzip` — 8 из 8 успешно.
_UA_BOT = "TG-Agents/1.0 (+https://github.com/Kanaki-K/TG-Agents)"  # описательный агент, как просит Wikimedia
_UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
_BOT_HEADERS = {"User-Agent": _UA_BOT, "Accept": "*/*", "Accept-Encoding": "gzip"}
_BROWSER_HEADERS = {
    "User-Agent": _UA_BROWSER,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
}


def _read_body(resp, max_bytes: int) -> bytes:
    """Тело ответа с распаковкой gzip. Сжатие просим сами (см. выше), значит сами и разжимаем;
    битый gzip отдаём как есть — пусть разбирается вызывающий, ронять забор из-за этого незачем."""
    raw = resp.read(max_bytes)
    if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
        try:
            return gzip.decompress(raw)
        except Exception:
            return raw
    return raw


def fetch_bytes(url: str, max_bytes: int = 800_000, timeout: int = 15) -> tuple[bytes, str] | None:
    """SSRF-безопасный GET → (тело, content-type) или None (заблокирован/ошибка/таймаут).

    Общий низкоуровневый забор для «рук», которым нужны сырые байты (og:image страницы,
    скачивание картинки первоисточника), а не очищенный текст. Та же защита, что у fetch_page:
    блокируем приватные/локальные адреса и проверяем каждый редирект.

    Отказ первого захода (403/429 у изданий, режущих ботов) — не приговор: повторяем браузерными
    заголовками. Причина последнего отказа доступна вызывающему через `last_error` — молчаливый
    None и был тем, из-за чего пул обложки годами терял лучшие источники незаметно.
    """
    reason = _url_blocked_reason(url)
    if reason:
        _LAST_ERROR[url] = reason
        return None
    err = ""
    for headers in (_BOT_HEADERS, _BROWSER_HEADERS):
        req = urllib.request.Request(url, headers=headers)
        try:
            with _SAFE_OPENER.open(req, timeout=timeout) as resp:
                _LAST_ERROR.pop(url, None)
                return _read_body(resp, max_bytes), (resp.headers.get_content_type() or "")
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            if e.code not in (401, 403, 405, 406, 429, 503):
                break            # 404/410 браузерными заголовками не лечится — второй заход впустую
        except Exception as e:   # таймаут/сеть/DNS — не роняем вызывающего
            err = type(e).__name__
            break
    _LAST_ERROR[url] = err or "неизвестно"
    return None


_LAST_ERROR: dict[str, str] = {}


def last_error(url: str) -> str:
    """Почему последний fetch_bytes по этому URL вернул None («HTTP 429», «timeout»). Пусто — успех."""
    return _LAST_ERROR.get(url, "")


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
