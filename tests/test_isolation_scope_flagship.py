"""Страж инварианта изоляции: ветки scope и флагман НЕ грузят память друг друга (ARCHITECTURE §4.1, N-14).

Изоляция держится тем, ЧТО каждая ветка _read-ит в свой _system(). Правка voice_core из scope-разбора
09.07 чуть не протекла флагману — этот тест ловит будущий регресс дёшево (статический разбор исходников,
только фактические _read('memory/…'), НЕ упоминания в комментариях/описаниях инструментов)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCOPE_ONLY = {"voice_core.md", "scope_manual.md", "scope_lessons.md", "headline_bank.md"}
FLAGSHIP_ONLY = {"content_manual.md", "post_lessons.md", "post_standard.md",
                 "format_playbook.md", "anchor_posts.md", "flagship_topics.md"}


def _loaded_memory(module_rel: str) -> set[str]:
    """Имена memory-файлов, которые модуль реально грузит в контекст через _read('memory/…')."""
    src = (ROOT / module_rel).read_text(encoding="utf-8")
    return set(re.findall(r"_read\(\s*['\"]memory/([^'\"]+\.md)['\"]", src))


def test_scope_does_not_load_flagship_memory():
    leak = _loaded_memory("core/scope_writer.py") & FLAGSHIP_ONLY
    assert leak == set(), f"scope грузит флагман-память (протечка): {leak}"


def test_flagship_does_not_load_scope_memory():
    leak = _loaded_memory("core/creator_bot.py") & SCOPE_ONLY
    assert leak == set(), f"флагман грузит scope-память (протечка): {leak}"


def test_guard_not_vacuous():
    # если _read-паттерн перестанет матчиться — тесты выше станут пустыми и бесполезными; ловим это
    assert "scope_manual.md" in _loaded_memory("core/scope_writer.py")
    assert "content_manual.md" in _loaded_memory("core/creator_bot.py")
