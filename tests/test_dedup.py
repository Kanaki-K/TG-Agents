"""Парсеры вердикта анти-повтора (core/dedup) — чистые, без LLM и без выгрузки канала."""
from core import dedup


def test_recommended_theme_extracts_quoted():
    v = ("🆕 «x402» — ново, ни одного поста\n"
         "РЕКОМЕНДУЮ: «Стейблкоины как рельсы для AI-агентов»\n"
         "СТАТУС: ОК")
    assert dedup.recommended_theme(v) == "Стейблкоины как рельсы для AI-агентов"
    assert dedup.all_repeats(v) is False


def test_all_repeats_blocks():
    v = ("🔁 «x402» — было #441 [2026-06-23]\n"
         "🔁 «ETF-приток» — было #438 [2026-06-19]\n"
         "РЕКОМЕНДУЮ: «ВСЕ ПОВТОРЫ»\n"
         "СТАТУС: ПОВТОР")
    assert dedup.all_repeats(v) is True
    assert dedup.recommended_theme(v) == ""


def test_status_ok_not_blocked():
    v = "🔁 «a» — было #1\n🆕 «b» — ново\nРЕКОМЕНДУЮ: «b как новый угол»\nСТАТУС: ОК"
    assert dedup.all_repeats(v) is False
    assert dedup.recommended_theme(v) == "b как новый угол"


def test_warn_tier_not_blocked():
    # ⚠️ «та же сущность недавно, угол потенциально иной» — флаг, но НЕ блок выпуска
    v = ("⚠️ «x402 + Visa + AWS» — была #439 [2026-06-23], бери только радикально иной угол\n"
         "РЕКОМЕНДУЮ: «x402 как инфра платежей — радикально иной угол + отсылка к #439»\n"
         "СТАТУС: ОК")
    assert dedup.all_repeats(v) is False
    assert "#439" in dedup.recommended_theme(v)


def test_fallback_without_status_line():
    # модель не дала строку СТАТУС — фолбэк по значкам 🆕/⚠️/🔁
    assert dedup.all_repeats("🔁 «a» — было\n🔁 «b» — было") is True
    assert dedup.all_repeats("🆕 «a» — ново\n🔁 «b» — было") is False
    assert dedup.all_repeats("⚠️ «a» — недавно была\n🔁 «b» — было") is False
    assert dedup.all_repeats("") is False


def test_repeat_themes_extracts_avoid_list():
    # флагман больше не получает «пиши ИМЕННО это» — ему отдают список повторов «чего НЕ брать»
    v = ("🔁 «x402 микроплатежи» — было #439 [2026-06-23]\n"
         "🔁 «ETF-приток» — было #438 [2026-06-19]\n"
         "🆕 «новый угол» — ново\n"
         "РЕКОМЕНДУЮ: «новый угол»\nСТАТУС: ОК")
    avoid = dedup.repeat_themes(v)
    assert "x402 микроплатежи" in avoid and "ETF-приток" in avoid
    assert "новый угол" not in avoid          # 🆕 в список «не брать» не попадает


def test_repeat_themes_empty_when_no_repeats():
    assert dedup.repeat_themes("🆕 «a» — ново\nСТАТУС: ОК") == ""


def test_empty_brief_soft_ok():
    v = dedup.check("")
    assert dedup.all_repeats(v) is False
    assert dedup.recommended_theme(v) == ""
