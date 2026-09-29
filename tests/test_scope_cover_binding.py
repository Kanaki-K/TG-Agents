"""ОБЛОЖКА: привязка к посту, а не ко времени и не к имени файла (16.09.2026).

ДВА ЖИВЫХ СЛУЧАЯ ПОДРЯД, оба мои регрессии — записаны, чтобы не повторить.

1. ЧУЖАЯ ОБЛОЖКА В КАНАЛЕ. Прогон 16.09 пере-выбрал тему (судья понятия отклонил первую), за один
   прогон написались ДВА поста, и publish_now взял обложку первого для второго: гейт сверял ВРЕМЯ
   («файл обложки свежее драфта на ≤2 сек»), а время не отличает «прошлый прогон» от «прошлая тема
   в этом же прогоне». В канал уехал пост про Venice с вывеской Strategy.

2. ОБЛОЖКИ НЕТ ВООБЩЕ. Починив первое, я записал в файл SCOPE_COVER вторую строку — имя драфта — и
   забыл, что файл читают ТРИ места. Конвейер прочитал обе строки как один путь, такого файла нет,
   и прогон отрапортовал «🚨 ОБЛОЖКИ НЕТ» при найденной и правильной картинке.
   Владелец: «обложка всегда должна быть». Это правило канала с 07.09 («всегда, без исключений»).

Запуск: python -m pytest tests/test_scope_cover_binding.py"""
from __future__ import annotations

from core import creator_tools as ct


# ── формат файла знает ОДНА функция ─────────────────────────────────────────────────────────────

def test_parser_splits_path_and_owner(tmp_path, monkeypatch):
    f = tmp_path / "cover.txt"
    f.write_text("C:\\media\\scope_3_0.jpg\n2026-09-17-btc-reserve-hr8957-scope.md", encoding="utf-8")
    monkeypatch.setattr(ct, "SCOPE_COVER", f)
    assert ct.scope_cover() == ("C:\\media\\scope_3_0.jpg", "2026-09-17-btc-reserve-hr8957-scope.md")


def test_parser_reads_old_single_line_format(tmp_path, monkeypatch):
    f = tmp_path / "cover.txt"
    f.write_text("C:\\media\\scope_3_0.jpg\n", encoding="utf-8")
    monkeypatch.setattr(ct, "SCOPE_COVER", f)
    assert ct.scope_cover() == ("C:\\media\\scope_3_0.jpg", "")


def test_parser_survives_missing_and_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "SCOPE_COVER", tmp_path / "нет-такого.txt")
    assert ct.scope_cover() == ("", "")
    f = tmp_path / "cover.txt"; f.write_text("   \n\n", encoding="utf-8")
    monkeypatch.setattr(ct, "SCOPE_COVER", f)
    assert ct.scope_cover() == ("", "")


def test_pipeline_uses_the_shared_parser():
    """Прямой read_text() и был причиной «обложки нет» — он не должен вернуться."""
    import run_pipeline as rp
    src = open(rp.__file__, encoding="utf-8").read()
    assert "creator_tools.scope_cover()" in src
    assert "SCOPE_COVER.read_text" not in src, "конвейер снова читает файл мимо общего разбора"


# ── своя обложка или чужая ──────────────────────────────────────────────────────────────────────

def test_rename_between_fix_rounds_keeps_the_cover():
    """Писатель пересохраняет драфт под новым именем на каждом круге правок. Это ТА ЖЕ тема —
    обложку терять нельзя, иначе пост уходит голым (живой случай 16.09)."""
    assert ct._same_topic_draft("2026-09-17-btc-reserve-hr8957-scope.md",
                                "2026-09-17-hr8957-audit-scope.md")
    assert ct._same_topic_draft("2026-09-16-venice-vvv.md", "2026-09-16-venice-vvv-fix-scope.md")


def test_different_topic_loses_the_cover():
    """Ровно случай 16.09: обложка Strategy не должна уехать с постом про Venice."""
    assert not ct._same_topic_draft("2026-09-16-strategy-strc-buyback.md",
                                    "2026-09-16-venice-insiders-scope.md")


def test_unparsable_names_keep_the_cover():
    """Не смогли разобрать имена — обложку НЕ теряем: «всегда, без исключений» важнее аккуратности."""
    assert ct._same_topic_draft("", "2026-09-17-x-scope.md")
    assert ct._same_topic_draft("2026-09-17-scope.md", "2026-09-17-fix-scope.md")


def test_service_suffixes_are_not_topic():
    """scope/fix/short — служебные хвосты, темой они не являются и совпадением считаться не должны."""
    assert ct._draft_topic_tokens("2026-09-17-venice-scope-fix.md") == {"venice"}
    assert not ct._same_topic_draft("2026-09-16-alpha-scope.md", "2026-09-16-beta-fix-scope.md")
