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


def test_has_issues_failopen_on_error_or_empty():
    # РЕД-ЛАЙН фейл-открыто (закрепляем ОСОЗНАННО, аудит 20.07): сбой/пустой вердикт НЕ блокирует —
    # инфра-флейк 2FA не должен глушить пост. Остаточный ⚠️ блокирует уже в run_pipeline (re-gate).
    assert verify.has_issues("(фактчек не удался: timeout)") is False
    assert verify.has_issues("") is False
    assert verify.has_issues(None) is False


def test_has_issues_on_indented_warning():
    assert verify.has_issues("  ⚠️ АТРИБУЦИЯ выдумана\nСТАТУС: ЧИСТО") is True   # strip() терпит отступ


def test_web_context_flagship_uses_reality_not_brief():
    # Флагман (web=True, scope=False): у вечной темы брифа НЕТ → сверяем с вебом, кап выше дефолтного (1).
    check, tool = verify._web_context(scope=False, web=True)
    assert check is verify.FLAGSHIP_SOURCE_CHECK
    assert tool is verify.FLAGSHIP_VERIFY_WEB
    assert tool["max_uses"] > verify.VERIFY_WEB["max_uses"]
    assert "БРИФА ПОД НЕЁ НЕТ" in check  # «нет в брифе» тут НЕ находка — источник истины веб


def test_web_context_scope_web_uses_scope_check():
    check, tool = verify._web_context(scope=True, web=True)
    assert check is verify.SCOPE_SOURCE_CHECK
    assert tool is verify.SCOPE_VERIFY_WEB


def test_web_context_default_no_source_check():
    # Дефолтный проход (web=False) — без спец-инструкции, дешёвый кап 1 (первый брифовый фильтр).
    check, tool = verify._web_context(scope=False, web=False)
    assert check == ""
    assert tool is verify.VERIFY_WEB
