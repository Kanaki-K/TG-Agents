"""Тесты ритма недели / выбора слота публикации (core/content_plan). Время инжектим — детерминированно."""
from datetime import datetime, timedelta

import pytest

from core import content_plan as cp


@pytest.fixture(autouse=True)
def _isolate_plan_settings(monkeypatch, tmp_path):
    """Ритм берём из КАНОНА кода, а не из живых правок владельца (data/plan_settings.json меняется
    из чата с Криейтором — иначе «выходим по пн» роняло бы эти тесты)."""
    monkeypatch.setattr(cp, "SETTINGS_FILE", tmp_path / "plan_settings.json")


def test_infer_kind_by_length():
    assert cp.infer_kind("x" * cp.FLAGSHIP_MIN_CHARS) == "flagship"
    assert cp.infer_kind("x" * (cp.FLAGSHIP_MIN_CHARS - 1)) == "short"
    assert cp.infer_kind("") == "short"
    assert cp.infer_kind(None) == "short"


def test_kind_label():
    assert "флагман" in cp.kind_label("flagship")
    assert "коротк" in cp.kind_label("short")
    assert "скоуп" in cp.kind_label("scope")


@pytest.mark.parametrize("raw,expect", [
    ("flagship", "flagship"), ("флагман", "flagship"), ("Флагмана", "flagship"), ("Ф1", "flagship"),
    ("scope", "scope"), ("short", "scope"), ("скоуп", "scope"), ("СКОУПА", "scope"),
    ("короткий", "scope"), ("под прицелом", "scope"),
])
def test_norm_kind_understands_owner_words(raw, expect):
    """Имя формата приезжает от МОДЕЛИ из чата — промах тут включил бы не тот автопилот."""
    assert cp.norm_kind(raw) == expect


def test_short_is_the_same_format_as_scope():
    """'short' — старое имя скоупа. Разъедутся дни или время — владелец получит два разных расписания
    в зависимости от того, кто позвал формат (пайплайн зовёт 'short', автопилот — 'scope')."""
    assert cp.days_for("short") == cp.days_for("scope")
    assert cp._slot_time("short") == cp._slot_time("scope")
    assert cp.time_env_key("short") == cp.time_env_key("scope")


def test_both_formats_default_to_16_00():
    """Канон канала — 16:00 у обоих. Дефолт кода обязан совпадать с реальностью: при опечатке в .env
    он и станет действующим временем, и разойтись с каналом ему нельзя (см. content_plan шапку)."""
    assert cp.DEFAULT_FLAGSHIP_TIME == (16, 0)
    assert cp.DEFAULT_SCOPE_TIME == (16, 0)


def test_scope_days_are_mon_wed_fri_and_do_not_clash_with_flagship():
    """Пятница — день скоупа (владелец 21.08 уехал и ставил пост руками именно в пятницу)."""
    assert cp.SCOPE_DAYS == (0, 2, 4)
    assert 4 in cp.days_for("scope")
    assert not set(cp.days_for("scope")) & set(cp.days_for("flagship"))


def _this_monday_midnight():
    """Понедельник текущей недели, 00:00, в поясе плана (детерминированный якорь now)."""
    z = cp.tz()
    now = datetime.now(z)
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday


def test_next_slot_flagship_is_future_and_on_flagship_day():
    monday = _this_monday_midnight()
    slot = cp.next_slot("flagship", now=monday)
    assert slot.weekday() in cp.days_for("flagship")
    assert slot > monday
    assert slot.time() == cp._slot_time("flagship")


def test_next_slot_short_is_future_and_on_short_day():
    monday = _this_monday_midnight()
    slot = cp.next_slot("short", now=monday)
    assert slot.weekday() in cp.days_for("short")
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
