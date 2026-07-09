"""Парсеры вердикта анти-повтора (core/dedup) — чистые, без LLM и без выгрузки канала."""
from core import dedup


def test_recommended_theme_extracts_quoted():
    v = ("🆕 «BTC-резерв» — ново, ни одного поста\n"
         "РЕКОМЕНДУЮ: «Биткоин как резерв государств»\n"
         "СТАТУС: ОК")
    assert dedup.recommended_theme(v) == "Биткоин как резерв государств"
    assert dedup.all_repeats(v) is False


def test_recommended_theme_rejects_paused_domain():
    # жёсткий стоп (dedup.py:285): рекомендацию по домену на паузе НЕ отдаём (модель любит протащить стейблы/x402)
    v = "РЕКОМЕНДУЮ: «Стейблкоины как рельсы для AI-агентов»\nСТАТУС: ОК"
    assert dedup.recommended_theme(v) == ""


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
    # ⚠️ «та же сущность недавно, угол потенциально иной» — флаг, но НЕ блок выпуска.
    # Тема НЕ-paused, иначе жёсткий стоп срежет рекомендацию в "" (см. test_recommended_theme_rejects_paused_domain)
    v = ("⚠️ «Майнеры и себестоимость» — была #439 [2026-06-23], бери только радикально иной угол\n"
         "РЕКОМЕНДУЮ: «Себестоимость майнинга — радикально иной угол + отсылка к #439»\n"
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


def test_repeat_themes_only_paused_note_when_no_repeats():
    # нет 🔁 → список повторов пуст, но paused_note добавляется ВСЕГДА (детерминированный запрет доменов, dedup.py:304)
    assert dedup.repeat_themes("🆕 «a» — ново\nСТАТУС: ОК") == dedup.paused_note()


def test_empty_brief_soft_ok():
    v = dedup.check("")
    assert dedup.all_repeats(v) is False
    assert dedup.recommended_theme(v) == ""


# --- paused-гейт: граница слова (фикс ложных блоков, 09.07) ---

def test_hits_paused_no_false_positive_midword():
    # РЕГРЕСС: «мика» (пауза MiCA) НЕ должна ловиться внутри «эконоМИКА / динаМИКА» —
    # был substring-баг, который заворачивал любой макро-пост ПОСЛЕ оплаченной генерации
    assert dedup._hits_paused("мировая экономика и рыночная динамика") == ""
    assert dedup._hits_paused("обычный пост про биткоин, ставку ФРС и золото") == ""
    assert dedup._hits_paused("") == ""


def test_hits_paused_stemming_at_word_start():
    # стемминг сохранён: паузное слово ловится как НАЧАЛО слова (sticky-домены, дата-независимо)
    assert dedup._hits_paused("стейблкоины как рельсы") == "стейбл"
    assert dedup._hits_paused("новость про MiCA регуляцию") == "mica"
