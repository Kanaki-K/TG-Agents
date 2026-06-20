"""Нативная (отложенная) публикация поста в Telegram-канал через MTProto (userbot @Amanbabai228).

Это «руки» Публикатора. Кладём пост аккаунтом-владельцем (userbot), а НЕ Bot API: у userbot нет
лимитов Bot API, пост ложится в канал как руками человека (целевой вид — 17.png: обложка сверху +
полный текст одним сообщением).

ПО УМОЛЧАНИЮ постим ОТЛОЖЕННО (schedule=when): пост уходит в нативные «отложенные» канала на слот из
контент-плана, а живой контроль остаётся у владельца (видит/правит/отменяет в отложенных). Это сильнее
обычного гейта: бот не публикует вживую, а лишь ставит в очередь и уведомляет (чек-лист PLAN §6).

Переиспользуем ту же MTProto-сессию, что и аналитика (connectors/telegram_export: TELEGRAM_SESSION /
data/kanaki.session) — один аккаунт, две функции (read метрики + write публикация), логика раздельна.

Три пути доставки «обложка сверху + текст», выбор АВТОМАТОМ по длине (потолок подписи Telegram):
  1) текст ≤ лимита подписи (1024; 2048 с Premium) → фото + подпись, одним сообщением;
  2) текст длиннее → обложка крупным превью-ссылкой НАД полным текстом (флагман в подпись не влезает;
     у превью потолка нет, но Telegram тянет его только по ПУБЛИЧНОМУ URL — обложку заливаем на хостинг);
  3) URL не вышел / сбой → фолбэк: фото + полный текст двумя (отложенными) сообщениями — пост не теряем.
Без обложки — просто текст.

Текст уходит ДОСЛОВНО (parse_mode=None — без markdown/HTML-интерпретации). Синхронные обёртки гоняют
Telethon в своём event loop — их зовут из потока бота (asyncio.to_thread), как telegram_scan.recent.
"""
from __future__ import annotations

import asyncio
import html as _html
import logging
from datetime import datetime
from pathlib import Path

from connectors.telegram_export.collect import _client
from core import config

logging.basicConfig(level=logging.INFO)

CAPTION_LIMIT_FREE = 1024      # лимит подписи к фото у обычного аккаунта
CAPTION_LIMIT_PREMIUM = 2048   # лимит подписи с Telegram Premium
TEXT_LIMIT = 4096              # лимит текстового сообщения (и превью-картинки над ним)
ZWSP = "​"               # нулевой пробел — невидимый носитель ссылки на обложку (путь №2)
_TRUE = {"1", "true", "yes", "on", "да"}


def _caption_limit() -> int:
    """Потолок подписи к фото: 2048 если у аккаунта Premium (PUBLISH_PREMIUM=1), иначе 1024."""
    return CAPTION_LIMIT_PREMIUM if config.get_optional("PUBLISH_PREMIUM").lower() in _TRUE else CAPTION_LIMIT_FREE


def _post_link(entity, msg) -> str:
    """Ссылка на опубликованное сообщение: t.me/<username>/<id> или t.me/c/<id>/<id> (приватный)."""
    mid = getattr(msg, "id", None)
    uname = getattr(entity, "username", None)
    if uname:
        return f"https://t.me/{uname}/{mid}"
    eid = getattr(entity, "id", None)
    return f"https://t.me/c/{eid}/{mid}" if eid else f"(сообщение {mid})"


async def _upload_image(path: Path) -> str | None:
    """Залить обложку и вернуть ПРЯМОЙ публичный URL (для превью над длинным постом).

    0x0.st (отдаёт прямой URL в теле) → фолбэк catbox. Не вышло — None (откат на 2 сообщения).
    Хосты режут «пустой» User-Agent — шлём нормальный.
    """
    import aiohttp

    ua = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) TG-Agents/1.0"}
    img_bytes = path.read_bytes()
    timeout = aiohttp.ClientTimeout(total=60)
    try:  # 1) 0x0.st
        data = aiohttp.FormData()
        data.add_field("file", img_bytes, filename=path.name, content_type="image/png")
        async with aiohttp.ClientSession(headers=ua) as s:
            async with s.post("https://0x0.st", data=data, timeout=timeout) as r:
                body = (await r.text()).strip()
                logging.info("[публикатор] 0x0.st: HTTP %s, ответ=%.120s", r.status, body)
                if r.status == 200 and body.startswith("http"):
                    return body
    except Exception:
        logging.exception("[публикатор] 0x0.st не вышел — пробую catbox")
    try:  # 2) catbox — фолбэк
        data = aiohttp.FormData()
        data.add_field("reqtype", "fileupload")
        data.add_field("fileToUpload", img_bytes, filename=path.name, content_type="image/png")
        async with aiohttp.ClientSession(headers=ua) as s:
            async with s.post("https://catbox.moe/user/api.php", data=data, timeout=timeout) as r:
                url = (await r.text()).strip()
                logging.info("[публикатор] catbox: HTTP %s, ответ=%.120s", r.status, url)
                return url if url.startswith("http") else None
    except Exception:
        logging.exception("[публикатор] не смог залить обложку (catbox тоже)")
    return None


async def _publish_async(channel: str, text: str, cover: str | None,
                         long_mode: str, when: datetime | None) -> dict:
    """Поставить пост в канал (отложенно, если when задан). {ok, mode, link?} либо {ok: False, error}."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "Пустой текст — публиковать нечего."}
    if len(text) > TEXT_LIMIT:
        return {"ok": False, "error": f"Пост {len(text)} знаков > лимита Telegram {TEXT_LIMIT} — "
                                      "одним сообщением не уйдёт. Сократи у Криейтора."}

    client = _client()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return {"ok": False, "error": "MTProto-сессия не авторизована (TELEGRAM_SESSION пуст/протух). "
                                          "Вход: connectors/telegram_export/login.py."}
        try:
            entity = await client.get_entity(channel)
        except Exception as e:
            return {"ok": False, "error": f"Не нашёл канал «{channel}»: {e}. Проверь PUBLISH_CHANNEL и что "
                                          "аккаунт-публикатор добавлен в канал админом с правом постить."}

        def done(mode: str, msg) -> dict:
            # У отложенного поста публичной ссылки ещё нет — вернём только режим; ссылку для немедленного.
            out = {"ok": True, "mode": mode}
            if when is None:
                out["link"] = _post_link(entity, msg)
            return out

        if not cover:  # без обложки — просто текст
            msg = await client.send_message(entity, text, parse_mode=None, link_preview=False, schedule=when)
            return done("только текст", msg)

        vis, cap = len(text), _caption_limit()
        if vis <= cap:  # путь №1: короткий → фото + подпись (картинка сверху, одно сообщение)
            msg = await client.send_file(entity, cover, caption=text, parse_mode=None,
                                         force_document=False, schedule=when)
            return done("фото+подпись", msg)
        if long_mode != "split":  # путь №2: длинный → обложка крупным превью НАД текстом
            url = await _upload_image(Path(cover))
            if url:
                body = f'<a href="{url}">{ZWSP}</a>' + _html.escape(text)  # тело экранировано → текст дословно
                try:
                    msg = await client.send_message(entity, body, parse_mode="html",
                                                    link_preview=True, schedule=when)
                    return done("обложка-превью над текстом", msg)
                except Exception:
                    logging.exception("[публикатор] превью над текстом не вышло — фолбэк на 2 сообщения")
            else:
                logging.warning("[публикатор] обложку не залить на хостинг — фолбэк на 2 сообщения")
        # путь №3 (фолбэк): фото + полный текст раздельно — пост не теряем
        await client.send_file(entity, cover, force_document=False, schedule=when)
        msg = await client.send_message(entity, text, parse_mode=None, link_preview=False, schedule=when)
        return done("фото и текст РАЗДЕЛЬНО (фолбэк)", msg)
    finally:
        await client.disconnect()


async def _scheduled_async(channel: str) -> list:
    """Даты/время уже отложенных постов канала (для проверки занятости слотов). UTC-aware datetimes."""
    client = _client()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return []
        try:
            entity = await client.get_entity(channel)
            msgs = await client.get_messages(entity, scheduled=True, limit=100)
        except Exception:
            logging.exception("[публикатор] не смог прочитать отложенные")
            return []
        return [m.date for m in msgs if getattr(m, "date", None)]
    finally:
        await client.disconnect()


async def _check_async(channel: str) -> dict:
    """Предполётная проверка: авторизован ли аккаунт, какой это аккаунт, виден ли канал."""
    client = _client()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return {"ok": False, "error": "MTProto-сессия не авторизована (TELEGRAM_SESSION). "
                                          "Вход: connectors/telegram_export/login.py."}
        me = await client.get_me()
        who = f"@{me.username}" if getattr(me, "username", None) else (me.first_name or "?")
        out = {"ok": True, "account": who,
               "premium": bool(getattr(me, "premium", False)),
               "caption_limit": _caption_limit()}
        if channel:
            try:
                ent = await client.get_entity(channel)
                out["channel"] = getattr(ent, "title", None) or channel
            except Exception as e:
                out["channel"] = None
                out["channel_error"] = str(e)
        return out
    finally:
        await client.disconnect()


def publish(channel: str, text: str, cover: str | None = None, when: datetime | None = None) -> dict:
    """Синхронно поставить пост (зовётся из потока бота). when задан → нативный ОТЛОЖЕННЫЙ пост.
    long_mode из PUBLISH_LONG_MODE ('preview' по умолч. — обложка над текстом; 'split' — фото+текст)."""
    long_mode = (config.get_optional("PUBLISH_LONG_MODE") or "preview").lower()
    return asyncio.run(_publish_async(channel, text, (cover or "").strip() or None, long_mode, when))


def scheduled_times(channel: str) -> list:
    """Синхронно: список UTC-aware datetime уже отложенных постов канала."""
    return asyncio.run(_scheduled_async((channel or "").strip()))


def check(channel: str = "") -> dict:
    """Синхронная предполётная проверка сессии и доступности канала."""
    return asyncio.run(_check_async((channel or "").strip()))
