"""Тесты сопоставления текстов (core/text_match): токены + асимметричное покрытие."""
from core import text_match as tm


def test_tokens_filters_short_and_punctuation():
    toks = tm.tokens("Иксы врут: 3x за 5 лет, ну и?")
    assert "иксы" in toks and "врут" in toks
    assert "3" in toks and "5" in toks          # числа
    assert "за" not in toks and "ну" not in toks  # <4 букв — отброшены


def test_coverage_identical_and_disjoint():
    assert tm.coverage("иксы врут годовых", "иксы врут годовых доходность") == 1.0
    assert tm.coverage("совсем другое слово", "иксы врут годовых") == 0.0
    assert tm.coverage("", "что угодно") == 0.0


def test_coverage_partial():
    # 2 из 3 токенов короткого покрыты длинным
    assert tm.coverage("иксы врут случайность", "иксы врут доходность") == 2 / 3


# --- обрезка для ИТОГ-панели: обрыв посреди слова врал владельцу (05.08) ------------------------

def test_clip_cuts_on_word_boundary():
    # было: «Circle объявила валидаторов Arc — BlackRock, Visa, D» — обрыв посреди имени
    s = "Circle объявила валидаторов Arc - BlackRock, Visa, DTCC становятся узлами"
    out = tm.clip(s, 52)
    assert out.endswith("…")
    assert len(out) <= 53
    assert not out.rstrip("…").endswith(("D", ","))     # ни обрубка слова, ни висячей запятой


def test_clip_keeps_short_text_untouched():
    assert tm.clip("короткая тема", 52) == "короткая тема"
    assert tm.clip("", 10) == ""
    assert tm.clip(None, 10) == ""


def test_clip_normalizes_whitespace():
    assert tm.clip("две   строки\nв одной", 40) == "две строки в одной"


def test_clip_handles_single_long_word():
    # одно слово длиннее лимита — режем жёстко, но обрыв всё равно помечаем
    out = tm.clip("A" * 80, 10)
    assert out == "A" * 10 + "…"
