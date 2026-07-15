"""Общий HTTP-слой к Threads Graph API. Только stdlib urllib — без новых зависимостей.

Хост фиксирован (graph.threads.net) — SSRF неприменим. OAuth-эндпоинты (обмен/refresh токена)
живут в auth.py отдельными литералами (у них другой базовый путь, без версии).

Версию пути (v1.0) держим в одной константе — если Meta потребует иной префикс,
правится в одном месте. ⚠ ПРОВЕРИТЬ на живом ответе: часть примеров в доке идёт без
'/v1.0' (graph.threads.net/{id}/...). Если словишь 400 на пути — сначала снять версию.

ЗАЩИТА АККАУНТА (15.07.2026). Этот файл — ЕДИНСТВЕННАЯ дверь наружу, поэтому темп, бюджет,
стоп-кран и журнал врезаны здесь, в `_open()`: обойти их из read/insights/replies нельзя даже
случайно. Логика — в `_guard.py`, там же разбор, почему это появилось (массовая выгрузка 14.07
→ проверка аккаунта). Правило: при сомнении НЕ ходить.

Токен уходит заголовком `Authorization: Bearer`, а НЕ в query-строке: в query он утекал бы в
логи любого прокси и в access-логи Meta. Query-вариант оставлен только для OAuth (там иначе нельзя).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from . import _guard
from ._guard import ThreadsBlocked  # noqa: F401 — реэкспорт: вызывающий код ловит его отсюда

API_HOST = "https://graph.threads.net"
API_VERSION = "v1.0"
GRAPH = f"{API_HOST}/{API_VERSION}"

# ЧЕСТНЫЙ UA: мы автоматика и не скрываем этого.
#
# Здесь стоял подставной Chrome — попытка не выглядеть машиной. Снято 15.07.2026, и вот почему.
# Мы — first-party клиент: читаем СВОЙ аккаунт по токену, который Meta сама и выдала. Нам нечего
# прятать, а притворяясь браузером, мы бы из законного использования API сделали ровно то, что
# Платформенные условия запрещают прямым текстом: «anything to circumvent, bypass, or override
# any technological measures that Meta uses to control or limit access». Подставной UA не защищал
# аккаунт — он создавал нарушение там, где его не было.
#
# Замедляться, чтобы не грузить чужой API, — законно. Притворяться человеком, чтобы не спалиться,
# — нет. Разница в намерении, и она должна быть видна в коде. Опознавательный UA = мы готовы
# показать Meta этот файл целиком.
USER_AGENT = "tg-agents/1.0 (first-party Threads client; own-account analytics)"


class ThreadsError(RuntimeError):
    """Ошибка обращения к Threads API с человекочитаемым сообщением."""


def _extract_error(body: bytes) -> tuple[str, int | None]:
    """Достаёт (текст, код Meta). Код нужен ПРОГРАММНО — по нему срабатывает предохранитель."""
    try:
        err = (json.loads(body.decode("utf-8")) or {}).get("error") or {}
        msg = err.get("message") or ""
        code = err.get("code")
        code = int(code) if code is not None else None
        return f"{msg}{f' (code {code})' if code is not None else ''}".strip(), code
    except Exception:  # noqa: BLE001 — тело ошибки может быть не JSON
        return "", None


def _endpoint(url: str) -> str:
    """Путь без query — в журнал не должен попасть токен."""
    return urllib.parse.urlsplit(url).path


def _open(url: str, data: bytes | None = None, *, token: str | None = None,
          timeout: int = 20, write: bool = False) -> dict:
    ep = _endpoint(url)
    # пауза/бюджет/стоп-кран (для write — свои, строже). Кинет ThreadsBlocked — запроса не будет.
    t0 = _guard.before(ep, write=write)

    req = urllib.request.Request(url, data=data)  # data != None → POST
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", USER_AGENT)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — хост фиксирован
            body = json.loads(r.read().decode("utf-8"))
            # Расход квоты ГЛАЗАМИ Meta. getattr — заголовков может не быть; их отсутствие
            # не повод ронять сбор.
            usage = _guard.usage_from_headers(getattr(r, "headers", None))
        _guard.after(ep, t0, status=200, usage=usage, write=write)
        _guard.check_usage(usage)  # ≥80% → стоп САМИ, не дожидаясь отказа
        return body
    except urllib.error.HTTPError as e:
        detail, code = _extract_error(e.read())
        _guard.after(ep, t0, status=e.code, error=detail or str(e.reason), write=write)
        # Троттлинг → гасим весь прогон и уходим остывать (внутри кинет ThreadsBlocked).
        _guard.trip(e.code, code, detail or str(e.reason))
        raise ThreadsError(f"Threads API {e.code}: {detail or e.reason}") from e
    except urllib.error.URLError as e:
        _guard.after(ep, t0, status=None, error=str(e.reason), write=write)
        raise ThreadsError(f"Сеть недоступна: {e.reason}") from e
    except ThreadsBlocked:
        raise  # защита сработала после отправки — наверх как есть, это не сбой сети
    except Exception as e:  # noqa: BLE001
        _guard.after(ep, t0, status=None, error=f"{type(e).__name__}: {e}", write=write)
        raise ThreadsError(f"Сбой запроса к Threads: {type(e).__name__}: {e}") from e


def get(path: str, params: dict | None = None, *, token: str | None = None,
        versioned: bool = True) -> dict:
    """GET к graph-эндпоинту. path — без ведущего слэша ('{id}/threads').

    token= уходит заголовком Bearer. OAuth-вызовы (versioned=False) кладут свой access_token
    прямо в params — у них выбора нет, это часть протокола обмена.
    """
    q = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    base = GRAPH if versioned else API_HOST
    url = f"{base}/{path.lstrip('/')}?{urllib.parse.urlencode(q)}"
    return _open(url, token=token)


def post(path: str, params: dict, *, token: str | None = None,
         versioned: bool = True) -> dict:
    """POST (form-encoded) к graph-эндпоинту — публикация/обмен токена.

    Versioned POST = ЗАПИСЬ в аккаунт (пост/ответ/удаление) → полоса записи _guard (второй
    стоп-кран, свои бюджеты). OAuth-обмены (versioned=False) — не запись контента: они идут
    полосой чтения, иначе закрытая запись ломала бы авто-refresh токена.
    """
    q = {k: v for k, v in params.items() if v not in (None, "")}
    base = GRAPH if versioned else API_HOST
    url = f"{base}/{path.lstrip('/')}"
    return _open(url, data=urllib.parse.urlencode(q).encode("utf-8"), token=token,
                 write=versioned)
