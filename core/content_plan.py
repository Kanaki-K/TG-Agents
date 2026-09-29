"""Контент-план канала — КОГДА и ЧТО постим. Решает, на какой слот ставить готовый пост.

Зеркалит memory/post_standard.md §«Ритм недели» (решение 18.06.2026) — держать в синхроне с ним
(позже вынесем в отдельный структурированный файл-план и будем дополнять):
    Вт + Чт   → флагман (Ф1), выход 16:00
    Пн/Ср/Пт  → скоуп 🔭 «Под прицелом» (Ф5), выход 16:00
    Сб/Вс     → постов нет
Пост-стандарт задаёт ВРЕМЯ окном, не точкой, поэтому точное время и часовой пояс — в .env
(PUBLISH_TZ, PUBLISH_FLAGSHIP_TIME, PUBLISH_SHORT_TIME); тут — канон канала по умолчанию.

ДВА ФОРМАТА-ФОРМАТА, оба самостоятельные (26.08.2026): 'flagship' и 'scope'. Раньше второй звался
'short' — имя осталось СИНОНИМОМ (его знают `infer_kind`, Threads-пайплайн и .env-ключ
PUBLISH_SHORT_TIME), но канон теперь 'scope': автопилот включается по формату, и у формата должно
быть то же имя, каким владелец его зовёт («скоуп»), иначе панель и чат говорят на разных языках.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

from core import config, io_safe

# weekday(): Пн=0, Вт=1, Ср=2, Чт=3, Пт=4, Сб=5, Вс=6
FLAGSHIP_DAYS = (1, 3)            # Вторник, Четверг
SCOPE_DAYS = (0, 2, 4)            # Понедельник, Среда, Пятница
SHORT_DAYS = SCOPE_DAYS           # старое имя формата — синоним, см. шапку модуля
# Канал выходит в 16:00 по Франкфурту — ОБА формата. Дефолт кода держим равным реальности: раньше тут
# стояли 17:00/15:00 «по окну стандарта», и включённый автопилот увёл бы выход на час, если в .env
# опечатка (11.08 такое уже ловили — см. _slot_time). Дефолт, совпадающий с каноном, эту цену снимает.
DEFAULT_FLAGSHIP_TIME = (16, 0)
DEFAULT_SCOPE_TIME = (16, 0)
DEFAULT_SHORT_TIME = DEFAULT_SCOPE_TIME
DEFAULT_TZ = "Europe/Berlin"      # Франкфурт = Europe/Berlin; берётся, только если пояс нигде не задан
FLAGSHIP_MIN_CHARS = 1500        # длинный пост ⇒ флагман, короче ⇒ короткий (если формат не задан явно)

KINDS = ("flagship", "scope")     # оба формата автопилота, в порядке показа в панелях

# Слова, которыми формат зовут в коде И в живой речи владельца. Русские нужны потому, что имя формата
# приезжает от МОДЕЛИ из чата («включи автопилот для флагмана»), и промах тут — не косметика: он
# включил бы не тот формат. Флагман проверяем ПЕРВЫМ: у него слов меньше и они однозначнее.
_KIND_WORDS = {
    "flagship": ("flagship", "флагман", "ф1"),
    "scope": ("scope", "short", "скоуп", "скоп", "прицел", "коротк", "ф5", "🔭"),
}

RU_DOW = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def kind_words(kind: str) -> tuple:
    """Слова, которыми зовут формат (для разборщиков ввода). Один словарь имён на весь проект."""
    return _KIND_WORDS[norm_kind(kind)]


def norm_kind(kind, default: str = "scope") -> str:
    """Каноничное имя формата: 'short'/'короткий'/'скоуп' → 'scope', 'флагман' → 'flagship'.

    Одна точка нормализации на весь проект: иначе `days_for('short')` и `days_for('scope')` разъедутся,
    и владелец получит скоуп в два разных времени в зависимости от того, кто его позвал.

    ЛЕНИВАЯ намеренно (незнакомое → default): её зовут из внутренних мест, где сорванный формат не
    должен ронять план. Для ввода ИЗ ЧАТА есть строгий `schedule.parse_kinds` — он на незнакомом
    ругается, потому что там цена ошибки — включённый не тот автопилот.
    """
    k = str(kind or "").strip().lower().strip("«»\"'., ")
    if not k:
        return default
    for canon, words in _KIND_WORDS.items():
        if any(w in k for w in words):
            return canon
    return default

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


def _plan_value(key: str):
    """Настройка плана из чата с оглядкой на СТАРОЕ имя формата: 'scope_time' видит и 'short_time'.

    Нужна, потому что скоуп переименован из 'short' (26.08), а plan_settings.json на машине владельца
    мог уже накопить ключи под старым именем. Молча их потерять = расписание откатится к дефолту.
    """
    data = settings()
    v = data.get(key)
    if v in (None, "", []) and key.startswith("scope_"):
        v = data.get("short_" + key[len("scope_"):])
    return v


def source_of(key: str, env_key: str = "") -> str:
    """Откуда взято ЭФФЕКТИВНОЕ значение — «из чата» / «из .env» / «дефолт кода».

    Нужно, чтобы в /autopilot было видно ПОЧЕМУ выход в 16:00: сам поменял в чате, стоит в .env или
    так в коде. Без этого три источника = «почему стоит не то, что я думал».

    ВАЖНО: смотрим не «задано ли значение», а «взяли ли мы его». Опечатка в .env («16-00») даёт откат
    на дефолт — и панель обязана сказать «дефолт кода», иначе она врёт ровно там, где владелец ей верит.
    """
    if key.endswith("_time"):
        validate = _hhmm            # время должно РАЗБИРАТЬСЯ, иначе источник — не оно
    elif key == "tz":
        validate = zone             # пояс должен СУЩЕСТВОВАТЬ в базе, иначе мы взяли не его
    else:
        def validate(v):
            return v
    chat = _plan_value(key)
    if chat not in (None, "") and validate(chat):
        return "из чата"
    env_raw = config.get_optional(env_key) if env_key else ""
    if env_raw and validate(env_raw):
        return "из .env"
    bad = (chat not in (None, "")) or bool(env_raw)   # значение задано, но мы его НЕ взяли
    return "дефолт кода — заданное значение не разобрал!" if bad else "дефолт кода"


def zone(name):
    """ZoneInfo по имени пояса или None (нет базы/кривое имя). Не бросает — план не должен падать."""
    name = str(name or "").strip()
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 — нет tzdata или опечатка в имени: решает вызывающий
        return None


def tz_name() -> str:
    """Имя пояса, которое ДЕЙСТВУЕТ: правка из чата > PUBLISH_TZ > канон канала (Франкфурт).

    Пусто возвращаем ТОЛЬКО когда владелец явно задал голое смещение PUBLISH_UTC_OFFSET — тогда имени
    у пояса и правда нет. Раньше пусто было и в случае «не задано ничего», и план молча уезжал на
    +3 без перехода на летнее время: канал выходил бы на час не в то время полгода в году.
    """
    name = str(settings().get("tz") or "").strip() or config.get_optional("PUBLISH_TZ")
    if name:
        return name
    if str(config.get_optional("PUBLISH_UTC_OFFSET") or "").strip():
        return ""      # владелец выбрал смещение осознанно — не подменяем его каноном
    return DEFAULT_TZ


def tz():
    """Часовой пояс контент-плана.

    Приоритет — ИМЯ пояса (правка из чата → PUBLISH_TZ → канон DEFAULT_TZ; напр. Europe/Berlin):
    zoneinfo учитывает переход на летнее/зимнее время сам. Фолбэк — фиксированное смещение
    PUBLISH_UTC_OFFSET (без DST), и он же спасает, если в системе нет базы поясов (tzdata).
    """
    name = tz_name()
    if name:
        z = zone(name)
        if z is not None:
            return z
        logging.warning("[план] не смог взять пояс '%s' (нужен пакет tzdata?) — беру PUBLISH_UTC_OFFSET", name)
    try:
        off = float(config.get_optional("PUBLISH_UTC_OFFSET") or 3)
    except ValueError:
        off = 3.0
    return timezone(timedelta(hours=off))


def time_env_key(kind: str) -> str:
    """Ключ .env со временем выхода формата. У скоупа он исторически PUBLISH_SHORT_TIME — имя ключа
    НЕ меняем при переименовании формата: .env владельца уже настроен, и тихая смена ключа увела бы
    время на дефолт кода."""
    return "PUBLISH_FLAGSHIP_TIME" if norm_kind(kind) == "flagship" else "PUBLISH_SHORT_TIME"


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
    kind = norm_kind(kind)
    for value, where in ((_plan_value(f"{kind}_time"), "правке из чата"),
                         (config.get_optional(time_env_key(kind)), f".env ({time_env_key(kind)})")):
        if str(value or "").strip():
            t = _hhmm(value)
            if t:
                return t
            logging.warning("[план] время '%s' в %s не разобрал — беру дефолт кода. Формат: «16:00»",
                            value, where)
    h, m = DEFAULT_FLAGSHIP_TIME if kind == "flagship" else DEFAULT_SCOPE_TIME
    return time(h, m)


def slot_time(kind: str) -> time:
    """Время выхода формата (публичное имя для других модулей — автопилот/панель состояния)."""
    return _slot_time(kind)


def infer_kind(text: str) -> str:
    """Формат поста по длине: длинный ⇒ флагман (Ф1), короткий ⇒ короткий (Ф5)."""
    return "flagship" if len(text or "") >= FLAGSHIP_MIN_CHARS else "short"


def kind_label(kind: str) -> str:
    """Подпись формата для владельца. Скоуп зовём его именем — так же, как он зовёт его в чате."""
    return "флагман (Ф1)" if norm_kind(kind) == "flagship" else "скоуп 🔭 «Под прицелом» (короткий)"


def kind_word(kind: str) -> str:
    """Короткое имя формата для заголовков панелей и алертов («флагман» / «скоуп»)."""
    return "флагман" if norm_kind(kind) == "flagship" else "скоуп"


def days_for(kind: str) -> tuple:
    """Дни недели формата (weekday(): Пн=0). Один источник правды о ритме — план И автопилот.

    Владелец меняет ритм из чата (`plan_settings.json`); мусор в файле игнорируем и падаем на канон.
    """
    kind = norm_kind(kind)
    raw = _plan_value(f"{kind}_days")
    if isinstance(raw, list) and raw and all(isinstance(x, int) and 0 <= x <= 6 for x in raw):
        return tuple(sorted(set(raw)))
    if raw not in (None, "", []):   # значение есть, но кривое (правка файла руками) — не молчим
        logging.warning("[план] дни '%s' в plan_settings.json не разобрал — беру канон %s",
                        raw, "Вт/Чт" if kind == "flagship" else "Пн/Ср/Пт")
    return FLAGSHIP_DAYS if kind == "flagship" else SCOPE_DAYS


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
    """Пояс плана с РЕАЛЬНЫМ текущим смещением — чтобы видеть, подхватился ли заданный пояс.
    Напр. «Europe/Berlin (сейчас UTC+02:00)» либо «UTC+03:00» (фолбэк на смещение)."""
    name = tz_name()   # действующее имя: правка из чата > PUBLISH_TZ
    try:
        off = datetime.now(tz()).utcoffset() or timedelta(0)
        secs = off.total_seconds()
        sign = "+" if secs >= 0 else "-"
        h, m = divmod(int(abs(secs)) // 60, 60)
        cur = f"UTC{sign}{h:02d}:{m:02d}"
    except Exception:
        cur = "UTC?"
    return f"{name} (сейчас {cur})" if name else cur
