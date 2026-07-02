"""Общий HTTP-слой к Threads Graph API. Только stdlib urllib — без новых зависимостей.

Хост фиксирован (graph.threads.net) — SSRF неприменим. Все запросы — GET к
graph-эндпоинтам с access_token в query. OAuth-эндпоинты (обмен/refresh токена)
живут в auth.py отдельными литералами (у них другой базовый путь, без версии).

Версию пути (v1.0) держим в одной константе — если Meta потребует иной префикс,
правится в одном месте. ⚠ ПРОВЕРИТЬ на живом ответе: часть примеров в доке идёт без
'/v1.0' (graph.threads.net/{id}/...). Если словишь 400 на пути — сначала снять версию.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

API_HOST = "https://graph.threads.net"
API_VERSION = "v1.0"
GRAPH = f"{API_HOST}/{API_VERSION}"


class ThreadsError(RuntimeError):
    """Ошибка обращения к Threads API с человекочитаемым сообщением."""


def _extract_error(body: bytes) -> str:
    try:
        err = (json.loads(body.decode("utf-8")) or {}).get("error") or {}
        msg = err.get("message") or ""
        code = err.get("code")
        return f"{msg}{f' (code {code})' if code is not None else ''}".strip()
    except Exception:  # noqa: BLE001 — тело ошибки может быть не JSON
        return ""


def _open(url: str, data: bytes | None = None, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, data=data)  # data != None → POST
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — хост фиксирован
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = _extract_error(e.read())
        raise ThreadsError(f"Threads API {e.code}: {detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise ThreadsError(f"Сеть недоступна: {e.reason}") from e
    except Exception as e:  # noqa: BLE001
        raise ThreadsError(f"Сбой запроса к Threads: {type(e).__name__}: {e}") from e


def get(path: str, params: dict | None = None, *, token: str | None = None,
        versioned: bool = True) -> dict:
    """GET к graph-эндпоинту. path — без ведущего слэша ('{id}/threads')."""
    q = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    if token:
        q["access_token"] = token
    base = GRAPH if versioned else API_HOST
    url = f"{base}/{path.lstrip('/')}?{urllib.parse.urlencode(q)}"
    return _open(url)


def post(path: str, params: dict, *, token: str | None = None,
         versioned: bool = True) -> dict:
    """POST (form-encoded) к graph-эндпоинту — публикация/обмен токена."""
    q = {k: v for k, v in params.items() if v not in (None, "")}
    if token:
        q["access_token"] = token
    base = GRAPH if versioned else API_HOST
    url = f"{base}/{path.lstrip('/')}"
    return _open(url, data=urllib.parse.urlencode(q).encode("utf-8"))
