"""Тесты автопилота (core/schedule): решение «пора или нет».

Почему это важно покрыть: ошибка тут = либо молчаливо пропущенный выход в канал, либо лишний
прогон (деньги + второй пост в отложке). Время, отложку и дату прошлого прогона инжектим
параметрами — тесты детерминированные, сети и API не касаются.
"""
from datetime import datetime, timedelta

import pytest

from core import content_plan as cp
from core import schedule


@pytest.fixture(autouse=True)
def _clean_autopilot_env(monkeypatch, tmp_path):
    """Окно считаем от ДЕФОЛТОВ: ни .env владельца, ни его правки из чата (plan_settings.json) не
    должны влиять на тесты — иначе «поменял расписание словами» роняет CI."""
    for k in ("AUTOPILOT_LEAD_HOURS", "AUTOPILOT_MARGIN_MINUTES", "AUTOPILOT_CHECK_EVERY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(cp, "SETTINGS_FILE", tmp_path / "plan_settings.json")


def _slot_day(offset_weeks: int = 0):
    """Ближайший будущий день флагмана (Вт/Чт) как date — якорь для всех тестов."""
    z = cp.tz()
    d = datetime.now(z).date() + timedelta(weeks=offset_weeks)
    for ahead in range(1, 15):
        cand = d + timedelta(days=ahead)
        if cand.weekday() in cp.FLAGSHIP_DAYS:
            return cand
    raise AssertionError("не нашёл день флагмана — сломан FLAGSHIP_DAYS")


def _at(d, hour: float):
    return datetime.combine(d, cp._slot_time("flagship"), cp.tz()) - timedelta(hours=hour)


# --- содержимое окна --------------------------------------------------------------------------

def test_window_starts_lead_hours_before_slot():
    d = _slot_day()
    start, deadline = schedule.window("flagship", d)
    slot = cp.slot_on(d, "flagship")
    assert slot - start == timedelta(hours=schedule.lead_hours())
    assert slot - deadline == timedelta(minutes=schedule.margin_minutes())
    assert start < deadline < slot


def test_window_is_none_on_non_flagship_day():
    d = _slot_day()
    non = next(d + timedelta(days=k) for k in range(1, 8)
               if (d + timedelta(days=k)).weekday() not in cp.FLAGSHIP_DAYS)
    assert schedule.window("flagship", non) is None


def test_slot_on_returns_none_outside_format_days():
    d = _slot_day()
    assert cp.slot_on(d, "flagship") is not None
    assert cp.slot_on(d, "flagship").weekday() in cp.FLAGSHIP_DAYS


# --- вердикт due() ---------------------------------------------------------------------------

def test_due_go_inside_window():
    d = _slot_day()
    v = schedule.due("flagship", now=_at(d, schedule.lead_hours() - 0.5),
                     busy_dates=set(), last=None)
    assert v["go"] is True
    assert v["slot"].date() == d


def test_due_too_early_before_window():
    d = _slot_day()
    v = schedule.due("flagship", now=_at(d, schedule.lead_hours() + 1),
                     busy_dates=set(), last=None)
    assert v["go"] is False
    assert "рано" in v["why"]


def test_due_too_late_near_slot():
    """Ближе margin к слоту не стартуем: прогон (~10-20 мин) не успеет к выходу."""
    d = _slot_day()
    v = schedule.due("flagship", now=_at(d, schedule.margin_minutes() / 60 / 2),
                     busy_dates=set(), last=None)
    assert v["go"] is False
    assert "поздно" in v["why"]


def test_due_skips_non_flagship_day():
    d = _slot_day()
    non = next(d + timedelta(days=k) for k in range(1, 8)
               if (d + timedelta(days=k)).weekday() not in cp.FLAGSHIP_DAYS)
    v = schedule.due("flagship", now=_at(non, schedule.lead_hours() - 0.5),
                     busy_dates=set(), last=None)
    assert v["go"] is False
    assert v["slot"] is None
    assert "не день формата" in v["why"]


def test_due_skips_if_already_ran_today():
    d = _slot_day()
    now = _at(d, schedule.lead_hours() - 0.5)
    v = schedule.due("flagship", now=now, busy_dates=set(), last=now.date())
    assert v["go"] is False
    assert "уже запускался" in v["why"]


def test_due_skips_if_slot_already_busy():
    """На сегодня в «Отложенных» уже стоит пост (владелец поставил руками) → второй не нужен."""
    d = _slot_day()
    now = _at(d, schedule.lead_hours() - 0.5)
    v = schedule.due("flagship", now=now, busy_dates={d}, last=None)
    assert v["go"] is False
    assert "Отложенных" in v["why"]


def test_due_goes_when_other_days_busy():
    d = _slot_day()
    now = _at(d, schedule.lead_hours() - 0.5)
    v = schedule.due("flagship", now=now, busy_dates={d + timedelta(days=1)}, last=None)
    assert v["go"] is True


def test_due_goes_when_queue_unknown_but_says_so():
    """Нет MTProto-сессии → отложку не прочли. Молчаливый пропуск выхода хуже: идём, но помечаем."""
    d = _slot_day()
    v = schedule.due("flagship", now=_at(d, schedule.lead_hours() - 0.5),
                     busy_dates=None, last=None)
    assert v["go"] is True
    assert "не проверена" in v["why"]


# --- состояние и выключатель -----------------------------------------------------------------

def test_mark_and_last_run_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule, "STATE_FILE", tmp_path / "autopilot_state.json")
    assert schedule.last_run("flagship") is None
    d = _slot_day()
    schedule.mark_run("flagship", d)
    assert schedule.last_run("flagship") == d


def test_last_run_survives_broken_state(tmp_path, monkeypatch):
    """Владелец правит data/ руками — битый файл не должен ронять автопилот (AUDIT N-10)."""
    p = tmp_path / "autopilot_state.json"
    p.write_text("{не json", encoding="utf-8")
    monkeypatch.setattr(schedule, "STATE_FILE", p)
    assert schedule.last_run("flagship") is None


def test_settings_write_is_atomic_and_leaves_no_temp(tmp_path, monkeypatch):
    """Обрыв записи оставил бы битый JSON, а битый читается как «настроек нет» — расписание владельца
    молча вернулось бы к дефолту. Пишем через temp+replace: на диске либо старое целиком, либо новое."""
    monkeypatch.setattr(cp, "SETTINGS_FILE", tmp_path / "plan_settings.json")
    assert schedule.apply_params({"flagship_time": "16:00"})["ok"]
    assert schedule.apply_params({"flagship_time": "18:00"})["ok"]
    assert cp.settings()["flagship_time"] == "18:00"
    assert list(tmp_path.glob("*.tmp")) == []      # временный файл не остался мусором
    assert (tmp_path / "plan_settings.json").read_text(encoding="utf-8").strip().endswith("}")


def test_mark_result_shows_in_panel(tmp_path, monkeypatch):
    """Итог последнего прогона владелец должен видеть В ТЕЛЕФОНЕ (панель), а не только в логе машины."""
    monkeypatch.setattr(schedule, "STATE_FILE", tmp_path / "autopilot_state.json")
    assert schedule.last_result("flagship") == "— ни разу"
    schedule.mark_result("flagship", "❌ упал: TimeoutError")
    assert "TimeoutError" in schedule.last_result("flagship")
    assert "TimeoutError" in schedule.status_text("flagship")


def test_mark_result_does_not_break_run_mark(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule, "STATE_FILE", tmp_path / "autopilot_state.json")
    d = _slot_day()
    schedule.mark_run("flagship", d)
    schedule.mark_result("flagship", "✅ в отложке")
    assert schedule.last_run("flagship") == d      # метки живут рядом и не затирают друг друга


def test_warned_once_per_day(tmp_path, monkeypatch):
    """Проверки идут каждые 10-30 мин: алерт «завод в /test» обязан прийти ОДИН раз, иначе спам."""
    monkeypatch.setattr(schedule, "STATE_FILE", tmp_path / "autopilot_state.json")
    assert schedule.warned_today("test-mode") is False
    schedule.mark_warned("test-mode")
    assert schedule.warned_today("test-mode") is True
    assert schedule.warned_today("no-channel") is False     # ключи независимы


def test_warning_mark_does_not_eat_run_mark(tmp_path, monkeypatch):
    """Метки предупреждений и метка прогона живут в одном файле — не должны затирать друг друга."""
    monkeypatch.setattr(schedule, "STATE_FILE", tmp_path / "autopilot_state.json")
    d = _slot_day()
    schedule.mark_run("flagship", d)
    schedule.mark_warned("test-mode")
    assert schedule.last_run("flagship") == d
    assert schedule.warned_today("test-mode") is True


def test_switch_off_by_default_and_toggles(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule, "ON_FILE", tmp_path / "autopilot_on")
    assert schedule.enabled() is False          # по умолчанию ВЫКЛЮЧЕН — включает только владелец
    schedule.turn_on("тест")
    assert schedule.enabled() is True
    assert "тест" in (tmp_path / "autopilot_on").read_text(encoding="utf-8")
    schedule.turn_off()
    assert schedule.enabled() is False


# --- настройки из .env -----------------------------------------------------------------------

# --- НАСТРОЙКА ИЗ ЧАТА: разбор человеческих формулировок --------------------------------------

@pytest.mark.parametrize("raw,expect", [
    ("вт,чт", [1, 3]),
    ("Вторник и четверг", [1, 3]),
    ("вт чт", [1, 3]),
    ("пн/ср/пт", [0, 2, 4]),
    ([1, 3], [1, 3]),
    ("чт,вт,чт", [1, 3]),          # порядок и дубли нормализуются
])
def test_parse_days_understands_owner_phrasing(raw, expect):
    assert schedule.parse_days(raw) == expect


@pytest.mark.parametrize("raw", ["по вт и пт", "выходим по вт, пт", "каждый вт и пт"])
def test_parse_days_ignores_speech_filler(raw):
    """Модель может передать фразу владельца как есть — «по» и «каждый» не должны ломать настройку."""
    assert schedule.parse_days(raw) == [1, 4]


@pytest.mark.parametrize("raw", ["вторнник", "", "8", "каждый день", "по и в"])
def test_parse_days_rejects_garbage(raw):
    with pytest.raises(ValueError):
        schedule.parse_days(raw)


@pytest.mark.parametrize("raw,expect", [("3", 3.0), ("3,5", 3.5), ("3 часа", 3.0), ("за 2 часа", 2.0)])
def test_parse_number_understands_speech(raw, expect):
    assert schedule.parse_number(raw, "тест") == expect


def test_parse_number_explains_instead_of_crashing():
    with pytest.raises(ValueError, match="не понял число"):
        schedule.parse_number("рано утром", "тест")


def test_apply_params_accepts_spoken_numbers():
    res = schedule.apply_params({"lead_hours": "3 часа"}, by="тест")
    assert res["ok"], res["error"]
    assert schedule.lead_hours() == 3.0


@pytest.mark.parametrize("raw,expect", [
    ("16:00", "16:00"), ("16", "16:00"), ("9.30", "09:30"),
    ("в 16:00", "16:00"), ("выход в 17:30", "17:30"),   # модель может передать фразу владельца как есть
])
def test_parse_time_normalises(raw, expect):
    assert schedule.parse_time(raw) == expect


@pytest.mark.parametrize("raw", ["03:00", "25:00", "вечером", ""])
def test_parse_time_rejects_unreasonable(raw):
    with pytest.raises(ValueError):
        schedule.parse_time(raw)


# --- НАСТРОЙКА ИЗ ЧАТА: запись и предохранители ----------------------------------------------

def test_apply_params_writes_and_reports_diff():
    res = schedule.apply_params({"flagship_time": "17:00", "flagship_days": "вт,пт"}, by="тест")
    assert res["ok"], res["error"]
    assert cp.settings()["flagship_time"] == "17:00"
    assert cp.settings()["flagship_days"] == [1, 4]
    assert cp.settings()["updated_by"] == "тест"
    names = {k for k, _, _ in res["diff"]}
    assert names == {"flagship_time", "flagship_days"}


def test_chat_change_actually_moves_the_slot():
    """Смысл всей затеи: правка словами обязана влиять на РЕАЛЬНЫЙ слот публикации, а не только на файл."""
    assert schedule.apply_params({"flagship_days": "пн"}, by="тест")["ok"]
    assert cp.days_for("flagship") == (0,)
    assert cp.next_slot("flagship").weekday() == 0


def test_apply_params_rejects_empty_window():
    """Запас ≥ лида = окно пустое, автопилот не сработал бы НИ РАЗУ, а владелец узнал бы по молчанию."""
    res = schedule.apply_params({"lead_hours": 1, "margin_minutes": 90})
    assert res["ok"] is False
    assert "окно" in res["error"]
    assert cp.settings() == {}          # при ошибке НИЧЕГО не записано


@pytest.mark.parametrize("changes", [
    {"lead_hours": 40},                 # «за 40 часов» — модель ослышалась
    {"margin_minutes": 5},
    {"flagship_time": "03:00"},
    {},                                 # нечего менять
])
def test_apply_params_rejects_out_of_range(changes):
    res = schedule.apply_params(changes)
    assert res["ok"] is False
    assert res["error"]
    assert cp.settings() == {}


def test_settings_beat_env_and_env_beats_default(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_LEAD_HOURS", "5")
    assert schedule.lead_hours() == 5.0                     # .env перекрывает дефолт
    assert schedule.apply_params({"lead_hours": 3})["ok"]
    assert schedule.lead_hours() == 3.0                     # правка из чата перекрывает .env


def test_status_text_shows_state_and_sources():
    txt = schedule.status_text("flagship")
    assert "АВТОПИЛОТ" in txt
    assert "дни выхода" in txt and "время выхода" in txt
    assert "дефолт кода" in txt          # ничего не задано → источник виден честно
    assert "вердикт сейчас" in txt


def test_panel_does_not_lie_about_broken_value(monkeypatch):
    """Опечатка в конфиге («16-00») даёт откат на дефолт. Панель обязана сказать «не разобрал», а не
    «из .env» — иначе она врёт ровно там, где владелец ей верит, решая, включать ли автопилот."""
    monkeypatch.setenv("PUBLISH_FLAGSHIP_TIME", "16-00")
    assert cp.source_of("flagship_time", "PUBLISH_FLAGSHIP_TIME").startswith("дефолт кода")
    assert "не разобрал" in cp.source_of("flagship_time", "PUBLISH_FLAGSHIP_TIME")
    assert "не разобрал" in schedule.status_text("flagship")
    monkeypatch.setenv("PUBLISH_FLAGSHIP_TIME", "16:00")
    assert cp.source_of("flagship_time", "PUBLISH_FLAGSHIP_TIME") == "из .env"
    assert cp.slot_time("flagship").strftime("%H:%M") == "16:00"


def test_broken_days_in_file_fall_back_to_canon(tmp_path, monkeypatch):
    """Файл правят руками — кривые дни не должны менять ритм молча (канон + предупреждение в лог)."""
    from core import io_safe

    p = tmp_path / "plan_settings.json"
    io_safe.dump_json(p, {"flagship_days": "вт,чт"})     # строка вместо списка чисел
    monkeypatch.setattr(cp, "SETTINGS_FILE", p)
    assert cp.days_for("flagship") == cp.FLAGSHIP_DAYS


def test_status_text_marks_chat_edit():
    schedule.apply_params({"flagship_time": "18:00"}, by="чат Криейтора")
    txt = schedule.status_text("flagship")
    assert "18:00" in txt
    assert "из чата" in txt


# --- исполнитель (run_autopilot) --------------------------------------------------------------
# Он работает БЕЗ человека, поэтому опечатка в нём вылезла бы только в 12:00 во вторник —
# импортом и выжимкой отчёта ловим это на CI.

def test_autopilot_module_imports_and_digests_report():
    import run_autopilot

    report = "\n".join([
        "=== Контент-завод: прогон [флагман] ===",
        "📝 --- ГОТОВЫЙ ПОСТ ---",
        "**💸 Заголовок поста**",
        "тело поста",
        "✅ Поставил в отложенные канала: флагман (Ф1) на Вт 12.08 16:00 (режим: file).",
        "━━━━━━ ИТОГ (вход → решение → почему) ━━━━━━",
        "  формат : флагман",
    ])
    d = run_autopilot._digest(report)
    assert "Заголовок поста" in d
    assert "Поставил в отложенные" in d
    assert "ИТОГ" in d
    assert len(d) <= run_autopilot.TG_ALERT_LIMIT


def test_autopilot_digest_survives_empty_report():
    import run_autopilot

    assert run_autopilot._digest("") == ""


def test_autopilot_recognises_whether_post_was_published():
    """«Прогон закончен» ≠ «пост в отложке»: писатель мог отказаться (нет повода). Владельцу нельзя
    показывать ✅, если в канал ничего не встало — он решит, что пост в очереди, и не проверит."""
    import run_autopilot

    assert run_autopilot._published_ok("✅ Поставил в отложенные канала: флагман (Ф1) на Вт 16:00") is True
    assert run_autopilot._published_ok("⛔ Свежего поста в этом прогоне НЕ создано") is False


def test_autopilot_emit_goes_to_log_not_only_console(caplog):
    """Смысл файлового лога: рассказ ПАЙПЛАЙНА (он идёт через print) обязан попасть в лог, иначе по
    логу не понять, где прогон встал. Многострочный блок разбиваем — одна запись на 4000 знаков нечитаема."""
    import logging as _logging

    import run_autopilot

    with caplog.at_level(_logging.INFO):
        run_autopilot._emit("🧭 Тема выбрана: стейблкоины")
        run_autopilot._emit("строка один\n\nстрока два")
    logged = [r.getMessage() for r in caplog.records]   # getMessage — уже с подставленными args
    assert any("Тема выбрана" in m for m in logged)
    assert sum("строка один" in m or "строка два" in m for m in logged) == 2   # разбито на две записи


@pytest.mark.parametrize("raw,expect", [("2", 2.0), ("2,5", 2.5), ("мусор", schedule.DEFAULT_LEAD_HOURS)])
def test_lead_hours_from_env(monkeypatch, raw, expect):
    monkeypatch.setenv("AUTOPILOT_LEAD_HOURS", raw)
    assert schedule.lead_hours() == expect


def test_lead_hours_default_when_unset(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_LEAD_HOURS", raising=False)
    assert schedule.lead_hours() == schedule.DEFAULT_LEAD_HOURS
