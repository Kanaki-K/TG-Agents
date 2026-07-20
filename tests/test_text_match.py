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
