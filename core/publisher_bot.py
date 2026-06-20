"""Публикатор — бот, который кладёт ОДОБРЕННЫЙ владельцем пост нативно в канал.

Намеренно ДЕТЕРМИНИРОВАННЫЙ: без LLM в цепочке публикации. Модель могла бы переписать пост
или «сама» опубликовать — а здесь пост должен уйти в канал РОВНО как владелец одобрил, и только
по явной команде. Это прямая реализация чек-листа безопасности (PLAN §6: «публикует не бот сам
по себе»). Поэтому Публикатору не нужен ни ключ Claude, ни agent_runtime — это «руки» с гейтом.

Поток (отдельный бот, выбор владельца):
  Криейтор → владелец правит/одобряет → пересылает финал + обложку Публикатору →
  Публикатор показывает предпросмотр → владелец жмёт /publish → пост уходит в канал (MTProto).

Команды: текст = финал поста; фото = обложка; /preview — что уйдёт; /check — проверить сессию и
канал; /publish — опубликовать (гейт); /discard — сбросить; /start, /help — справка.

Запуск: python run_publisher.py   (нужны PUBLISHER_BOT_TOKEN, PUBLISH_CHANNEL, TELEGRAM_SESSION).
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

from connectors.telegram_publish import publish
from core import config

logging.basicConfig(level=logging.INFO)

PENDING_FILE = config.ROOT / "data" / "publisher_pending.json"  # staged-пост (переживает рестарт), вне git
INCOMING = config.ROOT / "data" / "incoming"                    # сюда качаем присланную обложку

WELCOME = (
    "Я Публикатор. Кладу ОДОБРЕННЫЙ тобой пост нативно в канал (как руками), через аккаунт-"
    "публикатор. Сам ничего не переписываю и без твоей команды не публикую.\n\n"
    "Как пользоваться:\n"
    "1) пришли ФИНАЛЬНЫЙ текст поста (просто сообщением или пересылкой от Криейтора);\n"
    "2) пришли ОБЛОЖКУ картинкой (если есть) — подпись к фото можно не писать;\n"
    "3) /preview — покажу, что и как уйдёт; /publish — опубликую; /discard — сброшу.\n\n"
    "/check — проверю сессию и доступ к каналу перед боем. Текст уходит ДОСЛОВНО, без правок."
)


def _load() -> dict:
    try:
        return json.loads(PENDING_FILE.read_text(encoding="utf-8")) if PENDING_FILE.exists() else {}
    except Exception:
        logging.exception("Не смог прочитать staged-пост")
        return {}


def _save(data: dict) -> None:
    try:
        PENDING_FILE.parent.mkdir(exist_ok=True)
        PENDING_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logging.exception("Не смог сохранить staged-пост")


def _channel() -> str:
    return config.get_optional("PUBLISH_CHANNEL")


def _predict_mode(text: str, cover: str | None) -> str:
    """Каким путём уйдёт пост — чтобы показать владельцу в предпросмотре (логика как в коннекторе)."""
    if not cover:
        return "только текст, одним сообщением"
    if len(text) <= publish._caption_limit():
        return "фото + подпись, одним сообщением"
    if (config.get_optional("PUBLISH_LONG_MODE") or "preview").lower() == "split":
        return "фото и текст РАЗДЕЛЬНО (два сообщения)"
    return "обложка крупным превью НАД текстом, одним сообщением"


def _status(text: str, cover: str | None) -> str:
    ch = _channel() or "⚠ PUBLISH_CHANNEL не задан в .env"
    if not text:
        return f"Канал: {ch}\nПока пусто — пришли финальный текст поста."
    n = len(text)
    head = text[:280] + ("…" if n > 280 else "")
    return (f"Канал: {ch}\n"
            f"Текст: {n} знаков{' ✅' if n <= publish.TEXT_LIMIT else ' ⚠ > 4096, не уйдёт одним сообщением'}\n"
            f"Обложка: {'есть ✅' if cover else 'нет'}\n"
            f"Уйдёт как: {_predict_mode(text, cover)}\n\n"
            f"Начало:\n{head}\n\n"
            f"Готово? /preview — детально · /publish — опубликовать · /discard — сбросить")


async def main() -> None:
    token = config.get_secret("PUBLISHER_BOT_TOKEN")
    pending = _load()              # {chat_id(str): {text, cover}}
    publishing: set[int] = set()   # чаты с идущей публикацией — защита от двойного тапа /publish
    dp = Dispatcher()

    def _get(chat_id: int) -> dict:
        return pending.setdefault(str(chat_id), {"text": "", "cover": None})

    @dp.message(Command("start"))
    @dp.message(Command("help"))
    async def _start(m: Message) -> None:
        await m.answer(WELCOME)

    @dp.message(Command("check"))
    async def _check(m: Message) -> None:
        await m.bot.send_chat_action(m.chat.id, "typing")
        res = await asyncio.to_thread(publish.check, _channel())
        if not res.get("ok"):
            await m.answer(f"❌ {res.get('error', 'проверка не прошла')}")
            return
        lines = [f"✅ Аккаунт-публикатор: {res['account']}",
                 f"Premium: {'да' if res['premium'] else 'нет'} (лимит подписи {res['caption_limit']})"]
        if _channel():
            if res.get("channel"):
                lines.append(f"Канал «{res['channel']}» виден ✅")
            else:
                lines.append(f"⚠ Канал «{_channel()}» недоступен: {res.get('channel_error', '?')}\n"
                             "Добавь аккаунт-публикатор в канал админом с правом постить.")
        else:
            lines.append("⚠ PUBLISH_CHANNEL не задан в .env — публиковать некуда.")
        await m.answer("\n".join(lines))

    @dp.message(Command("discard"))
    async def _discard(m: Message) -> None:
        pending.pop(str(m.chat.id), None)
        _save(pending)
        await m.answer("Сбросил. Пришли новый текст и обложку, когда будешь готов.")

    @dp.message(Command("preview"))
    async def _preview(m: Message) -> None:
        st = _get(m.chat.id)
        if not st["text"]:
            await m.answer("Пусто — сначала пришли финальный текст поста.")
            return
        await m.answer("Так уйдёт в канал (текст — дословно):")
        if st["cover"] and Path(st["cover"]).exists():
            from aiogram.types import FSInputFile
            try:
                await m.answer_photo(FSInputFile(st["cover"]), caption="↑ обложка")
            except Exception:
                logging.exception("Не смог показать обложку в предпросмотре")
        await m.answer(st["text"][:publish.TEXT_LIMIT])
        await m.answer(_status(st["text"], st["cover"]))

    @dp.message(Command("publish"))
    async def _publish(m: Message) -> None:
        uid = m.chat.id
        st = _get(uid)
        if not st["text"]:
            await m.answer("Нечего публиковать — сначала пришли текст поста.")
            return
        if not _channel():
            await m.answer("⚠ PUBLISH_CHANNEL не задан в .env — некуда публиковать. Заполни и повтори.")
            return
        if uid in publishing:
            await m.answer("Уже публикую — секунду.")
            return
        publishing.add(uid)
        try:
            await m.bot.send_chat_action(uid, "typing")
            res = await asyncio.to_thread(publish.publish, _channel(), st["text"], st["cover"])
            if res.get("ok"):
                pending.pop(str(uid), None)
                _save(pending)
                await m.answer(f"✅ Опубликовано ({res.get('mode', '?')}).\n{res.get('link', '')}")
            else:
                await m.answer(f"❌ Не опубликовал: {res.get('error', 'неизвестная ошибка')}\n"
                               "Пост сохранён — поправь причину и снова /publish.")
        finally:
            publishing.discard(uid)

    @dp.message(F.photo)
    async def _photo(m: Message) -> None:
        photo = m.photo[-1]  # самый крупный размер
        dest = INCOMING / f"{photo.file_unique_id}.jpg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            await m.bot.download(photo, destination=dest)
        except Exception:
            logging.exception("Не смог скачать обложку")
            await m.answer("Не смог скачать картинку — пришли, пожалуйста, ещё раз.")
            return
        st = _get(m.chat.id)
        st["cover"] = str(dest)
        if (m.caption or "").strip():  # подпись к фото = текст поста (если прислали вместе)
            st["text"] = m.caption.strip()
        _save(pending)
        await m.answer("Обложку принял ✅\n\n" + _status(st["text"], st["cover"]))

    @dp.message(F.text)
    async def _text(m: Message) -> None:
        st = _get(m.chat.id)
        st["text"] = (m.text or "").strip()
        _save(pending)
        await m.answer("Текст принял ✅\n\n" + _status(st["text"], st["cover"]))

    bot = Bot(token)
    logging.info("Запускаю Публикатора (детерминированный, канал=%s, long_mode=%s)",
                 _channel() or "—", (config.get_optional("PUBLISH_LONG_MODE") or "preview"))
    await dp.start_polling(bot)
