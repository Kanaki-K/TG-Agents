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

from telethon.errors import MediaCaptionTooLongError
from telethon.tl import functions

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


async def _publish_async(channel: str, text: str, cover: str | None, when: datetime | None) -> dict:
    """Поставить пост в канал отложенно (when). ФАЙЛОМ, без URL/превью: фото-файл + текст-подпись
    одним сообщением; если подпись длиннее лимита Telegram — фото + текст двумя сообщениями.
    {ok, mode, link?} либо {ok: False, error}."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "Пустой текст — публиковать нечего."}
    if len(text) > TEXT_LIMIT:
        return {"ok": False, "error": f"Пост {len(text)} знаков > лимита Telegram {TEXT_LIMIT}. Сократи."}

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
            out = {"ok": True, "mode": mode}
            if when is None:  # у отложенного публичной ссылки ещё нет
                out["link"] = _post_link(entity, msg)
            return out

        # Рендер как у Криейтора в чате: жирный (**…**→bold) + кастом-эмодзи (<tg-emoji emoji-id=…> из
        # data/custom_emoji.json; премиум-аккаунт их шлёт). Сбой разметки → чистый текст (пост не теряем).
        html = tg_format.to_telegram_html(text, custom_emoji=True)

        async def _msg(target):
            try:
                return await client.send_message(target, html, parse_mode="html",
                                                 link_preview=False, schedule=when)
            except Exception:
                logging.exception("[публикатор] HTML отклонён — чистым текстом")
                return await client.send_message(target, text, parse_mode=None,
                                                 link_preview=False, schedule=when)

        if not cover:  # без обложки — просто текст
            return done("только текст", await _msg(entity))

        # С обложкой (файл от ГПТ/владельца): фото + текст-подпись ОДНИМ сообщением.
        for pm, body in (("html", html), (None, text)):  # html, при сбое разметки — чистый
            try:
                msg = await client.send_file(entity, cover, caption=body, parse_mode=pm,
                                             force_document=False, schedule=when)
                return done("фото + текст (одним сообщением)", msg)
            except MediaCaptionTooLongError:
                break  # подпись длиннее лимита Telegram — уходим на два сообщения
            except Exception:
                logging.exception("[публикатор] подпись (%s) отклонена — пробую дальше", pm)
        # Подпись не вместила текст → фото + текст двумя сообщениями (Telegram-лимит подписи; пост не теряем)
        await client.send_file(entity, cover, force_document=False, schedule=when)
        return done("фото + текст (два сообщения — текст не влез в подпись)", await _msg(entity))
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
    Файлом: фото+текст одним сообщением, либо двумя, если текст не влез в подпись."""
    return asyncio.run(_publish_async(channel, text, (cover or "").strip() or None, when))


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
