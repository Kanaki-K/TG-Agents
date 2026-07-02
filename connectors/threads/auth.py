"""Жизненный цикл токена Threads: разовый OAuth-бутстрап + авто-refresh.

Модель токенов Meta: код авторизации → короткоживущий токен (~1ч) → долгоживущий
(60 дней) → его можно обновлять (refresh) в окне «старше 24ч и младше 60д», получая
свежие 60 дней. Не обновил вовремя — доступ отваливается, нужен повторный бутстрап.

Раскладка секретов (из-за нашего харденинга .env закрыт на запись хуком):
- СТАТИЧЕСКИЕ секреты — в .env руками: THREADS_APP_ID, THREADS_APP_SECRET,
  THREADS_REDIRECT_URI (должен совпадать с redirect в настройках Meta-приложения).
- РОТИРУЕМЫЙ токен — пишем сами в data/threads_token.json (gitignore), т.к. .env код
  трогать не может.

Разовый вход:  python -m connectors.threads.auth
Дальше read/insights сами держат токен свежим через valid_token().
"""
from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path

from connectors.threads import _api
from core import config

ROOT = Path(__file__).resolve().parents[2]
TOKEN_FILE = ROOT / "data" / "threads_token.json"

AUTHORIZE_URL = "https://threads.net/oauth/authorize"
SCOPES = ["threads_basic", "threads_content_publish",
          "threads_manage_insights", "threads_manage_replies"]

_DAY = 86400
_REFRESH_MIN_AGE = 1 * _DAY       # Meta: токен обновляем не раньше чем через 24ч
_REFRESH_WHEN_LEFT = 15 * _DAY    # обновляем заранее, пока осталось > этого запаса


# --- хранилище токена -------------------------------------------------------

def load_token() -> dict | None:
    if not TOKEN_FILE.exists():
        return None
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — битый файл = как будто токена нет
        return None


def _save_token(access_token: str, user_id: str, expires_in: int, *,
                obtained_at: float | None = None) -> dict:
    now = time.time()
    data = {
        "access_token": access_token,
        "user_id": str(user_id),
        "obtained_at": obtained_at or now,
        "refreshed_at": now,
        "expires_at": now + int(expires_in),
    }
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


# --- обмены с Meta -----------------------------------------------------------

def _exchange_code(code: str) -> dict:
    """Код авторизации → короткоживущий токен (+ user_id). POST /oauth/access_token."""
    return _api.post("oauth/access_token", {
        "client_id": config.get_secret("THREADS_APP_ID"),
        "client_secret": config.get_secret("THREADS_APP_SECRET"),
        "grant_type": "authorization_code",
        "redirect_uri": config.get_secret("THREADS_REDIRECT_URI"),
        "code": code,
    }, versioned=False)


def _to_long_lived(short_token: str) -> dict:
    """Короткоживущий → долгоживущий (60 дней). GET /access_token."""
    return _api.get("access_token", {
        "grant_type": "th_exchange_token",
        "client_secret": config.get_secret("THREADS_APP_SECRET"),
        "access_token": short_token,
    }, versioned=False)


def _refresh(long_token: str) -> dict:
    """Продлить долгоживущий токен на новые 60 дней. GET /refresh_access_token."""
    return _api.get("refresh_access_token", {
        "grant_type": "th_refresh_token",
        "access_token": long_token,
    }, versioned=False)


def _me(token: str) -> dict:
    """Проверить токен и узнать свой user_id. GET /me."""
    return _api.get("me", {"fields": "id,username"}, token=token)


# --- публичный доступ --------------------------------------------------------

def valid_token() -> str:
    """Вернуть валидный access_token, при нужде тихо обновив его. Используют read/insights."""
    tok = load_token()
    if not tok:
        # Первый запуск: засеваем токен-файл из .env (THREADS_ACCESS_TOKEN) — один раз.
        # Дальше живём из data/threads_token.json и обновляемся сами, .env больше не нужен.
        seed = config.get_optional("THREADS_ACCESS_TOKEN")
        if not seed:
            raise _api.ThreadsError(
                "Токен Threads не задан. Вставь в .env строку THREADS_ACCESS_TOKEN=<токен> "
                "(один раз) и запусти снова — дальше он обновляется сам.")
        tok = save_manual_token(seed)
    now = time.time()
    if now >= tok.get("expires_at", 0):
        raise _api.ThreadsError(
            "⚠ Токен Threads ИСТЁК (прошло 60 дней без запусков). Что делать: "
            "1) сгенерируй новый токен в кабинете Meta; "
            "2) вставь его командой: python -m connectors.threads.auth --manual")
    age = now - tok.get("refreshed_at", now)
    left = tok.get("expires_at", now) - now
    # обновляем заранее, но только если токену уже больше суток (требование Meta)
    if age >= _REFRESH_MIN_AGE and left < _REFRESH_WHEN_LEFT:
        try:
            fresh = _refresh(tok["access_token"])
            tok = _save_token(fresh["access_token"], tok["user_id"],
                              fresh.get("expires_in", 60 * _DAY),
                              obtained_at=tok.get("obtained_at"))
        except _api.ThreadsError:
            pass  # не смогли обновить сейчас — старый ещё валиден, попробуем позже
    return tok["access_token"]


def user_id() -> str:
    tok = load_token()
    if not tok or not tok.get("user_id"):
        raise _api.ThreadsError(
            "Не знаю user_id Threads — вставь токен: python -m connectors.threads.auth --manual")
    return tok["user_id"]


def authorize_url() -> str:
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "client_id": config.get_secret("THREADS_APP_ID"),
        "redirect_uri": config.get_secret("THREADS_REDIRECT_URI"),
        "scope": ",".join(SCOPES),
        "response_type": "code",
    })


def bootstrap() -> None:
    """Разовый интерактивный вход: открой ссылку → одобри → вставь code из адреса."""
    print("\n1) Открой эту ссылку в браузере и одобри доступ своим Threads-аккаунтом:\n")
    print("   " + authorize_url() + "\n")
    print("2) После одобрения браузер перекинет на твой redirect_uri с ?code=... в адресе.")
    print("   Скопируй значение code (без хвоста '#_' в конце) и вставь сюда.\n")
    code = input("code = ").strip()
    # Threads иногда добавляет к коду хвост '#_' — срезаем всё от '#'
    code = code.split("#", 1)[0].strip()
    if not code:
        raise SystemExit("Пустой code — прервано.")

    short = _exchange_code(code)
    uid = short.get("user_id") or short.get("id") or ""
    long = _to_long_lived(short["access_token"])
    tok = _save_token(long["access_token"], uid, long.get("expires_in", 60 * _DAY))

    days = int((tok["expires_at"] - time.time()) / _DAY)
    print(f"\n✅ Готово. Токен сохранён в {TOKEN_FILE.relative_to(ROOT)} "
          f"(user_id={uid}, живёт ~{days} дн., обновляется сам).")


def save_manual_token(access_token: str) -> dict:
    """Сохранить уже готовый access_token (выданный в кабинете Meta), без входа через браузер.

    Полезно, когда токен получен вручную в дашборде — тогда redirect и OAuth-вход не нужны.
    Пытаемся продлить токен до долгоживущего (60 дней) — это НЕ требует redirect, только
    client_secret. Если продление недоступно (токен уже долгоживущий) — сохраняем как есть.
    Заодно дёргаем /me: это и проверка, что токен рабочий, и способ узнать user_id.
    """
    access_token = access_token.strip()
    if not access_token:
        raise SystemExit("Пустой токен — прервано.")

    expires_in = 60 * _DAY
    try:
        long = _to_long_lived(access_token)
        if long.get("access_token"):
            access_token = long["access_token"]
            expires_in = int(long.get("expires_in", expires_in))
            print("→ Токен продлён до долгоживущего (60 дней).")
    except _api.ThreadsError:
        # Обычно токен из кабинета уже долгоживущий — продлевать нечего, это норма.
        print("→ Токен уже долгоживущий, сохраняю как есть (срок ~60 дней).")

    me = _me(access_token)  # проверка токена + узнаём user_id
    uid = me.get("id") or ""
    if not uid:
        raise SystemExit("Не удалось узнать user_id по токену — токен неверный или без нужных прав?")

    tok = _save_token(access_token, uid, expires_in)
    days = int((tok["expires_at"] - time.time()) / _DAY)
    uname = me.get("username")
    who = f"@{uname}, " if uname else ""
    print(f"\n✅ Готово. Токен сохранён в {TOKEN_FILE.relative_to(ROOT)} "
          f"({who}user_id={uid}, живёт ~{days} дн., дальше обновляется сам).")
    return tok


if __name__ == "__main__":
    import sys

    if "--browser" in sys.argv:
        bootstrap()  # запасной путь: вход через браузер (OAuth + redirect)
    elif "--manual" in sys.argv:
        # запасной путь: ручной ввод в терминал (может рваться на длинных токенах)
        print("\nВставь access token и нажми Enter:")
        save_manual_token(input("access_token = "))
    else:
        # основной путь: берём токен из .env (THREADS_ACCESS_TOKEN), проверяем и сохраняем.
        seed = config.get_optional("THREADS_ACCESS_TOKEN")
        if not seed:
            print("Вставь в .env строку:  THREADS_ACCESS_TOKEN=<твой токен из кабинета Meta>\n"
                  "и запусти снова:  python -m connectors.threads.auth")
        else:
            save_manual_token(seed)
