"""Автопилот: КОГДА завод запускается сам — и когда НЕ запускается.

Зачем отдельным модулем: «пора или нет» — чистая функция от времени и состояния на диске, поэтому
покрывается тестами БЕЗ реального прогона (прогон = деньги + публикация в канал). `run_autopilot.py`
только исполняет вердикт и умеет о нём рассказать.

Ритм недели тут НЕ дублируется: дни и время выхода берём из `core/content_plan` (Вт/Чт,
`PUBLISH_FLAGSHIP_TIME`, `PUBLISH_TZ`). Здесь — только окно старта, метка «сегодня уже гоняли»
и предохранители. Полное объяснение для владельца — в `docs/AUTOPILOT.md`.

ГЛАВНЫЙ предохранитель — файл-выключатель `data/autopilot_on` (по образцу `data/threads_unlocked`):
нет файла → автопилот НИЧЕГО не делает. Удалить файл = мгновенно всё остановить, .env не трогая.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from core import config, content_plan, io_safe, runmode

log = logging.getLogger(__name__)

STATE_FILE = config.ROOT / "data" / "autopilot_state.json"   # что и когда гоняли (переживает перезапуск)
ON_FILE = config.ROOT / "data" / "autopilot_on"              # файл-выключатель: нет → автопилот спит

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


def enabled() -> bool:
    """Включён ли автопилот. Один выключатель — ФАЙЛ (не .env): убирается одним движением."""
    return ON_FILE.exists()


def turn_on(reason: str = "") -> None:
    """Включить автопилот (создать файл-выключатель). Причина остаётся в файле — как у Threads."""
    ON_FILE.parent.mkdir(exist_ok=True)
    stamp = datetime.now(content_plan.tz()).isoformat(timespec="seconds")
    ON_FILE.write_text(f"{stamp} {reason}".strip() + "\n", encoding="utf-8")


def turn_off() -> None:
    """Выключить автопилот (удалить файл). Прогон, который уже идёт, не трогает."""
    ON_FILE.unlink(missing_ok=True)


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
    out: dict = {}
    if "flagship_time" in changes:
        out["flagship_time"] = parse_time(changes["flagship_time"])
    if "flagship_days" in changes:
        out["flagship_days"] = parse_days(changes["flagship_days"])
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
    if key == "flagship_days":
        return "/".join(content_plan.RU_DOW[i] for i in value) if value else "—"
    if key == "lead_hours":
        return f"за {float(value):g} ч до выхода"
    if key == "margin_minutes":
        return f"{float(value):g} мин"
    return str(value)


def current_param(key: str):
    """Текущее ЭФФЕКТИВНОЕ значение параметра (с учётом всех источников)."""
    if key == "flagship_days":
        return list(content_plan.days_for("flagship"))
    if key == "flagship_time":
        return f"{content_plan.slot_time('flagship'):%H:%M}"
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
    if now > deadline:
        return {"go": False, "slot": slot,
                "why": f"поздно: до выхода в {slot:%H:%M} меньше {margin_minutes():.0f} мин — "
                       f"прогон не успеет, сегодня пропускаю"}
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


def status_text(kind: str = "flagship") -> str:
    """Панель состояния автопилота — ОДИН текст и для `run_autopilot --status`, и для /autopilot в боте.

    Специально с ИСТОЧНИКОМ каждой настройки («из чата» / «из .env» / «дефолт кода»): три источника
    без пометки = «почему стоит не то, что я думал».
    """
    now = datetime.now(content_plan.tz())
    win = window(kind, now.date())
    mode = runmode.get()
    days = "/".join(content_plan.RU_DOW[i] for i in content_plan.days_for(kind))
    st = content_plan.settings()
    v = due(kind, busy_dates=None)
    nxt = content_plan.next_slot(kind)
    lines = [
        f"🤖 АВТОПИЛОТ — {'✅ ВКЛЮЧЁН' if enabled() else '⏸ ВЫКЛЮЧЕН'}"
        f"{'' if enabled() else ' (сам не запускается)'}",
        "",
        f"• сейчас        : {content_plan.human(now)} · пояс {content_plan.tz_label()}",
        f"• режим завода  : {'🧪 test — публиковать нельзя' if mode['mode'] == 'test' else 'боевой /main'}",
        f"• канал         : {config.get_optional('PUBLISH_CHANNEL') or '❌ не задан'}",
        f"• дни выхода    : {days} ({content_plan.source_of(f'{kind}_days')})",
        f"• время выхода  : {content_plan.slot_time(kind):%H:%M} "
        f"({content_plan.source_of(f'{kind}_time', content_plan.time_env_key(kind))})",
        f"• старт прогона : за {lead_hours():g} ч до выхода "
        f"({content_plan.source_of('lead_hours', 'AUTOPILOT_LEAD_HOURS')})",
        f"• запас до слота: {margin_minutes():g} мин "
        f"({content_plan.source_of('margin_minutes', 'AUTOPILOT_MARGIN_MINUTES')})",
        f"• окно старта   : {f'{win[0]:%H:%M}–{win[1]:%H:%M}' if win else '— сегодня не день формата'}",
        f"• последний авто: {last_run(kind) or '— ни разу'}",
        f"• чем кончился : {last_result(kind)}",
        f"• следующий выход: {content_plan.human(nxt)}",
        f"• вердикт сейчас: {'✅ пора' if v['go'] else '⏭ пропуск'} — {v['why']}",
    ]
    if st.get("updated"):
        lines.append(f"• правил из чата: {st['updated']} ({st.get('updated_by', '?')})")
    return "\n".join(lines)
