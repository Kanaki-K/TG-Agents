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
def _clean_autopilot_env(monkeypatch):
    """Окно считаем от ДЕФОЛТОВ, а не от .env владельца — иначе тесты зависят от его настроек."""
    for k in ("AUTOPILOT_LEAD_HOURS", "AUTOPILOT_MARGIN_MINUTES", "AUTOPILOT_CHECK_EVERY"):
        monkeypatch.delenv(k, raising=False)


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
    assert "проверить не удалось" in v["why"]


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


def test_switch_off_by_default_and_toggles(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule, "ON_FILE", tmp_path / "autopilot_on")
    assert schedule.enabled() is False          # по умолчанию ВЫКЛЮЧЕН — включает только владелец
    schedule.turn_on("тест")
    assert schedule.enabled() is True
    assert "тест" in (tmp_path / "autopilot_on").read_text(encoding="utf-8")
    schedule.turn_off()
    assert schedule.enabled() is False


# --- настройки из .env -----------------------------------------------------------------------

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


@pytest.mark.parametrize("raw,expect", [("2", 2.0), ("2,5", 2.5), ("мусор", schedule.DEFAULT_LEAD_HOURS)])
def test_lead_hours_from_env(monkeypatch, raw, expect):
    monkeypatch.setenv("AUTOPILOT_LEAD_HOURS", raw)
    assert schedule.lead_hours() == expect


def test_lead_hours_default_when_unset(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_LEAD_HOURS", raising=False)
    assert schedule.lead_hours() == schedule.DEFAULT_LEAD_HOURS
