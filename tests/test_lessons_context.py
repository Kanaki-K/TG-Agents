"""Анти-жир уроков: загрузка в контекст режет провенанс-хвост, но НЕ правило/инлайн-пример;
страж записи ловит дубль мануала. Причина существования — уроки грузятся в КАЖДЫЙ пост и растут
append-only, провенанс-хвост «— _из правки:…_» платится зря (см. core/creator_tools.load_lessons_for_context)."""
from pathlib import Path

from core import creator_tools


def test_strip_keeps_rule_and_inline_example_drops_provenance(tmp_path):
    f = tmp_path / "post_lessons.md"
    f.write_text(
        "# Уроки\n\n"
        "- (2026-06-17) Убирать «И честно:» перед фактом - ❌ «И честно: X» ✅ «X» "
        "— _из правки: было «И честно: биткоин» → стало «биткоин»_\n",
        encoding="utf-8")
    ctx = creator_tools.load_lessons_for_context(f)
    assert "Убирать «И честно:» перед фактом" in ctx    # ПРАВИЛО цело
    assert "❌ «И честно: X» ✅ «X»" in ctx              # ИНЛАЙН-пример цел
    assert "из правки" not in ctx                        # провенанс-хвост срезан
    assert "стало «биткоин»" not in ctx


def test_non_provenance_dash_italic_kept(tmp_path):
    # дыра старого широкого регекса: он срезал ЛЮБОЙ «— _italic_» в конце строки → мог съесть
    # правило. Якорь на провенанс-префикс (из/владелец/правка) это чинит.
    f = tmp_path / "post_lessons.md"
    f.write_text("- (2026-07-20) Правило про заголовок — _это часть правила, не провенанс_\n",
                 encoding="utf-8")
    ctx = creator_tools.load_lessons_for_context(f)
    assert "это часть правила, не провенанс" in ctx   # НЕ срезано (не провенанс-хвост)


def test_flag_off_keeps_provenance(tmp_path, monkeypatch):
    f = tmp_path / "post_lessons.md"
    f.write_text("- (2026-06-17) Правило X — _из правки: было Y_\n", encoding="utf-8")
    monkeypatch.setattr(creator_tools, "STRIP_LESSON_EVIDENCE", False)
    assert "из правки" in creator_tools.load_lessons_for_context(f)  # флаг выкл → хвост на месте


def test_missing_or_empty_file_returns_empty(tmp_path):
    assert creator_tools.load_lessons_for_context(Path("/no/such.md")) == ""
    empty = tmp_path / "e.md"
    empty.write_text("", encoding="utf-8")
    assert creator_tools.load_lessons_for_context(empty) == ""


def test_manual_guard_flags_duplicate(tmp_path, monkeypatch):
    # урок, повторяющий строку мануала, ловится стражем (порог 0.6 по значимым словам)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "content_manual.md").write_text(
        "Не ссылайся на источник через слово: «сам признал», «тот же предупреждает» - источник один раз\n",
        encoding="utf-8")
    monkeypatch.setattr(creator_tools.config, "ROOT", tmp_path)
    hit = creator_tools._covered_by_manual("Не ссылайся на источник через слово")
    assert hit is not None
    # непохожее правило страж НЕ трогает
    assert creator_tools._covered_by_manual("Закрывающий вопрос делай коротким и понятным") is None
