"""Страж инварианта изоляции: ветки scope, флагман и Threads НЕ грузят память друг друга
(ARCHITECTURE §4.1, N-14; Threads-набор добавлен аудитом 15.07 — третья ветка жила «на дисциплине»).

Изоляция держится тем, ЧТО каждая ветка _read-ит в свой _system(). Правка voice_core из scope-разбора
09.07 чуть не протекла флагману — этот тест ловит будущий регресс дёшево (статический разбор исходников,
только фактические _read('memory/…'), НЕ упоминания в комментариях/описаниях инструментов).
Общий для всех веток канон (brand.md) изоляцией НЕ считается — он и должен грузиться везде."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCOPE_ONLY = {"voice_core.md", "scope_manual.md", "scope_lessons.md", "headline_bank.md",
              "scope_anchors.md"}
FLAGSHIP_ONLY = {"content_manual.md", "post_lessons.md", "post_standard.md",
                 "format_playbook.md", "anchor_posts.md", "flagship_topics.md"}
THREADS_ONLY = {"threads_manual.md", "threads_flagman_anchors.md", "threads_lessons.md"}


def _loaded_memory(module_rel: str) -> set[str]:
    """Имена memory-файлов, которые модуль реально грузит в контекст через _read('memory/…')."""
    src = (ROOT / module_rel).read_text(encoding="utf-8")
    return set(re.findall(r"_read\(\s*['\"]memory/([^'\"]+\.md)['\"]", src))


def test_scope_does_not_load_flagship_memory():
    leak = _loaded_memory("core/scope_writer.py") & (FLAGSHIP_ONLY | THREADS_ONLY)
    assert leak == set(), f"scope грузит чужую память (протечка): {leak}"


def test_flagship_does_not_load_scope_memory():
    leak = _loaded_memory("core/creator_bot.py") & (SCOPE_ONLY | THREADS_ONLY)
    assert leak == set(), f"флагман грузит чужую память (протечка): {leak}"


def test_threads_does_not_load_tg_memory():
    # Голос Threads ≠ голос ТГ (данные 434 постов): протечка content_manual/voice_core в дистиллятор
    # тихо испортила бы мини-флагман — ровно сценарий, из-за которого этот файл существует.
    leak = _loaded_memory("core/threads_creator.py") & (SCOPE_ONLY | FLAGSHIP_ONLY)
    assert leak == set(), f"threads грузит ТГ-память (протечка): {leak}"


def test_guard_not_vacuous():
    # если _read-паттерн перестанет матчиться — тесты выше станут пустыми и бесполезными; ловим это
    assert "scope_manual.md" in _loaded_memory("core/scope_writer.py")
    assert "content_manual.md" in _loaded_memory("core/creator_bot.py")
    assert "threads_manual.md" in _loaded_memory("core/threads_creator.py")
