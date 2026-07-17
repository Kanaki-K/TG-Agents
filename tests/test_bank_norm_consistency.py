"""Страж ТИХОЙ ДЕГРАДАЦИИ: нормализация банка в dedup и в topic_category должна совпадать.

Путь к банку и чистка строки продублированы в двух модулях (dedup._bank_lines и topic_category).
Если одна нормализация дрейфанёт от другой — category_of вернёт UNKNOWN на РЕАЛЬНЫХ темах банка →
веса пикера все 1.0 → наклон ротации молча выключится (не падение, а невидимая потеря обучения).
Этот тест ловит расхождение на уровне логики, не дожидаясь прода. Аудит 17.07.
"""
from core import dedup, topic_category as tc

BANK = """## Слой 1.1 — Применение и принятие
- Стейблкоины как долларовые рельсы: инфраструктура, не казино
- [вышло 2026-07-07] RWA-токенизация — принятие структурно, не хайп

## Слой 3.4 — Математика стратегии
- IRR — почему «иксы» врут: 3x за 5 лет ≠ 3x за год

## Слой 6 — Разборы концепций и «словарь»
- Что такое L2 простыми словами
"""


def test_dedup_and_topic_category_agree_on_bank(tmp_path, monkeypatch):
    f = tmp_path / "flagship_topics.md"
    f.write_text(BANK, encoding="utf-8")
    monkeypatch.setattr(dedup, "BANK_FILE", f)
    monkeypatch.setattr(tc, "BANK_FILE", f)
    themes = [t for (_raw, t, _d) in dedup._bank_lines()]
    assert themes, "dedup не увидел тем банка — проверь парсер"
    unknown = [t for t in themes if tc.category_of(t) == tc.UNKNOWN]
    assert not unknown, (f"рассинхрон нормализации dedup↔topic_category: {len(unknown)} тем банка "
                         f"не привязались к категории (наклон пикера тихо выключился бы): {unknown[:3]}")
