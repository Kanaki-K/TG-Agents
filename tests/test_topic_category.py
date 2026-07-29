"""Тесты категоризации тем флагмана (core/topic_category): слой банка → категория."""
from core import topic_category as tc

BANK = """# Банк образовательных флагманов

## Слой 1.1 — Реальное применение и принятие
- Стейблкоины как долларовые рельсы: инфраструктура, не казино
- [вышло 2026-07-07] RWA-токенизация — принятие структурно, не хайп

## Слой 1.2 — AI × крипта
- AI-агенты будут платить стейблами: Visa не работает для машин

## Слой 3.4 — Математика стратегии
- IRR — почему «иксы» врут о доходности: 3x за 5 лет ≠ 3x за год

## Слой 6 — Разборы концепций и «словарь»
- Что такое L2 простыми словами
"""


def _bank(tmp_path, monkeypatch):
    f = tmp_path / "flagship_topics.md"
    f.write_text(BANK, encoding="utf-8")
    monkeypatch.setattr(tc, "BANK_FILE", f)


def test_category_from_macro_layer(tmp_path, monkeypatch):
    _bank(tmp_path, monkeypatch)
    # Слой 1.* → «применение» (макро-слой 1), 3.* → «рынок», 6 → «словарь»
    assert tc.category_of("Стейблкоины как долларовые рельсы: инфраструктура, не казино") == "применение"
    # Слой 1.2 вынесен в свою категорию (override), а не в «применение»
    assert tc.category_of("AI-агенты будут платить стейблами: Visa не работает для машин") == "ai-крипта"
    assert tc.category_of("IRR — почему «иксы» врут о доходности: 3x за 5 лет ≠ 3x за год") == "рынок"
    assert tc.category_of("Что такое L2 простыми словами") == "словарь"


def test_used_marker_stripped(tmp_path, monkeypatch):
    """Журнал хранит тему БЕЗ маркера, в банке она с [вышло] — join всё равно матчится."""
    _bank(tmp_path, monkeypatch)
    assert tc.category_of("RWA-токенизация — принятие структурно, не хайп") == "применение"


def test_norm_case_and_spaces(tmp_path, monkeypatch):
    _bank(tmp_path, monkeypatch)
    assert tc.category_of("что такое   l2   простыми словами") == "словарь"


def test_unknown_theme(tmp_path, monkeypatch):
    _bank(tmp_path, monkeypatch)
    assert tc.category_of("Темы которой нет в банке") == tc.UNKNOWN
    assert tc.category_of("") == tc.UNKNOWN


def test_missing_bank_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "BANK_FILE", tmp_path / "нет-файла.md")
    assert tc.category_of("что угодно") == tc.UNKNOWN


def test_helpers():
    assert tc.label("рынок") == "Рынок, on-chain, математика, макро"
    assert set(tc.all_slugs()) == {"применение", "психология", "рынок", "философия",
                                   "антиказино", "словарь", "ai-крипта", "институции"}
