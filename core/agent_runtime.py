"""Общий рантайм агента: aiogram-бот + цикл Claude с инструментами.

Один и тот же движок крутит любого агента — отличается только:
  - какой агент загружен (config.yaml + SKILL.md);
  - какие у него инструменты (tools_schema/dispatch);
  - как собирается системный контекст (system_builder);
  - приветствие и пресет-команды.

Слэш-команды реализованы как «пресет-промпты»: /report просто шлёт модели
заранее заданный запрос — модель сама дёргает нужные инструменты.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from pathlib import Path
from typing import Callable

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import FSInputFile, LinkPreviewOptions, Message

from core import config, llm, tg_format

logging.basicConfig(level=logging.INFO)


# --- Простой планировщик: запускать пресет раз в N дней и слать владельцу в чат ---
# Состояние (дата прошлого прогона) и chat_id владельца лежат в data/ (вне git).
def _read_owner(path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip()) if path.exists() else None
    except Exception:
        return None


def _write_owner(path, chat_id: int) -> None:
    try:
        path.parent.mkdir(exist_ok=True)
        path.write_text(str(chat_id), encoding="utf-8")
    except Exception:
        logging.exception("Не смог сохранить chat владельца")


def _read_run_date(path):
    try:
        if path.exists():
            return date.fromisoformat(json.loads(path.read_text(encoding="utf-8"))["last"])
    except Exception:
        pass
    return None


def _write_run_date(path, d: date) -> None:
    try:
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"last": d.isoformat()}), encoding="utf-8")
    except Exception:
        logging.exception("Не смог записать дату прогона")


async def _periodic_loop(bot, agent_name, spec, model, system_builder,
                         tools_schema, dispatch, api_key, thinking=None) -> None:
    """Раз в spec['days'] дней гоняет spec['preset'] и шлёт результат владельцу.

    Перезапуск-устойчиво: дату прошлого прогона храним в файле, проверяем раз в час.
    Пока владелец ни разу не написал боту — не знаем chat_id, тихо ждём.
    """
    data_dir = config.ROOT / "data"
    state_file = data_dir / f"{agent_name}_{spec['key']}.json"
    owner_file = data_dir / f"{agent_name}_owner.txt"
    while True:
        await asyncio.sleep(spec.get("check_every", 3600))
        try:
            chat_id = _read_owner(owner_file)
            if not chat_id:
                continue
            last = _read_run_date(state_file)
            today = date.today()
            if last and (today - last).days < spec["days"]:
                continue
            logging.info("Периодический прогон '%s' агента %s", spec["key"], agent_name)
            text, _ = await asyncio.to_thread(
                llm.reply, model, system_builder(), [], spec["preset"],
                tools_schema, dispatch, api_key, thinking)
            for chunk in _chunks((spec.get("header", "") + (text or "…")).strip()):
                try:
                    await bot.send_message(chat_id, tg_format.strip_markdown(chunk)[:TG_LIMIT])
                except Exception:
                    logging.exception("Не смог отправить периодический отчёт")
            _write_run_date(state_file, today)
        except Exception:
            logging.exception("Периодический прогон не удался")


def _trim_history(hist: list, keep: int = 12) -> list:
    """Короткий хвост диалога, но обязательно начинающийся с «настоящего»
    хода пользователя (роль user + строковый content).

    Просто `hist[-keep:]` опасен: срез может попасть между `tool_use` и его
    `tool_result`, и тогда первым сообщением окажется `tool_result` без парного
    `tool_use` — Anthropic API отклоняет это с ошибкой 400. Поэтому после среза
    отбрасываем ведущие сообщения (assistant-ходы и блоки tool_result), пока в
    начале не окажется обычная реплика пользователя.
    """
    tail = hist[-keep:]
    while tail and not (tail[0].get("role") == "user"
                        and isinstance(tail[0].get("content"), str)):
        tail = tail[1:]
    return tail


TG_LIMIT = 4096          # жёсткий лимит Telegram на длину сообщения
CHUNK = 3900             # режем с запасом под HTML-теги жирного (<b>…</b>): 3900 источника + теги ≈ <4096.
                         # Подняли с 3500, чтобы флагман-драфт (идеал 3000–3800) приходил ОДНИМ сообщением,
                         # а не рвался (из-за чего хвост читался как «дописала ИИ»).
SPLIT_MARK = "[[SPLIT]]" # агент ставит этот маркер, чтобы разбить ответ на ОТДЕЛЬНЫЕ сообщения
# Превью ссылок ВЫКЛЮЧЕНО на всех ответах: в постах есть футер-ссылки (Канал/Медиа/Notion/…),
# и Telegram иначе цепляет к сообщению уродливую карточку-превью первой ссылки. Владелец и руками
# превью отключает — бот делает так же по умолчанию.
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def _chunks(text: str, size: int = CHUNK) -> list[str]:
    """Разбить длинный текст на куски ≤ size, по границам строк (не рвём слова/теги).

    Очень длинную одиночную строку (напр. гигантский URL) режем жёстко.
    """
    out: list[str] = []
    cur = ""
    for line in text.split("\n"):
        while len(line) > size:                 # одиночная строка длиннее куска
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:size])
            line = line[size:]
        if cur and len(cur) + 1 + len(line) > size:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out or [text]


async def _send(m: Message, text: str, *, custom_emoji: bool = False) -> None:
    """Отправить ответ модели как Telegram-HTML, разбив длинный текст на части.

    Telegram режет сообщения на 4096 символов — длинные ответы шлём кусками.
    На каждый кусок: пробуем HTML; если разметка кривая (400) — шлём чистым
    текстом, чтобы ответ дошёл, а бот не упал.
    custom_emoji — подставлять ли кастомные эмодзи (только агенты с флагом).
    """
    parts = [p.strip() for p in text.split(SPLIT_MARK)] if SPLIT_MARK in text else [text]
    for part in parts:
        if not part:
            continue
        for chunk in _chunks(part):
            try:
                await m.answer(tg_format.to_telegram_html(chunk, custom_emoji=custom_emoji),
                               parse_mode="HTML", link_preview_options=NO_PREVIEW)
            except TelegramBadRequest as e:
                # Частая причина отказа — бот не вправе слать кастом-эмодзи (нет Telegram
                # Premium у ВЛАДЕЛЬЦА бота либо нет Fragment-username): Telegram отвергает
                # <tg-emoji>. Логируем реальную причину и пробуем без кастома — так
                # сохраняем жирный/ссылки, а не рушим всё форматирование в plain-text.
                logging.warning("Telegram отклонил HTML (%s) — повтор без кастом-эмодзи", e)
                if custom_emoji:
                    try:
                        await m.answer(tg_format.to_telegram_html(chunk, custom_emoji=False),
                                       parse_mode="HTML", link_preview_options=NO_PREVIEW)
                        continue
                    except TelegramBadRequest as e2:
                        logging.warning("HTML отклонён и без кастома (%s) — шлю чистым текстом", e2)
                await m.answer(tg_format.strip_markdown(chunk)[:TG_LIMIT], link_preview_options=NO_PREVIEW)


def _clear_outbox(outbox: Path | None) -> None:
    """Сбросить аутбокс ПЕРЕД ходом — чтобы отправить только картинки этого хода, не старьё."""
    if outbox and outbox.exists():
        try:
            outbox.unlink()
        except Exception:
            logging.exception("Не смог очистить медиа-аутбокс")


CAPTION_LIMIT = 1024   # лимит Telegram на подпись к фото (sendPhoto caption)
TEXT_LIMIT = 4096      # лимит Telegram на текстовое сообщение (и превью-картинка над ним)


def _pop_outbox_image(outbox: Path | None) -> str | None:
    """Достать путь к картинке, что инструмент сложил за этот ход, и очистить аутбокс.

    Возвращает последнюю существующую картинку (или None). Инструменты умеют возвращать
    только текст — путь к PNG пишется в файл-аутбокс, а отправляет картинку рантайм.
    """
    if not outbox or not outbox.exists():
        return None
    try:
        paths = [ln.strip() for ln in outbox.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except Exception:
        paths = []
    try:
        outbox.unlink()
    except Exception:
        logging.exception("Не смог очистить медиа-аутбокс")
    for p in reversed(paths):           # последняя картинка хода
        if Path(p).exists():
            return p
        logging.warning("Картинки из аутбокса нет на диске: %s", p)
    return None


async def _upload_image(path: Path) -> str | None:
    """Залить картинку и вернуть ПРЯМОЙ публичный URL — для «обложки над текстом» у длинных постов.

    Длинный пост (>1024) в подпись к фото не влезает, поэтому картинку показываем крупным превью
    ссылки над текстом — а превью Telegram тянет только по публичному URL. Основной хост —
    telegra.ph (инфраструктура самого Telegram: прямой линк, доступен везде, где работает Telegram,
    не режется как внешние сервисы); фолбэк — catbox. Не вышло нигде — None (откат на 2 сообщения).
    """
    try:
        import aiohttp

        data = aiohttp.FormData()
        data.add_field("file", path.read_bytes(), filename=path.name, content_type="image/png")
        async with aiohttp.ClientSession() as s:
            async with s.post("https://telegra.ph/upload", data=data,
                              timeout=aiohttp.ClientTimeout(total=60)) as r:
                j = await r.json(content_type=None)
                if isinstance(j, list) and j and j[0].get("src"):
                    return "https://telegra.ph" + j[0]["src"]
    except Exception:
        logging.exception("telegra.ph upload не вышел — пробую catbox")
    try:
        import aiohttp

        data = aiohttp.FormData()
        data.add_field("reqtype", "fileupload")
        data.add_field("fileToUpload", path.read_bytes(),
                       filename=path.name, content_type="image/png")
        async with aiohttp.ClientSession() as s:
            async with s.post("https://catbox.moe/user/api.php", data=data,
                              timeout=aiohttp.ClientTimeout(total=60)) as r:
                url = (await r.text()).strip()
                return url if url.startswith("http") else None
    except Exception:
        logging.exception("Не смог залить обложку (catbox тоже)")
        return None


async def _cover_public_url(m: Message, img: str, cover_url: str | None) -> str | None:
    """Публичный URL обложки для «превью над текстом». Сначала заливаем на telegra.ph/catbox
    (прямой линк, надёжно рендерится превью), и лишь в крайнем случае — URL присланного фото
    в самом Telegram. None — доставка откатится на фото+текст раздельно.
    """
    return await _upload_image(Path(img)) or cover_url


async def _send_with_cover(m: Message, text: str, img: str, *,
                           custom_emoji: bool, cover_url: str | None = None) -> bool:
    """Прислать ОДНИМ сообщением: фото+подпись (если текст ≤1024) либо обложка крупным превью
    над текстом (если длиннее). Картинка всегда СВЕРХУ. True — если ушло одним сообщением.
    """
    vis = len(tg_format.strip_markdown(text))   # длина ПОСЛЕ парсинга (без markdown-маркеров)
    logging.info("[обложка] есть картинка; длина поста=%d (лимит подписи=%d)", vis, CAPTION_LIMIT)
    html = tg_format.to_telegram_html(text, custom_emoji=custom_emoji)
    if vis <= CAPTION_LIMIT:                      # короткий пост → фото + подпись (картинка сверху)
        logging.info("[обложка] путь: фото+подпись, одним сообщением")
        await m.answer_photo(FSInputFile(img), caption=html, parse_mode="HTML")
        return True
    if vis <= TEXT_LIMIT:                          # длинный → обложка превью над текстом
        url = await _cover_public_url(m, img, cover_url)
        logging.info("[обложка] путь: превью над текстом; URL обложки=%s", url)
        if url:
            await m.answer(html, parse_mode="HTML", link_preview_options=LinkPreviewOptions(
                url=url, prefer_large_media=True, show_above_text=True))
            logging.info("[обложка] отправлено одним сообщением (превью над текстом)")
            return True
    logging.warning("[обложка] одним сообщением НЕ вышло (URL пуст или текст >4096) — будет откат")
    return False


async def _save_incoming_photo(m: Message) -> str:
    """Скачать самое крупное присланное владельцем фото в data/incoming/ и вернуть путь к файлу."""
    photo = m.photo[-1]  # последний размер в списке = самый крупный
    dest = config.ROOT / "data" / "incoming" / f"{photo.file_unique_id}.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    await m.bot.download(photo, destination=dest)
    return str(dest)


async def _deliver(m: Message, text: str, outbox: Path | None, *, custom_emoji: bool,
                   cover: str | None = None, cover_url: str | None = None) -> None:
    """Выдать ответ. Обложка берётся из cover (присланной владельцем картинки) ИЛИ из аутбокса
    (сгенерированной make_image); если есть — слать её и пост ОДНИМ сообщением, иначе обычный текст.
    cover_url — готовый публичный URL обложки (для присланного фото — URL самого Telegram).
    При любом сбое «одного сообщения» — откат на фото+текст раздельно (не хуже старого).
    """
    img = cover or _pop_outbox_image(outbox)
    if not img:
        await _send(m, text, custom_emoji=custom_emoji)
        return
    try:
        if await _send_with_cover(m, text, img, custom_emoji=custom_emoji, cover_url=cover_url):
            return
    except Exception:
        logging.exception("Одним сообщением не вышло — шлю фото и текст раздельно")
    try:
        await m.answer_photo(FSInputFile(img))    # запасной путь: фото…
    except Exception:
        logging.exception("Не смог отправить картинку %s", img)
    await _send(m, text, custom_emoji=custom_emoji)  # …и текст отдельно


async def run(
    agent_name: str,
    *,
    tools_schema: list[dict],
    dispatch: Callable[[str, dict], str],
    system_builder: Callable[[], str],
    welcome: str,
    commands: dict[str, str] | None = None,
    periodic: dict | list | None = None,  # один спец или список (несколько плановых задач)
    thinking: dict | None = None,         # конфиг мышления модели (напр. {"type": "adaptive"})
    media_outbox: Path | None = None,     # файл-аутбокс картинок (агенты с «руками»-рендером); None = нет
) -> None:
    agent = config.load_agent(agent_name)
    model = agent["model"]
    api_key = config.agent_api_key(agent)   # свой ключ агента или общий
    commands = commands or {}
    render_emoji = bool(agent.get("custom_emoji"))  # кастом-эмодзи только у агентов с custom_emoji: true
    history: dict[int, list] = {}   # короткий хвост диалога по пользователю
    busy: set[int] = set()          # пользователи с уже идущим запросом (защита от параллельного дубля)
    owner_file = config.ROOT / "data" / f"{agent_name}_owner.txt"  # куда слать проактивные отчёты
    dp = Dispatcher()

    async def _turn(m: Message, user_text: str, cover: str | None = None,
                    cover_url: str | None = None) -> None:
        uid = m.from_user.id
        _write_owner(owner_file, m.chat.id)  # запоминаем чат для проактивных (еженедельных) отчётов
        # пустой/не-текстовый ввод не шлём в модель: Anthropic отклоняет пустой
        # user-content (400), да и отвечать не на что. Голос/фото — позже.
        if not (user_text or "").strip():
            await m.answer("Пока понимаю только текст — пришли, пожалуйста, сообщением.")
            return
        # один запрос на пользователя за раз: aiogram обрабатывает апдейты параллельно,
        # а долгий /scan (инструменты + веб-поиск) при повторном тапе запускался дважды
        # — два отчёта и порча общей истории. Пока занят — просим подождать.
        if uid in busy:
            await m.answer("Ещё думаю над прошлым запросом — секунду, отвечу по нему.")
            return
        busy.add(uid)
        try:
            await m.bot.send_chat_action(m.chat.id, "typing")
            _clear_outbox(media_outbox)  # только картинки ЭТОГО хода, без старья от прошлого
            # на входе чиним возможный «обрыв» tool_use/tool_result (лечит и старое состояние),
            prior = _trim_history(history.get(uid, []))
            text, hist = await asyncio.to_thread(
                llm.reply, model, system_builder(), prior,
                user_text, tools_schema, dispatch, api_key, thinking,
            )
            history[uid] = _trim_history(hist)
            await _deliver(m, text or "…", media_outbox, custom_emoji=render_emoji,
                           cover=cover, cover_url=cover_url)
        finally:
            busy.discard(uid)

    @dp.message(Command("start"))
    async def _start(m: Message) -> None:
        _write_owner(owner_file, m.chat.id)
        await m.answer(welcome)

    # пресет-команды: /<cmd> → заранее заданный промпт модели
    def _make_preset(preset: str):
        async def handler(m: Message) -> None:
            await _turn(m, preset)
        return handler

    for cmd, preset in commands.items():
        dp.message(Command(cmd))(_make_preset(preset))

    if media_outbox is not None:  # агенты с «руками»-картинками умеют принять фото от владельца
        @dp.message(F.photo)
        async def _photo(m: Message) -> None:
            # присланное фото = готовая обложка; склеим её с постом одним сообщением (картинка сверху).
            try:
                cover = await _save_incoming_photo(m)
            except Exception:
                logging.exception("Не смог скачать присланное фото")
                await m.answer("Не смог скачать картинку — пришли, пожалуйста, ещё раз.")
                return
            cover_url = None  # URL самого Telegram — для «превью над текстом» у длинных постов (надёжно)
            try:
                f = await m.bot.get_file(m.photo[-1].file_id)
                cover_url = f"https://api.telegram.org/file/bot{m.bot.token}/{f.file_path}"
            except Exception:
                logging.exception("Не смог получить telegram-URL присланного фото")
            caption = (m.caption or "").strip()
            base = caption or "(подписи к фото нет — текст поста возьми из последнего поста в нашем диалоге)"
            instruction = (
                f"{base}\n\n"
                "[Система: к твоему ответу УЖЕ прикреплена присланная владельцем картинка — она уйдёт "
                "обложкой СВЕРХУ одним сообщением с твоим текстом. Выведи ТОЛЬКО финальный пост, готовый "
                "к публикации: без меты, без слов про картинку, без заметок и вопросов, не повторяй дважды.]"
            )
            await _turn(m, instruction, cover=cover)

    @dp.message()
    async def _chat(m: Message) -> None:
        await _turn(m, m.text or "")

    bot = Bot(config.get_secret(agent["token_env"]))
    logging.info("Запускаю агента '%s' (модель %s)", agent_name, model)
    if media_outbox is not None:  # маркер версии: видно в логе ТОЛЬКО на новом коде доставки
        stub = config.get_optional("GPT_IMAGE_STUB").strip()
        logging.info("Доставка обложки: пост+картинка ОДНИМ сообщением [build:onemsg]%s",
                     " | GPT_IMAGE_STUB ВКЛ (готовая картинка, без ChatGPT)" if stub else "")
    specs = periodic if isinstance(periodic, list) else [periodic] if periodic else []
    for spec in specs:
        asyncio.create_task(_periodic_loop(
            bot, agent_name, spec, model, system_builder,
            tools_schema, dispatch, api_key, thinking))
        logging.info("Планировщик '%s' включён: раз в %s дн.", spec.get("key"), spec.get("days"))
    await dp.start_polling(bot)
