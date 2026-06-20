"""Публикатор — бот, который ставит ОДОБРЕННЫЙ владельцем пост в нативные «отложенные» канала.

Намеренно ДЕТЕРМИНИРОВАННЫЙ: без LLM в цепочке публикации. Модель могла бы переписать пост или
«сама» опубликовать — а здесь пост должен попасть в канал РОВНО как одобрено, на слот из контент-плана,
и только по явной команде. Публикатор НЕ публикует вживую: он кладёт пост в отложенные канала и пишет
владельцу в ЛС, что готово. Живой контроль — у владельца в нативных отложенных (видит/правит/отменяет).
Это прямая реализация чек-листа безопасности (PLAN §6). Ключ Claude и agent_runtime не нужны.

Поток: Криейтор → владелец правит/одобряет → пересылает финал + обложку Публикатору → Публикатор
считает слот по контент-плану (memory/post_standard §«Ритм недели» через core.content_plan) →
ставит отложенный пост (MTProto) → пишет владельцу «готово, в отложенных на <слот>».

Команды: текст = финал; фото = обложка; /preview — что и КОГДА уйдёт; /schedule [флагман|короткий] —
поставить в отложенные; /check — проверить сессию и канал; /discard — сбросить; /start, /help — справка.

Запуск: python run_publisher.py   (нужны PUBLISHER_BOT_TOKEN, PUBLISH_CHANNEL, TELEGRAM_SESSION).
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import FSInputFile, Message

from connectors.telegram_publish import publish
from core import config, content_plan

logging.basicConfig(level=logging.INFO)

PENDING_FILE = config.ROOT / "data" / "publisher_pending.json"  # staged-пост (переживает рестарт), вне git
INCOMING = config.ROOT / "data" / "incoming"                    # сюда качаем присланную обложку

WELCOME = (
    "Я Публикатор. Ставлю ОДОБРЕННЫЙ тобой пост в отложенные канала на слот из контент-плана "
    "(ритм недели), через аккаунт-публикатор. Сам ничего не переписываю и вживую не публикую — "
    "Telegram отправит по расписанию, а ты видишь и правишь пост в отложенных канала.\n\n"
    "Как пользоваться:\n"
    "1) пришли ФИНАЛЬНЫЙ текст поста (сообщением или пересылкой от Криейтора);\n"
    "2) пришли ОБЛОЖКУ картинкой (если есть);\n"
    "3) /preview — покажу, что и КОГДА уйдёт; /schedule — поставлю в отложенные; /discard — сброшу.\n"
    "Формат беру по длине (длинный = флагман → Вт/Чт; короткий → Пн/Ср/Пт); переопределить: "
    "/schedule флагман  или  /schedule короткий.\n\n"
    "/check — проверю сессию и доступ к каналу. Текст уходит ДОСЛОВНО, без правок."
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


def _kind_from_arg(arg: str, text: str) -> str:
    """Формат: из явного аргумента команды (флагман/короткий) либо по длине текста."""
    a = (arg or "").strip().lower()
    if a.startswith(("флаг", "flag", "ф1")):
        return "flagship"
    if a.startswith(("корот", "short", "ф5", "лёг", "лег")):
        return "short"
    return content_plan.infer_kind(text)


def _predict_mode(text: str, cover: str | None) -> str:
    """Каким путём уйдёт пост (логика как в коннекторе) — для предпросмотра."""
    if not cover:
        return "только текст, одним сообщением"
    if len(text) <= publish._caption_limit():
        return "фото + подпись, одним сообщением"
    if (config.get_optional("PUBLISH_LONG_MODE") or "preview").lower() == "split":
        return "фото и текст РАЗДЕЛЬНО (два сообщения)"
    return "обложка крупным превью НАД текстом, одним сообщением"


async def _next_slot(kind: str) -> "object":
    """Ближайший слот формата с учётом уже занятых отложенными дат (читаем из канала)."""
    busy = set()
    try:
        times = await asyncio.to_thread(publish.scheduled_times, _channel())
        busy = {dt.astimezone(content_plan.tz()).date() for dt in times}
    except Exception:
        logging.exception("Не смог прочитать занятые слоты — считаю без них")
    return content_plan.next_slot(kind, busy_dates=busy)


def _status(text: str, cover: str | None) -> str:
    ch = _channel() or "⚠ PUBLISH_CHANNEL не задан в .env"
    if not text:
        return f"Канал: {ch}\nПока пусто — пришли финальный текст поста."
    n = len(text)
    kind = content_plan.infer_kind(text)
    head = text[:280] + ("…" if n > 280 else "")
    return (f"Канал: {ch}\n"
            f"Текст: {n} знаков{' ✅' if n <= publish.TEXT_LIMIT else ' ⚠ > 4096, не уйдёт одним сообщением'}\n"
            f"Обложка: {'есть ✅' if cover else 'нет'}\n"
            f"Формат (по длине): {content_plan.kind_label(kind)}\n"
            f"Уйдёт как: {_predict_mode(text, cover)}\n\n"
            f"Начало:\n{head}\n\n"
            f"/preview — слот и детали · /schedule — поставить в отложенные · /discard — сбросить")


async def main() -> None:
    token = config.get_secret("PUBLISHER_BOT_TOKEN")
    pending = _load()              # {chat_id(str): {text, cover}}
    scheduling: set[int] = set()   # чаты с идущей постановкой — защита от двойного тапа /schedule
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
                 f"Premium: {'да' if res['premium'] else 'нет'} (лимит подписи {res['caption_limit']})",
                 f"Часовой пояс плана: UTC{config.get_optional('PUBLISH_UTC_OFFSET') or '+3'}"]
        if _channel():
            if res.get("channel"):
                lines.append(f"Канал «{res['channel']}» виден ✅")
            else:
                lines.append(f"⚠ Канал «{_channel()}» недоступен: {res.get('channel_error', '?')}\n"
                             "Добавь аккаунт-публикатор в канал админом с правом постить.")
        else:
            lines.append("⚠ PUBLISH_CHANNEL не задан в .env — ставить некуда.")
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
        kind = content_plan.infer_kind(st["text"])
        slot = await _next_slot(kind)
        await m.answer("Так уйдёт в канал (текст — дословно):")
        if st["cover"] and Path(st["cover"]).exists():
            try:
                await m.answer_photo(FSInputFile(st["cover"]), caption="↑ обложка")
            except Exception:
                logging.exception("Не смог показать обложку в предпросмотре")
        await m.answer(st["text"][:publish.TEXT_LIMIT])
        await m.answer(_status(st["text"], st["cover"]) +
                       f"\n\n🗓 Слот по плану: {content_plan.kind_label(kind)} → "
                       f"{content_plan.human(slot)}. Поставить: /schedule")

    @dp.message(Command("schedule"))
    async def _schedule(m: Message, command: CommandObject) -> None:
        uid = m.chat.id
        st = _get(uid)
        if not st["text"]:
            await m.answer("Нечего ставить — сначала пришли текст поста.")
            return
        if not _channel():
            await m.answer("⚠ PUBLISH_CHANNEL не задан в .env — некуда ставить. Заполни и повтори.")
            return
        if uid in scheduling:
            await m.answer("Уже ставлю — секунду.")
            return
        scheduling.add(uid)
        try:
            await m.bot.send_chat_action(uid, "typing")
            kind = _kind_from_arg(command.args or "", st["text"])
            slot = await _next_slot(kind)
            res = await asyncio.to_thread(publish.publish, _channel(), st["text"], st["cover"], slot)
            if res.get("ok"):
                pending.pop(str(uid), None)
                _save(pending)
                await m.answer(f"✅ Готово. {content_plan.kind_label(kind)} поставлен в отложенные канала "
                               f"на {content_plan.human(slot)} (режим: {res.get('mode', '?')}).\n"
                               "Telegram отправит сам — проверь/поправь/отмени в «Отложенных» канала.")
            else:
                await m.answer(f"❌ Не поставил: {res.get('error', 'неизвестная ошибка')}\n"
                               "Пост сохранён — поправь причину и снова /schedule.")
        finally:
            scheduling.discard(uid)

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
    logging.info("Запускаю Публикатора (отложенные посты, канал=%s, tz=UTC%s, long_mode=%s)",
                 _channel() or "—", config.get_optional("PUBLISH_UTC_OFFSET") or "+3",
                 config.get_optional("PUBLISH_LONG_MODE") or "preview")
    await dp.start_polling(bot)
