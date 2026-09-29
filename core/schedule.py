"""Автопилот: КОГДА завод запускается сам — и когда НЕ запускается.

Зачем отдельным модулем: «пора или нет» — чистая функция от времени и состояния на диске, поэтому
покрывается тестами БЕЗ реального прогона (прогон = деньги + публикация в канал). `run_autopilot.py`
только исполняет вердикт и умеет о нём рассказать.

Ритм недели тут НЕ дублируется: дни и время выхода берём из `core/content_plan` (Вт/Чт,
`PUBLISH_FLAGSHIP_TIME`, `PUBLISH_TZ`). Здесь — только окно старта, метка «сегодня уже гоняли»
и предохранители. Полное объяснение для владельца — в `docs/AUTOPILOT.md`.

ГЛАВНЫЙ предохранитель — файлы-выключатели `data/autopilot_on_<формат>` (по образцу
`data/threads_unlocked`): нет файла → этот формат НИЧЕГО не делает. Удалить файл = мгновенно
остановить, .env не трогая.

ФОРМАТЫ НЕЗАВИСИМЫ (26.08.2026): у флагмана и скоупа свой выключатель, своё расписание и своя метка
«сегодня гоняли». Так и было задумано владельцем: скоуп может законно не выйти (нет свежего повода),
и одна неудачная неделя со скоупом не должна быть поводом гасить флагман — а с общим рубильником
выбора бы не было.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from core import config, content_plan, io_safe, runmode

log = logging.getLogger(__name__)

STATE_FILE = config.ROOT / "data" / "autopilot_state.json"   # что и когда гоняли (переживает перезапуск)
SWITCH_DIR = config.ROOT / "data"        # где живут файлы-выключатели (тесты подменяют на tmp_path)

DEFAULT_LEAD_HOURS = 4.0       # за сколько часов до слота стартуем (флагману повод не нужен — можно с утра)
DEFAULT_MARGIN_MINUTES = 60    # ближе этого к слоту не начинаем: прогон (~10-20 мин) должен успеть
DEFAULT_CHECK_EVERY = 600      # пауза между проверками в режиме --daemon, сек

_UNSET = object()               # «параметр не передан» ≠ «передан None» (None значит «неизвестно»)


def _num(key: str, env_key: str, default: float) -> float:
    """Число из настроек: правка ИЗ ЧАТА (plan_settings.json) > .env > дефолт кода."""
    raw = content_plan.settings().get(key)
    if raw in (None, ""):
        raw = config.get_optional(env_key)
    if raw in (None, ""):
        return default
    try:
        return float(str(raw).replace(",", "."))
    except ValueError:
        log.warning("[автопилот] %s='%s' не число — беру %s", key, raw, default)
        return default


def lead_hours() -> float:
    return _num("lead_hours", "AUTOPILOT_LEAD_HOURS", DEFAULT_LEAD_HOURS)


def margin_minutes() -> float:
    return _num("margin_minutes", "AUTOPILOT_MARGIN_MINUTES", DEFAULT_MARGIN_MINUTES)


def check_every() -> float:
    return _num("check_every", "AUTOPILOT_CHECK_EVERY", DEFAULT_CHECK_EVERY)


def on_file(kind: str):
    """Файл-выключатель ФОРМАТА: data/autopilot_on_flagship | data/autopilot_on_scope."""
    return SWITCH_DIR / f"autopilot_on_{content_plan.norm_kind(kind)}"


def legacy_on_file():
    """Старый ОБЩИЙ выключатель `data/autopilot_on` — до разделения форматов (11.08–26.08.2026)."""
    return SWITCH_DIR / "autopilot_on"


def enabled(kind: str = "flagship") -> bool:
    """Включён ли автопилот для формата. Выключатель — ФАЙЛ (не .env): убирается одним движением.

    Старый общий `data/autopilot_on` читаем как «флагман включён»: он описан в docs/AUTOPILOT.md как
    стоп-кран, и владелец мог создать его руками до разделения форматов. Молча его игнорировать
    значило бы «включил по инструкции, а оно не работает».
    """
    kind = content_plan.norm_kind(kind)
    return on_file(kind).exists() or (kind == "flagship" and legacy_on_file().exists())


def enabled_kinds() -> list:
    """Форматы, которым сейчас разрешено запускаться самим (в порядке content_plan.KINDS)."""
    return [k for k in content_plan.KINDS if enabled(k)]


def any_enabled() -> bool:
    """Нужен ли вообще будильник в ОС: хоть один формат включён."""
    return bool(enabled_kinds())


def turn_on(kind: str = "flagship", reason: str = "") -> None:
    """Включить автопилот ФОРМАТА (создать его файл-выключатель). Причина остаётся в файле — как у Threads."""
    kind = content_plan.norm_kind(kind)
    f = on_file(kind)
    f.parent.mkdir(exist_ok=True)
    stamp = datetime.now(content_plan.tz()).isoformat(timespec="seconds")
    f.write_text(f"{stamp} {reason}".strip() + "\n", encoding="utf-8")


def turn_off(kind: str = "flagship") -> None:
    """Выключить автопилот ФОРМАТА. Прогон, который уже идёт, не трогает.

    Для флагмана сносим и старый общий файл: иначе «выключи флагман» оставило бы его включённым через
    легаси-путь в enabled() — стоп-кран обязан быть настоящим.
    """
    kind = content_plan.norm_kind(kind)
    on_file(kind).unlink(missing_ok=True)
    if kind == "flagship":
        legacy_on_file().unlink(missing_ok=True)


def _state() -> dict:
    data = io_safe.load_json(STATE_FILE, {})
    return data if isinstance(data, dict) else {}


def last_run(kind: str = "flagship") -> date | None:
    """Дата последнего АВТО-прогона формата (None — ни разу / файл битый)."""
    raw = _state().get(kind)
    try:
        return date.fromisoformat(raw) if raw else None
    except (TypeError, ValueError):
        log.info("[автопилот] в состоянии кривая дата для '%s': %r", kind, raw)
        return None


def _save_state(data: dict) -> None:
    """Записать состояние АТОМАРНО. Не бросает: сорванная запись метки не должна ронять прогон.

    Атомарность тут не про «красиво»: битая метка «сегодня гоняли» читается как «не гоняли», и
    следующая проверка запустила бы ВТОРОЙ прогон — второй пост в отложке и лишние $1.6.
    """
    try:
        io_safe.dump_json(STATE_FILE, data)
    except OSError:
        log.exception("[автопилот] не смог записать состояние в %s", STATE_FILE)


def mark_run(kind: str, d: date | None = None) -> None:
    """Пометить, что формат сегодня уже запускался.

    Ставим метку ДО прогона (заявка, не отчёт): если прогон упадёт на середине, автопилот не станет
    перезапускать его каждые 10 минут и жечь деньги. Владелец увидит алерт о падении и решит сам.
    """
    data = _state()
    data[kind] = (d or datetime.now(content_plan.tz()).date()).isoformat()
    _save_state(data)


# --- НАСТРОЙКА ИЗ ЧАТА: валидация в КОДЕ, не в промпте ---------------------------------------
# Владелец меняет расписание словами в чате с Криейтором, значит значения приходят от МОДЕЛИ —
# и проверять их обязан код. Модель может ослышаться («за 40 часов»), а цена ошибки — пропущенный
# или сорванный выход в канал. Поэтому: жёсткие диапазоны, перекрёстная проверка «окно не пустое»,
# и на выходе всегда ЧЕЛОВЕЧЕСКИЙ отчёт «было → стало», который владелец видит в чате.

DOW_ALIASES = {
    "пн": 0, "понедельник": 0, "mon": 0,
    "вт": 1, "вторник": 1, "tue": 1,
    "ср": 2, "среда": 2, "wed": 2,
    "чт": 3, "четверг": 3, "thu": 3,
    "пт": 4, "пятница": 4, "fri": 4,
    "сб": 5, "суббота": 5, "sat": 5,
    "вс": 6, "воскресенье": 6, "sun": 6,
}


# Служебные слова живой речи: владелец скажет «по вт и пт», модель может передать фразу как есть —
# спотыкаться об «по» нельзя, иначе «настройка разговором» превращается в угадывание формата.
DOW_FILLER = {"по", "и", "в", "во", "на", "каждый", "каждую", "дни", "день", "выходим", "только", "-", "—"}


def parse_days(raw) -> list[int]:
    """«вт,чт» / «по вт и пт» / [1,3] → [1, 3]. Непонятное — ValueError с внятным текстом."""
    if isinstance(raw, (list, tuple)):
        items = [str(x) for x in raw]
    else:
        items = [p for p in str(raw or "").replace("/", ",").replace(" ", ",").split(",") if p]
    out: list[int] = []
    for it in items:
        s = it.strip().lower().strip(".")
        if not s or s in DOW_FILLER:
            continue
        if s.isdigit() and 0 <= int(s) <= 6:
            out.append(int(s))
        elif s in DOW_ALIASES:
            out.append(DOW_ALIASES[s])
        else:
            raise ValueError(f"не понял день «{it}» — пиши днями недели: «вт,чт»")
    if not out:
        raise ValueError("не увидел ни одного дня недели — напиши, например, «вт,чт»")
    return sorted(set(out))


# Слова «оба формата разом». Владелец говорит «включи автопилот» без уточнения — это НЕ значит
# «включи оба» молча: включение = посты в канал без его «ок», и догадываться тут нельзя. Поэтому
# «оба» должно быть СКАЗАНО, а пустое значение вызывающий обрабатывает сам (переспрашивает).
# Сверяем ЦЕЛИКОМ со словом, а не вхождением: «все» внутри «всегда» превратило бы «включи флагман
# всегда» в «включи оба» — молча и в ту сторону, где ошибка дороже.
_BOTH_WORDS = frozenset(("оба", "обе", "обоих", "обоим", "все", "всё", "вместе", "both", "all"))


def parse_kinds(raw) -> list:
    """«флагман» / «скоуп» / «флагман и скоуп» / «оба» → список форматов. Непонятное — ValueError.

    Строгая (в отличие от content_plan.norm_kind): это ввод ИЗ ЧАТА, то есть от модели, а цена промаха —
    включённый не тот автопилот, который сам поставит пост в канал. Лучше переспросить.
    """
    if isinstance(raw, (list, tuple)):
        out: list = []
        for item in raw:
            out += parse_kinds(item)
        return [k for k in content_plan.KINDS if k in out]     # канонический порядок, без дублей
    s = str(raw or "").strip().lower()
    if not s:
        raise ValueError("не понял, для какого формата — скажи «для флагмана», «для скоупа» или «для обоих»")
    words = [w.strip("«»\"'.,!?()") for w in s.replace("/", " ").replace(",", " ").split()]
    if _BOTH_WORDS.intersection(words):
        return list(content_plan.KINDS)
    # А вот имя формата ищем вхождением: владелец склоняет («для скоупа», «флагмана»), и обрубать
    # окончания списком было бы хрупче, чем искать корень.
    found = [k for k in content_plan.KINDS
             if any(w in s for w in content_plan.kind_words(k))]
    if not found:
        raise ValueError(f"не понял формат «{raw}» — скажи «флагман», «скоуп» или «оба»")
    return found


def parse_time(raw) -> str:
    """«16:00» / «16» / «16.30» / «в 16:00» → «16:00». Вне 05:00–23:59 — отказ (ночью не публикуем).

    Терпим служебные слова живой речи, как parse_days: владелец говорит «выход в 16:00», и модель
    может передать фразу как есть — спотыкаться об «в» нельзя.
    """
    s = str(raw or "").strip().replace(".", ":").replace("-", ":")
    s = "".join(ch for ch in s if ch.isdigit() or ch == ":").strip(":")
    if s.isdigit():
        s = f"{int(s)}:00"
    try:
        h, m = (int(x) for x in s.split(":")[:2])
    except ValueError:
        raise ValueError(f"не понял время «{raw}» — пиши как «16:00»") from None
    if not (5 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"время {h:02d}:{m:02d} вне разумного окна 05:00–23:59 — не публикуем ночью")
    return f"{h:02d}:{m:02d}"


# Пояса живой речью: владелец говорит «по берлину», а zoneinfo хочет «Europe/Berlin».
# Список короткий НАМЕРЕННО — города, где владелец реально бывает/о которых говорит. Полное имя пояса
# («Europe/Berlin») принимается всегда, так что список — удобство, а не ограничение.
TZ_ALIASES = {
    "берлин": "Europe/Berlin", "берлину": "Europe/Berlin", "берлине": "Europe/Berlin",
    "berlin": "Europe/Berlin", "германия": "Europe/Berlin", "цет": "Europe/Berlin",
    # Франкфурт — тот же пояс, что Берлин; владелец зовёт время канала именно франкфуртским.
    "франкфурт": "Europe/Berlin", "франкфурту": "Europe/Berlin", "франкфурте": "Europe/Berlin",
    "frankfurt": "Europe/Berlin",
    "москва": "Europe/Moscow", "москве": "Europe/Moscow", "мск": "Europe/Moscow",
    "moscow": "Europe/Moscow", "msk": "Europe/Moscow",
    "киев": "Europe/Kyiv", "киеву": "Europe/Kyiv", "kyiv": "Europe/Kyiv", "kiev": "Europe/Kyiv",
    "лондон": "Europe/London", "лондону": "Europe/London", "london": "Europe/London",
    "варшава": "Europe/Warsaw", "варшаве": "Europe/Warsaw", "warsaw": "Europe/Warsaw",
    "дубай": "Asia/Dubai", "дубаю": "Asia/Dubai", "dubai": "Asia/Dubai",
    "утс": "UTC", "utc": "UTC", "гмт": "UTC", "gmt": "UTC",
}


def parse_zone(raw) -> str:
    """«по берлину» / «Berlin» / «Europe/Berlin» → «Europe/Berlin». Непонятное/нет базы — ValueError.

    Проверяем ПО ФАКТУ (zoneinfo находит пояс), а не по виду строки: иначе можно записать красивое имя,
    которого нет в базе, и расписание молча уедет на фолбэк-смещение.
    """
    s = str(raw or "").strip().strip(".,")
    for junk in ("по ", "во ", "в ", "времени ", "время ", "часовой пояс ", "пояс "):
        if s.lower().startswith(junk):
            s = s[len(junk):].strip()
    if not s:
        raise ValueError("не понял, какой пояс — напиши, например, «по берлину» или «Europe/Berlin»")
    name = TZ_ALIASES.get(s.lower(), s)
    if content_plan.zone(name) is None:
        raise ValueError(f"пояс «{raw}» не нашёл в базе часовых поясов — попробуй «Europe/Berlin» "
                         f"или город: берлин / москва / киев / лондон / варшава / дубай")
    return name


def parse_number(raw, what: str) -> float:
    """«3» / «3,5» / «3 часа» → 3.0. Внятная ошибка вместо питоновского «could not convert string»."""
    s = str(raw or "").strip().replace(",", ".")
    keep = "".join(ch for ch in s if ch.isdigit() or ch == ".")   # «3 часа» → «3»
    try:
        return float(keep)
    except ValueError:
        raise ValueError(f"не понял число в «{raw}» ({what}) — напиши цифрой, например «3»") from None


def _validated(changes: dict) -> dict:
    """Проверить пачку правок целиком. Возвращает готовые к записи значения; бросает ValueError."""
    changes = {("scope_" + k[len("short_"):] if k.startswith("short_") else k): v
               for k, v in (changes or {}).items()}   # старое имя формата → каноничное
    out: dict = {}
    for kind in content_plan.KINDS:
        if f"{kind}_time" in changes:
            out[f"{kind}_time"] = parse_time(changes[f"{kind}_time"])
        if f"{kind}_days" in changes:
            out[f"{kind}_days"] = parse_days(changes[f"{kind}_days"])
    if "timezone" in changes:
        out["tz"] = parse_zone(changes["timezone"])
    if "lead_hours" in changes:
        v = parse_number(changes["lead_hours"], "за сколько часов до выхода стартовать")
        if not (0.5 <= v <= 12):
            raise ValueError(f"старт за {v:g} ч до выхода — вне разумного (0.5–12 ч)")
        out["lead_hours"] = v
    if "margin_minutes" in changes:
        v = parse_number(changes["margin_minutes"], "запас до слота в минутах")
        if not (10 <= v <= 240):
            raise ValueError(f"запас {v:g} мин — вне разумного (10–240 мин)")
        out["margin_minutes"] = v
    if not out:
        raise ValueError("нечего менять — не понял, какой параметр правим")
    # ПЕРЕКРЁСТНАЯ проверка: запас не должен съесть всё окно, иначе автопилот не запустится НИКОГДА
    # (окно = [слот−лид, слот−запас]) и владелец узнает об этом только по молчанию канала.
    lead = out.get("lead_hours", lead_hours())
    margin = out.get("margin_minutes", margin_minutes())
    if margin >= lead * 60:
        raise ValueError(f"запас {margin:g} мин ≥ старт за {lead:g} ч — окно запуска станет пустым, "
                         f"автопилот не сработает ни разу. Уменьши запас или увеличь лид.")
    return out


def describe_param(key: str, value) -> str:
    """Значение параметра человеческим языком (для отчёта «было → стало»)."""
    if key.endswith("_days"):
        return "/".join(content_plan.RU_DOW[i] for i in value) if value else "—"
    if key == "lead_hours":
        return f"за {float(value):g} ч до выхода"
    if key == "margin_minutes":
        return f"{float(value):g} мин"
    return str(value)


def param_label(key: str) -> str:
    """Имя параметра для владельца: «дни выхода скоупа», а не «scope_days».

    Отчёт «было → стало» он читает в телефоне — внутренние ключи там читаются как ошибка.
    """
    for kind in content_plan.KINDS:
        if key == f"{kind}_days":
            return f"дни выхода ({content_plan.kind_word(kind)})"
        if key == f"{kind}_time":
            return f"время выхода ({content_plan.kind_word(kind)})"
    return {"tz": "часовой пояс", "lead_hours": "старт прогона",
            "margin_minutes": "запас до слота"}.get(key, key)


def current_param(key: str):
    """Текущее ЭФФЕКТИВНОЕ значение параметра (с учётом всех источников)."""
    if key == "tz":
        return content_plan.tz_name() or "смещение PUBLISH_UTC_OFFSET"
    for kind in content_plan.KINDS:
        if key == f"{kind}_days":
            return list(content_plan.days_for(kind))
        if key == f"{kind}_time":
            return f"{content_plan.slot_time(kind):%H:%M}"
    if key == "lead_hours":
        return lead_hours()
    if key == "margin_minutes":
        return margin_minutes()
    return None


def apply_params(changes: dict, by: str = "чат") -> dict:
    """Применить правки расписания. {'ok': bool, 'diff': [(имя, было, стало)], 'error': str}.

    Пишем в plan_settings.json (НЕ в .env: боту .env править нельзя, и там нет пометки «кто менял»).
    Ничего не сохраняем при любой ошибке валидации — расписание не остаётся в полусостоянии.
    """
    try:
        clean = _validated(changes)
    except (ValueError, TypeError) as e:
        return {"ok": False, "diff": [], "error": str(e)}
    before = {k: current_param(k) for k in clean}
    data = content_plan.settings()
    data.update(clean)
    data["updated"] = datetime.now(content_plan.tz()).isoformat(timespec="seconds")
    data["updated_by"] = by
    try:
        content_plan.save_settings(data)
    except OSError as e:
        log.exception("[автопилот] не смог записать настройки плана")
        return {"ok": False, "diff": [], "error": f"не смог записать файл настроек: {e}"}
    diff = [(k, describe_param(k, before[k]), describe_param(k, clean[k])) for k in clean]
    log.info("[автопилот] настройки изменены (%s): %s", by, diff)
    return {"ok": True, "diff": diff, "error": ""}


# --- ОКНО и ВЕРДИКТ ---------------------------------------------------------------------------

def mark_result(kind: str, text: str) -> None:
    """Запомнить ИТОГ последнего автопрогона одной строкой (для панели /autopilot).

    Зачем: владелец смотрит в телефон, а не в лог на машине. «Последний прогон: ❌ упал: TimeoutError»
    в панели — это разница между «чинить прямо сейчас» и «узнать через два дня по молчанию канала».
    """
    data = _state()
    data[f"result_{kind}"] = text
    data[f"result_at_{kind}"] = datetime.now(content_plan.tz()).isoformat(timespec="minutes")
    _save_state(data)


def last_result(kind: str = "flagship") -> str:
    """Итог последнего автопрогона с временем («— ни разу», если автопилот ещё не работал)."""
    data = _state()
    text = data.get(f"result_{kind}")
    if not text:
        return "— ни разу"
    when = data.get(f"result_at_{kind}", "")
    return f"{text} ({when})" if when else str(text)


def warned_today(key: str) -> bool:
    """Уже предупреждали владельца про это сегодня? Проверки идут каждые 10–30 мин, и алерт «завод в
    /test» без этого превратился бы в спам — а спам перестают читать, и настоящий алерт потеряется."""
    return _state().get(f"warned_{key}") == datetime.now(content_plan.tz()).date().isoformat()


def mark_warned(key: str) -> None:
    data = _state()
    data[f"warned_{key}"] = datetime.now(content_plan.tz()).date().isoformat()
    _save_state(data)


def window(kind: str, d: date) -> tuple[datetime, datetime] | None:
    """Окно старта в конкретный день: (когда можно начинать, крайний срок). None — не день формата.

    Начало = слот − AUTOPILOT_LEAD_HOURS (по умолч. 4ч: пост в 16:00 ⇒ старт в 12:00).
    Конец = слот − AUTOPILOT_MARGIN_MINUTES. Это ОКНО, а не точка: если машина спала и Планировщик
    дёрнул нас в 13:20 вместо 12:00 — прогон всё равно состоится, пост всё равно успеет к 16:00.
    """
    slot = content_plan.slot_on(d, kind)
    if slot is None:
        return None
    return slot - timedelta(hours=lead_hours()), slot - timedelta(minutes=margin_minutes())


def due(kind: str = "flagship", *, now: datetime | None = None,
        busy_dates: set | None = None, last=_UNSET) -> dict:
    """Вердикт: {'go': bool, 'why': причина человеческим языком, 'slot': слот сегодня | None}.

    Чистая: всё внешнее (время, отложка канала, дата прошлого прогона) можно передать параметрами —
    отсюда тесты. `busy_dates=None` значит «проверить отложку не удалось» (нет сессии/сети): НЕ
    блокируем прогон, но пишем это в причину — предохранителем тут выступает сам content_plan
    (next_slot пропускает занятые дни), а молчаливый пропуск выхода хуже.
    """
    z = content_plan.tz()
    now = (now or datetime.now(z)).astimezone(z)
    today = now.date()
    slot = content_plan.slot_on(today, kind)
    label = content_plan.kind_label(kind)
    if slot is None:
        days = "/".join(content_plan.RU_DOW[i] for i in content_plan.days_for(kind))
        return {"go": False, "slot": None,
                "why": f"сегодня {content_plan.RU_DOW[today.weekday()]} — не день формата «{label}» ({days})"}
    start, deadline = window(kind, today)
    if now < start:
        return {"go": False, "slot": slot,
                "why": f"рано: окно старта с {start:%H:%M} (выход в {slot:%H:%M})"}
    # Две РАЗНЫЕ причины, а не одна «поздно» (баг, вскрытый живым выводом 11.08 в 19:13: панель писала
    # «до выхода в 16:00 меньше 60 мин», когда слот прошёл ТРИ ЧАСА назад). Формально пропуск верный в
    # обоих случаях, но объяснение — единственное, по чему владелец понимает, почему в канале тишина.
    if now >= slot:
        return {"go": False, "slot": slot,
                "why": f"выход в {slot:%H:%M} уже прошёл — сегодня поезд ушёл "
                       f"(окно старта было {start:%H:%M}–{deadline:%H:%M})"}
    if now > deadline:
        left = (slot - now).total_seconds() / 60
        return {"go": False, "slot": slot,
                "why": f"поздно: до выхода в {slot:%H:%M} осталось {left:.0f} мин (нужен запас "
                       f"{margin_minutes():.0f}) — прогон не успеет, сегодня пропускаю"}
    prev = last_run(kind) if last is _UNSET else last
    if prev == today:
        return {"go": False, "slot": slot, "why": "сегодня уже запускался (метка в autopilot_state.json)"}
    if busy_dates and today in busy_dates:
        return {"go": False, "slot": slot,
                "why": "на сегодня в «Отложенных» канала пост уже стоит — второй не нужен"}
    # Формулировка нейтральная НАМЕРЕННО: None приходит и когда отложку прочесть не смогли (мёртвая
    # сессия — тогда это в логах), и когда её просто не смотрели (панель /autopilot). «Не удалось» в
    # панели читалось бы как поломка, поэтому говорим ровно то, что правда в обоих случаях.
    note = "" if busy_dates is not None else " (занятость слота не проверена — иду по плану)"
    return {"go": True, "slot": slot,
            "why": f"пора: «{label}» выходит сегодня в {slot:%H:%M}, окно старта "
                   f"{start:%H:%M}–{deadline:%H:%M}{note}"}


def _alarm_is_set() -> bool:
    """Стоит ли задача-будильник в ОС. Ленивый импорт: os_task дёргает subprocess, панели он нужен раз."""
    try:
        from core import os_task
        return bool(os_task.status().get("exists"))
    except Exception:  # noqa: BLE001 — панель не имеет права падать из-за опроса ОС
        log.exception("[автопилот] не смог проверить задачу-будильник")
        return False


def status_text(kind: str = "flagship") -> str:
    """Панель состояния автопилота ОДНОГО формата — и для `run_autopilot --status`, и для /autopilot.

    Специально с ИСТОЧНИКОМ каждой настройки («из чата» / «из .env» / «дефолт кода»): три источника
    без пометки = «почему стоит не то, что я думал».
    """
    kind = content_plan.norm_kind(kind, default="flagship")
    now = datetime.now(content_plan.tz())
    win = window(kind, now.date())
    mode = runmode.get()
    days = "/".join(content_plan.RU_DOW[i] for i in content_plan.days_for(kind))
    st = content_plan.settings()
    v = due(kind, busy_dates=None)
    nxt = content_plan.next_slot(kind)
    # Пары (подпись, значение), а колонку ровняет ljust: подписи руками не выравниваем — на живом
    # выводе 11.08 «чем кончился» и «следующий выход» съехали, и панель стало неудобно читать.
    rows = [
        ("сейчас", f"{content_plan.human(now)}"),
        ("пояс канала", f"{content_plan.tz_label()} ({content_plan.source_of('tz', 'PUBLISH_TZ')})"),
        ("режим завода", "🧪 test — публиковать нельзя" if mode["mode"] == "test" else "боевой /main"),
        ("канал", config.get_optional("PUBLISH_CHANNEL") or "❌ не задан"),
        ("дни выхода", f"{days} ({content_plan.source_of(f'{kind}_days')})"),
        ("время выхода", f"{content_plan.slot_time(kind):%H:%M} "
                         f"({content_plan.source_of(f'{kind}_time', content_plan.time_env_key(kind))})"),
        ("старт прогона", f"за {lead_hours():g} ч до выхода "
                          f"({content_plan.source_of('lead_hours', 'AUTOPILOT_LEAD_HOURS')})"),
        ("запас до слота", f"{margin_minutes():g} мин "
                           f"({content_plan.source_of('margin_minutes', 'AUTOPILOT_MARGIN_MINUTES')})"),
        ("окно старта", f"{win[0]:%H:%M}–{win[1]:%H:%M}" if win else "— сегодня не день формата"),
        # Будильник ОБЯЗАН быть в панели: без него «включено» ничего не значит — некому проснуться.
        ("будильник", "✅ стоит (Планировщик Windows)" if _alarm_is_set()
                      else "❌ НЕТ — сам не проснётся, скажи «включи автопилот»"),
        ("последний авто", str(last_run(kind) or "— ни разу")),
        ("чем кончился", last_result(kind)),
        ("следующий слот", content_plan.human(nxt)),
        ("вердикт сейчас", f"{'✅ пора' if v['go'] else '⏭ пропуск'} — {v['why']}"),
    ]
    if st.get("updated"):
        rows.append(("правил из чата", f"{st['updated']} ({st.get('updated_by', '?')})"))
    width = max(len(k) for k, _ in rows)
    on = enabled(kind)
    head = (f"🤖 АВТОПИЛОТ · {content_plan.kind_word(kind).upper()} — "
            f"{'✅ ВКЛЮЧЁН' if on else '⏸ ВЫКЛЮЧЕН'}{'' if on else ' (сам не запускается)'}")
    return "\n".join([head, ""] + [f"• {k.ljust(width)} : {v}" for k, v in rows])


def status_all() -> str:
    """Сводная панель по ОБОИМ форматам: сначала однострочный итог, потом подробности по каждому.

    Зачем итог сверху: форматы независимы, и первый вопрос владельца — «что сейчас включено», а не
    «какой запас до слота у скоупа». Без сводки он читал бы две простыни, чтобы ответить на него.
    """
    head = ["🤖 АВТОПИЛОТ — что включено сейчас", ""]
    for k in content_plan.KINDS:
        days = "/".join(content_plan.RU_DOW[i] for i in content_plan.days_for(k))
        head.append(f"• {content_plan.kind_word(k).ljust(8)} : "
                    f"{'✅ включён' if enabled(k) else '⏸ выключен'} · {days} в "
                    f"{content_plan.slot_time(k):%H:%M} · след. {content_plan.human(content_plan.next_slot(k))}")
    if not any_enabled():
        head.append("\nОба выключены — посты выходят только по твоей команде (/run, /run_scope).")
    elif not _alarm_is_set():
        # Включённый формат без будильника — самая опасная ложь панели: «включено», а просыпаться некому.
        head.append("\n❌ БУДИЛЬНИК НЕ СТОИТ — сам никто не проснётся. Скажи «включи автопилот» заново.")
    return "\n\n".join(["\n".join(head)] + [status_text(k) for k in content_plan.KINDS])
