"""Контент-план канала — КОГДА и ЧТО постим. Решает, на какой слот ставить готовый пост.

Зеркалит memory/post_standard.md §«Ритм недели» (решение 18.06.2026) — держать в синхроне с ним
(позже вынесем в отдельный структурированный файл-план и будем дополнять):
    Вт + Чт   → флагман (Ф1), окно 16–19:00
    Пн/Ср/Пт  → короткий (Ф5), окно 14–19:00
    Сб/Вс     → постов нет
Пост-стандарт задаёт ВРЕМЯ окном, не точкой, поэтому точное время и часовой пояс — в .env
(PUBLISH_UTC_OFFSET, PUBLISH_FLAGSHIP_TIME, PUBLISH_SHORT_TIME); тут — разумные значения по умолчанию.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

from core import config, io_safe

# weekday(): Пн=0, Вт=1, Ср=2, Чт=3, Пт=4, Сб=5, Вс=6
FLAGSHIP_DAYS = (1, 3)            # Вторник, Четверг
SHORT_DAYS = (0, 2, 4)           # Понедельник, Среда, Пятница
DEFAULT_FLAGSHIP_TIME = (17, 0)   # в окне 16–19:00
DEFAULT_SHORT_TIME = (15, 0)      # в окне 14–19:00
FLAGSHIP_MIN_CHARS = 1500        # длинный пост ⇒ флагман, короче ⇒ короткий (если формат не задан явно)

RU_DOW = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

# Живые настройки плана — то, что владелец меняет ИЗ ЧАТА с Криейтором (бот пишет сюда).
# ПРИОРИТЕТ: этот файл > .env > дефолт в коде.
# Почему файл, а не .env: .env — секреты, ботам его правка запрещена (хук + deny), и там нет пометки
# «кто и когда поменял». Тут же лежит `updated`/`updated_by` — видно, что это правка из чата.
SETTINGS_FILE = config.ROOT / "data" / "plan_settings.json"


def settings() -> dict:
    """Настройки плана с диска. Битый/пустой файл → {} (io_safe, AUDIT N-10) — план не падает."""
    data = io_safe.load_json(SETTINGS_FILE, {})
    return data if isinstance(data, dict) else {}


def save_settings(data: dict) -> None:
    """Записать настройки плана (полный словарь). Бросает — вызывающий обязан сообщить владельцу.

    Атомарно (io_safe.dump_json): обрыв на середине записи оставил бы битый JSON, а битый читается как
    «настроек нет» — расписание владельца молча вернулось бы к дефолту. Тут это цена ошибки.
    """
    io_safe.dump_json(SETTINGS_FILE, data)


def source_of(key: str, env_key: str = "") -> str:
    """Откуда взято ЭФФЕКТИВНОЕ значение — «из чата» / «из .env» / «дефолт кода».

    Нужно, чтобы в /autopilot было видно ПОЧЕМУ выход в 16:00: сам поменял в чате, стоит в .env или
    так в коде. Без этого три источника = «почему стоит не то, что я думал».

    ВАЖНО: смотрим не «задано ли значение», а «взяли ли мы его». Опечатка в .env («16-00») даёт откат
    на дефолт — и панель обязана сказать «дефолт кода», иначе она врёт ровно там, где владелец ей верит.
    """
    validate = _hhmm if key.endswith("_time") else (lambda v: v)   # для времени проверяем разбор
    chat = settings().get(key)
    if chat not in (None, "") and validate(chat):
        return "из чата"
    env_raw = config.get_optional(env_key) if env_key else ""
    if env_raw and validate(env_raw):
        return "из .env"
    bad = (chat not in (None, "")) or bool(env_raw)   # значение задано, но мы его НЕ взяли
    return "дефолт кода — заданное значение не разобрал!" if bad else "дефолт кода"


def tz():
    """Часовой пояс контент-плана.

    Приоритет — ИМЯ пояса PUBLISH_TZ (напр. Europe/Berlin): zoneinfo учитывает переход на летнее/
    зимнее время сам. Фолбэк — фиксированное смещение PUBLISH_UTC_OFFSET (по умолч. +3, без DST).
    """
    name = config.get_optional("PUBLISH_TZ")
    if name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except Exception:  # нет zoneinfo/tzdata или кривое имя — откатываемся на смещение
            logging.warning("[план] не смог взять пояс '%s' (нужен пакет tzdata?) — беру PUBLISH_UTC_OFFSET", name)
    try:
        off = float(config.get_optional("PUBLISH_UTC_OFFSET") or 3)
    except ValueError:
        off = 3.0
    return timezone(timedelta(hours=off))


def time_env_key(kind: str) -> str:
    return "PUBLISH_FLAGSHIP_TIME" if kind == "flagship" else "PUBLISH_SHORT_TIME"


def _hhmm(raw: str):
    """«16:00» → time(16, 0). Непонятное → None (мусор в .env не должен ронять план)."""
    raw = str(raw or "").strip()
    if not raw or ":" not in raw:
        return None
    try:
        h, m = raw.split(":")[:2]
        return time(int(h), int(m))
    except ValueError:
        return None


def _slot_time(kind: str) -> time:
    """Время выхода: правка из чата > .env > дефолт кода. Неразобранное значение — ГРОМКО в лог.

    Молчать нельзя (нашёл на аудите 11.08): при опечатке в .env («16-00») время тихо становилось
    дефолтным, а панель /autopilot честно писала «из .env» — владелец видел бы 17:00 и не понимал, почему.
    """
    for value, where in ((settings().get(f"{kind}_time"), "правке из чата"),
                         (config.get_optional(time_env_key(kind)), f".env ({time_env_key(kind)})")):
        if str(value or "").strip():
            t = _hhmm(value)
            if t:
                return t
            logging.warning("[план] время '%s' в %s не разобрал — беру дефолт кода. Формат: «16:00»",
                            value, where)
    h, m = DEFAULT_FLAGSHIP_TIME if kind == "flagship" else DEFAULT_SHORT_TIME
    return time(h, m)


def slot_time(kind: str) -> time:
    """Время выхода формата (публичное имя для других модулей — автопилот/панель состояния)."""
    return _slot_time(kind)


def infer_kind(text: str) -> str:
    """Формат поста по длине: длинный ⇒ флагман (Ф1), короткий ⇒ короткий (Ф5)."""
    return "flagship" if len(text or "") >= FLAGSHIP_MIN_CHARS else "short"


def kind_label(kind: str) -> str:
    return "флагман (Ф1)" if kind == "flagship" else "короткий (Ф5)"


def days_for(kind: str) -> tuple:
    """Дни недели формата (weekday(): Пн=0). Один источник правды о ритме — план И автопилот.

    Владелец меняет ритм из чата (`plan_settings.json`); мусор в файле игнорируем и падаем на канон.
    """
    raw = settings().get(f"{kind}_days")
    if isinstance(raw, list) and raw and all(isinstance(x, int) and 0 <= x <= 6 for x in raw):
        return tuple(sorted(set(raw)))
    if raw not in (None, "", []):   # значение есть, но кривое (правка файла руками) — не молчим
        logging.warning("[план] дни '%s' в plan_settings.json не разобрал — беру канон %s",
                        raw, "Вт/Чт" if kind == "flagship" else "Пн/Ср/Пт")
    return FLAGSHIP_DAYS if kind == "flagship" else SHORT_DAYS


def slot_on(d, kind: str) -> datetime | None:
    """Слот КОНКРЕТНОГО дня (tz-aware) или None, если в этот день формат не выходит.

    Нужен автопилоту (core/schedule): его вопрос — «во сколько выход СЕГОДНЯ», а next_slot отвечает
    на другой — «какой слот следующий» (тот может уехать на другой день, и автопилот запустил бы
    прогон не в свой день).
    """
    if d.weekday() not in days_for(kind):
        return None
    return datetime.combine(d, _slot_time(kind), tz())


def next_slot(kind: str, *, now: datetime | None = None, busy_dates: set | None = None) -> datetime:
    """Ближайший подходящий слот для формата по ритму недели (tz-aware datetime).

    busy_dates — даты (date), на которые уже стоит отложенный пост: пропускаем (не сдваиваем день).
    Ищем вперёд до 3 недель; если ничего — фолбэк через неделю в тот же слот.
    """
    z = tz()
    now = (now or datetime.now(z)).astimezone(z)
    days = days_for(kind)   # не константа: ритм владелец меняет из чата (см. days_for/settings)
    t = _slot_time(kind)
    busy_dates = busy_dates or set()
    for ahead in range(0, 21):
        d = (now + timedelta(days=ahead)).date()
        if d.weekday() not in days or d in busy_dates:
            continue
        cand = datetime.combine(d, t, z)
        if cand <= now + timedelta(minutes=5):   # в прошлом / слишком близко — берём следующий день
            continue
        return cand
    return datetime.combine((now + timedelta(days=7)).date(), t, z)


def human(dt: datetime) -> str:
    """Человекочитаемый слот: «Чт 26.06 17:00»."""
    return f"{RU_DOW[dt.weekday()]} {dt:%d.%m %H:%M}"


def tz_label() -> str:
    """Пояс плана с РЕАЛЬНЫМ текущим смещением — чтобы видеть, подхватился ли PUBLISH_TZ.
    Напр. «Europe/Berlin (сейчас UTC+02:00)» либо «UTC+03:00» (фолбэк на смещение)."""
    name = config.get_optional("PUBLISH_TZ")
    try:
        off = datetime.now(tz()).utcoffset() or timedelta(0)
        secs = off.total_seconds()
        sign = "+" if secs >= 0 else "-"
        h, m = divmod(int(abs(secs)) // 60, 60)
        cur = f"UTC{sign}{h:02d}:{m:02d}"
    except Exception:
        cur = "UTC?"
    return f"{name} (сейчас {cur})" if name else cur
