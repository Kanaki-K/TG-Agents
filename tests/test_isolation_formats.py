"""Страж инварианта изоляции: ЧЕТЫРЕ свода правил (площадка × формат) не грузят память друг друга.

    ТГ-флагман      content_manual.md          ← core/creator_bot
    ТГ-скоуп        scope_manual.md            ← core/scope_writer
    Threads-флагман threads_flagship_manual.md ← core/threads_creator, kind='flagship'
    Threads-скоуп   threads_scope_manual.md    ← core/threads_creator, kind='scope'

(ARCHITECTURE §4.1, N-14; Threads-набор добавлен аудитом 15.07, разделён на два формата 09.09.2026 —
принцип владельца «каждая площадка × каждый формат = свой набор правил».)

Две разные проверки, потому что изоляция держится двумя разными способами:
* ТГ-ветки — РАЗНЫМИ МОДУЛЯМИ: сверяем статически, какие memory-файлы модуль реально _read-ит;
* Threads-форматы — ОДНИМ модулем с реестром FORMATS: сверяем, что наборы файлов не пересекаются
  и что ни один не тянет ТГ-память.
Общий для всех канон (brand.md) изоляцией НЕ считается — он и должен грузиться везде."""
import re
from pathlib import Path

from core import threads_creator

ROOT = Path(__file__).resolve().parent.parent

SCOPE_ONLY = {"voice_core.md", "scope_manual.md", "scope_lessons.md", "headline_bank.md"}
FLAGSHIP_ONLY = {"content_manual.md", "post_lessons.md", "post_standard.md",
                 "format_playbook.md", "anchor_posts.md", "flagship_topics.md"}
TG_ONLY = SCOPE_ONLY | FLAGSHIP_ONLY
THREADS_ONLY = {"threads_flagship_manual.md", "threads_flagship_anchors.md", "threads_flagship_lessons.md",
                "threads_scope_manual.md", "threads_scope_anchors.md", "threads_scope_lessons.md"}


def _loaded_memory(module_rel: str) -> set[str]:
    """Имена memory-файлов, которые модуль реально грузит в контекст через _read('memory/…')."""
    src = (ROOT / module_rel).read_text(encoding="utf-8")
    return set(re.findall(r"_read\(\s*['\"]memory/([^'\"]+\.md)['\"]", src))


def _format_files(kind: str) -> set[str]:
    """Файлы памяти, объявленные в реестре формата Threads (мануал/эталоны/уроки)."""
    fmt = threads_creator.spec(kind)
    return {fmt["manual"].split("/")[-1], fmt["anchors"].split("/")[-1], fmt["lessons"].split("/")[-1]}


def test_scope_does_not_load_flagship_memory():
    leak = _loaded_memory("core/scope_writer.py") & (FLAGSHIP_ONLY | THREADS_ONLY)
    assert leak == set(), f"scope грузит чужую память (протечка): {leak}"


def test_flagship_does_not_load_scope_memory():
    leak = _loaded_memory("core/creator_bot.py") & (SCOPE_ONLY | THREADS_ONLY)
    assert leak == set(), f"флагман грузит чужую память (протечка): {leak}"


def test_threads_module_does_not_load_tg_memory():
    # Голос Threads ≠ голос ТГ (данные 434 постов): протечка content_manual/voice_core в Threads-ветку
    # тихо испортила бы её — ровно сценарий, из-за которого этот файл существует.
    leak = _loaded_memory("core/threads_creator.py") & TG_ONLY
    assert leak == set(), f"threads грузит ТГ-память (протечка): {leak}"


def test_threads_formats_do_not_share_rule_files():
    flagship, scope = _format_files("flagship"), _format_files("scope")
    assert flagship & scope == set(), f"мини-флагман и мини-скоуп делят файлы правил: {flagship & scope}"
    assert (flagship | scope) & TG_ONLY == set(), "Threads-формат объявил ТГ-файл своим сводом"
    assert (flagship | scope) <= THREADS_ONLY, "неизвестный файл в реестре форматов Threads"


def test_threads_format_files_exist():
    # Свод может быть ПУСТЫМ (мануал ждёт правил владельца), но файл обязан существовать: иначе
    # ветка молча поехала бы на «(эталонов пока нет)» и никто бы не заметил опечатку в пути.
    for kind in ("flagship", "scope"):
        fmt = threads_creator.spec(kind)
        for key in ("manual", "anchors", "lessons"):
            assert (ROOT / fmt[key]).exists(), f"{kind}: нет файла {fmt[key]}"


def test_guard_not_vacuous():
    # если _read-паттерн перестанет матчиться — тесты выше станут пустыми и бесполезными; ловим это
    assert "scope_manual.md" in _loaded_memory("core/scope_writer.py")
    assert "content_manual.md" in _loaded_memory("core/creator_bot.py")
    assert _format_files("flagship") and _format_files("scope")
