"""Нативная публикация поста в Telegram-канал через MTProto (userbot @Amanbabai228).

Это «руки» Публикатора. Постим аккаунтом-владельцем (userbot), а НЕ Bot API: у userbot нет
лимитов Bot API, пост ложится в канал как руками человека (целевой вид — 17.png: обложка
сверху + полный текст одним сообщением).

Переиспользуем ту же MTProto-сессию, что и сбор аналитики (connectors/telegram_export:
TELEGRAM_SESSION в .env / data/kanaki.session) — один аккаунт, две функции (read метрики +
write публикация), логика держится раздельно.

Три пути доставки «обложка сверху + текст», выбор АВТОМАТОМ по длине (потолок подписи Telegram):
  1) текст ≤ лимита подписи (1024; 2048 с Premium) → фото + подпись, одним сообщением (чистый вид);
  2) текст длиннее → обложка крупным превью-ссылкой НАД полным текстом, одним сообщением
     (подпись бы не вместила флагман 2800–4096; у превью потолка нет, но Telegram тянет его
     только по ПУБЛИЧНОМУ URL — поэтому обложку заливаем на хостинг);
  3) URL не вышел / сбой → фолбэк: фото отдельным сообщением, затем полный текст
     (пост НИКОГДА не теряем — в худшем случае два сообщения вместо одного).
Без обложки — просто текст одним сообщением.

ВАЖНО (чек-лист безопасности PLAN §6): функция публикует РОВНО переданный текст, дословно
(parse_mode=None — без markdown/HTML-интерпретации), и только когда её явно позвал бот по
команде /publish владельца. Сама ничего не решает и по расписанию не постит.

Синхронные обёртки publish()/check() гоняют Telethon в собственном event loop — их зовут из
рабочего потока бота (asyncio.to_thread), где запущенного loop нет (как telegram_scan.recent).
"""
from __future__ import annotations

import asyncio
import html as _html
import logging
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
    """Ссылка на опубликованное сообщение: t.me/<username>/<id> или t.me/c/<id>/<id> для приватного."""
    mid = getattr(msg, "id", None)
    uname = getattr(entity, "username", None)
    if uname:
        return f"https://t.me/{uname}/{mid}"
    eid = getattr(entity, "id", None)
    return f"https://t.me/c/{eid}/{mid}" if eid else f"(сообщение {mid})"


async def _upload_image(path: Path) -> str | None:
    """Залить обложку и вернуть ПРЯМОЙ публичный URL (для превью над длинным постом).

    0x0.st (простой, отдаёт прямой URL в теле) → фолбэк catbox. Не вышло нигде — None
    (доставка откатится на 2 сообщения). Хосты режут «пустой» User-Agent — шлём нормальный.
    """
    import aiohttp

    ua = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) TG-Agents/1.0"}
    img_bytes = path.read_bytes()
    timeout = aiohttp.ClientTimeout(total=60)
    # 1) 0x0.st
    try:
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
    # 2) catbox — фолбэк
    try:
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


async def _publish_async(channel: str, text: str, cover: str | None, long_mode: str) -> dict:
    """Опубликовать пост в канал. Возвращает {ok, mode, link} либо {ok: False, error}."""
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
                                          "Сделай вход: connectors/telegram_export/login.py."}
        try:
            entity = await client.get_entity(channel)
        except Exception as e:  # канал не найден / нет доступа
            return {"ok": False, "error": f"Не нашёл канал «{channel}»: {e}. Проверь PUBLISH_CHANNEL и что "
                                          "аккаунт-публикатор добавлен в канал админом с правом постить."}

        # Без обложки — просто текст
        if not cover:
            msg = await client.send_message(entity, text, parse_mode=None, link_preview=False)
            return {"ok": True, "mode": "только текст", "link": _post_link(entity, msg)}

        vis, cap = len(text), _caption_limit()
        # Путь №1: короткий пост → фото + подпись (картинка сверху, одно сообщение)
        if vis <= cap:
            msg = await client.send_file(entity, cover, caption=text, parse_mode=None, force_document=False)
            return {"ok": True, "mode": "фото+подпись", "link": _post_link(entity, msg)}
        # Путь №2: длинный пост → обложка крупным превью НАД текстом (одно сообщение)
        if long_mode != "split":
            url = await _upload_image(Path(cover))
            if url:
                # Невидимая ссылка-носитель обложки в начале; тело экранируем — текст уходит ДОСЛОВНО.
                body = f'<a href="{url}">{ZWSP}</a>' + _html.escape(text)
                try:
                    msg = await client.send_message(entity, body, parse_mode="html", link_preview=True)
                    return {"ok": True, "mode": "обложка-превью над текстом", "link": _post_link(entity, msg)}
                except Exception:
                    logging.exception("[публикатор] превью над текстом не вышло — фолбэк на 2 сообщения")
            else:
                logging.warning("[публикатор] обложку не залить на хостинг — фолбэк на 2 сообщения")
        # Путь №3 (фолбэк): фото отдельным сообщением + полный текст — пост не теряем
        await client.send_file(entity, cover, force_document=False)
        msg = await client.send_message(entity, text, parse_mode=None, link_preview=False)
        return {"ok": True, "mode": "фото и текст РАЗДЕЛЬНО (фолбэк)", "link": _post_link(entity, msg)}
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


def publish(channel: str, text: str, cover: str | None = None) -> dict:
    """Синхронно опубликовать пост (зовётся из потока бота). long_mode из PUBLISH_LONG_MODE
    ('preview' по умолчанию — обложка над текстом; 'split' — всегда фото+текст раздельно)."""
    long_mode = (config.get_optional("PUBLISH_LONG_MODE") or "preview").lower()
    return asyncio.run(_publish_async(channel, text, (cover or "").strip() or None, long_mode))


def check(channel: str = "") -> dict:
    """Синхронная предполётная проверка сессии и доступности канала."""
    return asyncio.run(_check_async((channel or "").strip()))
