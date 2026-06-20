"""Нативная (отложенная) публикация поста в Telegram-канал через MTProto (userbot @Amanbabai228).

Это «руки» Публикатора. Кладём пост аккаунтом-владельцем (userbot), а НЕ Bot API: у userbot нет
лимитов Bot API, пост ложится в канал как руками человека (целевой вид — 17.png: обложка сверху +
полный текст одним сообщением).

ПО УМОЛЧАНИЮ постим ОТЛОЖЕННО (schedule=when): пост уходит в нативные «отложенные» канала на слот из
контент-плана, а живой контроль остаётся у владельца (видит/правит/отменяет в отложенных). Это сильнее
обычного гейта: бот не публикует вживую, а лишь ставит в очередь и уведомляет (чек-лист PLAN §6).

Переиспользуем ту же MTProto-сессию, что и аналитика (connectors/telegram_export: TELEGRAM_SESSION /
data/evgeniyp.session) — один аккаунт, две функции (read метрики + write публикация), логика раздельна.

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
import logging
import re
from datetime import datetime
from pathlib import Path

from telethon import helpers
from telethon.extensions import html as _tl_html
from telethon.tl import functions, types

from connectors.telegram_export.collect import _client
from core import config, tg_format

logging.basicConfig(level=logging.INFO)

CAPTION_LIMIT_FREE = 1024      # лимит подписи к фото у обычного аккаунта
CAPTION_LIMIT_PREMIUM = 2048   # лимит подписи с Telegram Premium
TEXT_LIMIT = 4096              # лимит текстового сообщения (и превью-картинки над ним)
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


async def _resolve_entity(client, channel: str):
    """Найти канал надёжно, в т.ч. ПРИВАТНЫЙ (без публичного @username).

    Порядок: 1) приватная инвайт-ссылка t.me/+HASH (или joinchat/HASH) — достаём канал по хэшу,
    аккаунт уже в нём; 2) числовой id; 3) @username / t.me/username; 4) по названию среди диалогов.
    Приватный канал по «имени» (как @username) НЕЛЬЗЯ — оно резолвится в чужой публичный канал,
    отсюда был ChatWriteForbidden; инвайт-ссылка/id однозначны."""
    channel = (channel or "").strip()

    # 1) приватная инвайт-ссылка: t.me/+HASH или t.me/joinchat/HASH или голый +HASH
    m = re.search(r"(?:t\.me/\+|t\.me/joinchat/|^\+)([\w-]+)", channel)
    if m:
        try:
            inv = await client(functions.messages.CheckChatInviteRequest(m.group(1)))
            chat = getattr(inv, "chat", None)  # ChatInviteAlready/Peek — если аккаунт уже участник
            if chat is not None:
                return chat
            logging.warning("[публикатор] по инвайт-ссылке аккаунт НЕ участник канала — вступи им в канал")
        except Exception:
            logging.exception("[публикатор] инвайт-ссылку не разрешил")

    # 2) числовой id (-100…)
    if channel.lstrip("-").isdigit():
        return await client.get_entity(int(channel))

    # 3) @username / t.me/username
    try:
        return await client.get_entity(channel)
    except Exception:
        pass

    # 4) по названию среди диалогов (аккаунт в канале участник/админ)
    target = channel.lower().lstrip("@")
    async for d in client.iter_dialogs():
        if not (getattr(d, "is_channel", False) or getattr(d, "is_group", False)):
            continue
        title = (d.title or "").lower()
        uname = (getattr(d.entity, "username", None) or "").lower()
        if target and (target == uname or target == title or target in title):
            return d.entity
    raise ValueError(f"«{channel}» не найден ни как @username/id, ни по названию среди диалогов "
                     "аккаунта-публикатора (он точно админ/участник этого канала?)")


async def _upload_image(path: Path) -> str | None:
    """Залить обложку и вернуть ПРЯМОЙ публичный URL (для превью над длинным постом).

    imgbb (если задан IMGBB_API_KEY — НАДЁЖНО, рекомендуется) → telegra.ph → 0x0.st → catbox.
    Не вышло — None (откат на 2 сообщения). Хосты режут «пустой» User-Agent — шлём нормальный.
    """
    import base64
    import json as _json

    import aiohttp

    ua = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) TG-Agents/1.0"}
    img_bytes = path.read_bytes()
    timeout = aiohttp.ClientTimeout(total=60)
    imgbb_key = config.get_optional("IMGBB_API_KEY")
    if imgbb_key:  # 0) imgbb — стабильный, по бесплатному ключу (приоритет, если задан)
        try:
            data = aiohttp.FormData()
            data.add_field("image", base64.b64encode(img_bytes).decode())
            async with aiohttp.ClientSession(headers=ua) as s:
                async with s.post(f"https://api.imgbb.com/1/upload?key={imgbb_key}",
                                  data=data, timeout=timeout) as r:
                    body = (await r.text()).strip()
                    logging.info("[публикатор] imgbb: HTTP %s", r.status)
                    if r.status == 200:
                        url = (_json.loads(body).get("data") or {}).get("url", "")
                        if url:
                            return url
        except Exception:
            logging.exception("[публикатор] imgbb не вышел — пробую telegra.ph")
    try:  # 1) telegra.ph (Telegram-нативный, отдаёт [{"src":"/file/xxx.jpg"}])
        data = aiohttp.FormData()
        data.add_field("file", img_bytes, filename=path.name, content_type="image/png")
        async with aiohttp.ClientSession(headers=ua) as s:
            async with s.post("https://telegra.ph/upload", data=data, timeout=timeout) as r:
                body = (await r.text()).strip()
                logging.info("[публикатор] telegra.ph: HTTP %s, ответ=%.120s", r.status, body)
                if r.status == 200 and body.startswith("[{"):
                    src = _json.loads(body)[0].get("src", "")
                    if src:
                        return "https://telegra.ph" + src
    except Exception:
        logging.exception("[публикатор] telegra.ph не вышел — пробую 0x0.st")
    try:  # 2) 0x0.st
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
    try:  # 3) catbox — последний фолбэк
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
            entity = await _resolve_entity(client, channel)
        except Exception as e:
            return {"ok": False, "error": f"Не нашёл канал «{channel}»: {e}. Проверь PUBLISH_CHANNEL и что "
                                          "аккаунт-публикатор добавлен в канал админом с правом постить."}

        def done(mode: str, msg) -> dict:
            # У отложенного поста публичной ссылки ещё нет — вернём только режим; ссылку для немедленного.
            out = {"ok": True, "mode": mode}
            if when is None:
                out["link"] = _post_link(entity, msg)
            return out

        # Рендер как у Криейтора в чате: жирный (**…** → bold) + кастом-эмодзи из набора
        # (<tg-emoji emoji-id=…>, читается из data/custom_emoji.json). Аккаунт с премиумом их шлёт.
        html = tg_format.to_telegram_html(text, custom_emoji=True)

        async def _msg(target):  # текст с рендером; при сбое разметки — чистым, чтобы пост не потерять
            try:
                return await client.send_message(target, html, parse_mode="html",
                                                  link_preview=False, schedule=when)
            except Exception:
                logging.exception("[публикатор] HTML отклонён — шлю чистым текстом")
                return await client.send_message(target, text, parse_mode=None,
                                                 link_preview=False, schedule=when)

        if not cover:  # без обложки — просто текст
            return done("только текст", await _msg(entity))

        vis, cap = len(text), _caption_limit()
        if vis <= cap:  # короткий → фото + подпись ОДНИМ сообщением (картинка сверху)
            try:
                msg = await client.send_file(entity, cover, caption=html, parse_mode="html",
                                             force_document=False, schedule=when)
            except Exception:
                logging.exception("[публикатор] HTML-подпись отклонена — чистым текстом")
                msg = await client.send_file(entity, cover, caption=text, parse_mode=None,
                                             force_document=False, schedule=when)
            return done("фото+подпись", msg)

        if long_mode != "split":  # длинный → обложка КРУПНО НАД текстом, ОДНО сообщение (invert_media)
            try:
                url = await _upload_image(Path(cover))
                if url:
                    clean, entities = _tl_html.parse(html)  # текст + entities (жирный/эмодзи) для raw-запроса
                    peer = await client.get_input_entity(entity)
                    await client(functions.messages.SendMediaRequest(
                        peer=peer,
                        media=types.InputMediaWebPage(url=url, force_large_media=True, optional=True),
                        message=clean, entities=entities, invert_media=True,
                        random_id=helpers.generate_random_long(), schedule_date=when))
                    return {"ok": True, "mode": "обложка над текстом (одно сообщение)"}
                logging.warning("[публикатор] обложку не залить на хостинг — фолбэк на 2 сообщения")
            except Exception:
                logging.exception("[публикатор] фото-над-текстом не вышло — фолбэк на 2 сообщения")

        # фолбэк / режим split: фото + полный текст двумя сообщениями (пост не теряем)
        await client.send_file(entity, cover, force_document=False, schedule=when)
        return done("фото + полный текст (два сообщения)", await _msg(entity))
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
            entity = await _resolve_entity(client, channel)
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
                ent = await _resolve_entity(client, channel)
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


async def _notify_async(user: str, text: str) -> dict:
    """Отправить ЛС от аккаунта-публикатора пользователю (мейну владельца). user — @username/t.me/id."""
    client = _client()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return {"ok": False, "error": "сессия не авторизована"}
        ent = await client.get_entity(user)  # для пользователя @username/ссылка/id это работает напрямую
        await client.send_message(ent, text, parse_mode=None, link_preview=False)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        await client.disconnect()


def check(channel: str = "") -> dict:
    """Синхронная предполётная проверка сессии и доступности канала."""
    return asyncio.run(_check_async((channel or "").strip()))


def notify(user: str, text: str) -> dict:
    """Синхронно отправить уведомление в ЛС (мейну владельца) аккаунтом-публикатором."""
    return asyncio.run(_notify_async((user or "").strip(), text))
