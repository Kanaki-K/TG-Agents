"""Заголовок scope — РОВНО одна мысль (владелец 20.07/27.07): не двойник ни через точку, ни через тире.
Дырка 27.07: `_title_two_sentences` считает тире ОДНИМ предложением (для тег-тем «RWA: …») → двойник
«Бигтехи потеряли 800$ - биткоин не дрогнул» проскакивал. `_title_dash_double` её закрывает (слева
уже полный крючок ≥3 слов = двойник; короткий тег 1-2 слова = тег-тема, не трогаем).
Запуск: python -m pytest tests/test_scope_title.py"""
from core import creator_tools as ct


def test_dash_double_detected():
    # «полный крючок - вторая мысль» (слева ≥3 слов) = двойник (кейс 27.07)
    assert ct._title_dash_double("📊 Бигтехи потеряли 800 млрд$ - биткоин не дрогнул") is True


def test_dash_tag_theme_not_double():
    # короткий тег перед тире (1-2 слова) — тег-тема, НЕ двойник (бережём «RWA - …»)
    assert ct._title_dash_double("RWA - рельсы для банков") is False


def test_no_dash_not_double():
    assert ct._title_dash_double("📊 Mag7 минус 800 млрд$") is False


def test_name_with_initial_not_double():
    # инициал «T.» не считается словом → «T. Rowe Price» = 2 слова = тег-тема, не двойник (ложняк 17.07)
    assert ct._title_dash_double("T. Rowe Price - пенсии в крипте") is False
    assert ct._title_keep_first("T. Rowe Price - пенсии в крипте") == "T. Rowe Price - пенсии в крипте"


def test_keep_first_strips_dash_tail():
    # срез оставляет ЛЕВУЮ мысль — ровно то, что владелец утвердил 27.07
    assert ct._title_keep_first("📊 Бигтехи потеряли 800 млрд$ - биткоин не дрогнул") == "📊 Бигтехи потеряли 800 млрд$"


def test_keep_first_bold_preserved():
    # жирную обёртку **…** бережём
    assert ct._title_keep_first("**📊 Бигтехи потеряли 800 млрд$ - биткоин не дрогнул**") == "**📊 Бигтехи потеряли 800 млрд$**"


def test_keep_first_tag_theme_untouched():
    # тег-тема через тире не режется (слева 1 слово)
    assert ct._title_keep_first("RWA - рельсы для банков") == "RWA - рельсы для банков"


def test_keep_first_single_thought_untouched():
    assert ct._title_keep_first("📊 Mag7 минус 800 млрд$") == "📊 Mag7 минус 800 млрд$"


def test_keep_first_period_double_still_cut():
    # старое правило (двойник через точку) продолжает работать
    assert ct._title_keep_first("**Рынок вытряхнул трейдеров. Долгосрочника - нечем**") == "**Рынок вытряхнул трейдеров**"
