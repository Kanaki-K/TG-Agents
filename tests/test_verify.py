"""Контракт verify: темпоральный флаг свежести триггерит правку (без LLM/сети)."""
from core import verify


def test_temporal_flag_triggers_fix():
    # ⚠️ ТЕМП (устаревший/старо-поданный повод) должен считаться замечанием → авто-правка
    v = ("✅ «ETH 1778$» — совпадает с брифом\n"
         "⚠️ ТЕМП: пост ведёт от «Merge 2022» — свежий повод читается как ретроспектива — вынеси дату повода вперёд\n"
         "ИТОГ: 1✅ / 1⚠️ / 0❓\nСТАТУС: ПРАВКИ")
    assert verify.has_issues(v) is True


def test_clean_temporal_no_fix():
    v = ("✅ «ETH 1778$» — совпадает\nИТОГ: 1✅ / 0⚠️ / 0❓\nСТАТУС: ЧИСТО")
    assert verify.has_issues(v) is False


def test_temporal_check_only_when_scope():
    # правило свежести подмешивается в промпт ТОЛЬКО для scope (флагман = вечные темы, «2022» законно)
    assert "ТЕМПОРАЛЬНАЯ СВЕЖЕСТЬ" in verify.TEMPORAL_CHECK
