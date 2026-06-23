"""Тесты ритма недели / выбора слота публикации (core/content_plan). Время инжектим — детерминированно."""
from datetime import datetime, timedelta

from core import content_plan as cp


def test_infer_kind_by_length():
    assert cp.infer_kind("x" * cp.FLAGSHIP_MIN_CHARS) == "flagship"
    assert cp.infer_kind("x" * (cp.FLAGSHIP_MIN_CHARS - 1)) == "short"
    assert cp.infer_kind("") == "short"
    assert cp.infer_kind(None) == "short"


def test_kind_label():
    assert "флагман" in cp.kind_label("flagship")
    assert "коротк" in cp.kind_label("short")


def _this_monday_midnight():
    """Понедельник текущей недели, 00:00, в поясе плана (детерминированный якорь now)."""
    z = cp.tz()
    now = datetime.now(z)
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday


def test_next_slot_flagship_is_future_and_on_flagship_day():
    monday = _this_monday_midnight()
    slot = cp.next_slot("flagship", now=monday)
    assert slot.weekday() in cp.FLAGSHIP_DAYS
    assert slot > monday
    assert slot.time() == cp._slot_time("flagship")


def test_next_slot_short_is_future_and_on_short_day():
    monday = _this_monday_midnight()
    slot = cp.next_slot("short", now=monday)
    assert slot.weekday() in cp.SHORT_DAYS
    assert slot > monday


def test_next_slot_skips_busy_date():
    monday = _this_monday_midnight()
    first = cp.next_slot("flagship", now=monday)
    second = cp.next_slot("flagship", now=monday, busy_dates={first.date()})
    assert second.date() != first.date()
    assert second > first


def test_human_starts_with_weekday_label():
    monday = _this_monday_midnight()
    slot = cp.next_slot("flagship", now=monday)
    assert cp.human(slot)[:2] in cp.RU_DOW
