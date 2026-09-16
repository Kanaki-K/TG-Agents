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
import ast
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


# --- ВТОРОЙ КОНТУР ИЗОЛЯЦИИ: не только память, но и КОД (требование владельца 09.09.2026:
# «пайплайны не должны пересекаться»). ТГ-пайплайн и Threads-пайплайн — две отдельные машины;
# единственная разрешённая точка контакта — журнал вышедших постов (published_journal): ТГ туда
# пишет, Threads оттуда читает. Всё остальное — общий нейтральный слой (config/llm/cost/план/руки).
TG_BRAINS = {"core.creator_tools", "core.creator_bot", "core.scope_writer", "core.verify", "core.dedup",
             "core.topic_gate", "core.scout_tools", "core.scout_bot", "core.scout_funnel",
             "core.post_angle", "core.title_emoji", "core.market_tools", "run_pipeline"}
THREADS_BRAINS = {"core.threads_creator", "core.threads_source", "run_threads_pipeline",
                  "core.threads_dedup"}


def _imported_modules(module_rel: str) -> set[str]:
    """Модули проекта, которые файл импортирует (import X / from X import y, включая `from core import a, b`)."""
    tree = ast.parse((ROOT / module_rel).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def test_threads_pipeline_does_not_import_tg_machinery():
    for mod in ("core/threads_creator.py", "core/threads_source.py", "run_threads_pipeline.py"):
        leak = _imported_modules(mod) & TG_BRAINS
        assert leak == set(), f"{mod} тянет мозги ТГ-пайплайна: {leak}"


def test_tg_pipeline_does_not_import_threads_machinery():
    for mod in ("run_pipeline.py", "core/creator_tools.py", "core/scope_writer.py"):
        leak = _imported_modules(mod) & THREADS_BRAINS
        assert leak == set(), f"{mod} тянет мозги Threads-пайплайна: {leak}"


def test_the_only_bridge_is_the_journal():
    # Мост существует и он ОДИН: ТГ пишет в журнал, Threads из него читает. Если однажды Threads-ветка
    # начнёт читать драфты или звать ТГ-писателя — тест выше покраснеет, а этот покажет, что мост цел.
    assert "core.published_journal" in _imported_modules("run_pipeline.py")
    assert "core.published_journal" in _imported_modules("core/threads_source.py")


# ── ПЕРСОНА — СЛЕПОЕ ПЯТНО СТРАЖА (найдено 16.09.2026) ──────────────────────────────────────────
# Проверки выше сверяют, какие memory/*.md грузит модуль. По ним всё было чисто — и всё равно
# писатель скоупа получал ФЛАГМАНСКИЕ правила: персона приходит не через _read('memory/…'), а через
# config.load_agent(), и в поле зрения стража не попадала вовсе.
# ЗАМЕР 16.09 (до фикса): в системном промпте скоупа флагманские числа 2800/3000/3800/4096 —
# 17 упоминаний, свои 1250/1500/1050 — 5. Причём чужие стояли в ПЕРСОНЕ, самой авторитетной части
# промпта, а свои — глубоко в мануале. Владелец про пост на 1656 знаков: «какого хуя такой длинный?
# такое чувство, что он напутал флагман и скоуп». Напутал не он.
# Лечение: флагман-специфичные куски персоны помечены [[Ф-ONLY]] и вырезаются для скоупа кодом.

def test_scope_prompt_carries_no_flagship_length():
    """Главный тест: писатель скоупа не должен видеть НИ ОДНОГО флагманского размера."""
    from core import scope_writer
    import re
    s = scope_writer._system()
    for n in ("3000", "3800"):
        assert not re.search(r"\b" + n + r"\b", s), f"флагманское число {n} снова в промпте скоупа"
    # 2800–4096 допустимы ровно в двух местах: явный дисклеймер «правила флагмана к тебе НЕ
    # применяются» и таблица сравнения форматов в своде. Больше — значит снова протекло.
    assert len(re.findall(r"\b4096\b", s)) <= 2, "флагманский потолок протёк в промпт скоупа"


def test_scope_prompt_carries_no_flagship_branch_logic():
    """Скоуп не выбирает формат и не правит стандарт — это ветка флагмана."""
    from core import scope_writer
    s = scope_writer._system()
    for leak in ("каталог форматов", "propose_standard", "#434"):
        assert leak not in s, f"логика флагман-ветки протекла в скоуп: «{leak}»"


def test_flagship_prompt_carries_no_scope_rules():
    """Изоляция обязана держать в ОБЕ стороны."""
    from core import creator_bot
    s = creator_bot._system()
    for leak in ("scope_lessons", "scope_anchors", "Под прицелом» — свод"):
        assert leak not in s, f"правила скоупа протекли во флагман: «{leak}»"


def test_persona_keeps_the_shared_voice():
    """Вырезаем ФОРМАТ, а не ГОЛОС: общие правила ремесла обязаны остаться — ради них персону
    и переиспользуют. Иначе завтра у скоупа заведётся вторая копия голоса и они разойдутся."""
    from core import config, scope_writer
    clean = scope_writer._scope_persona(config.load_agent("creator")["persona"])
    for must in ("Голос автора", "Железные правила", "Не выдумывай цифры"):
        assert must in clean, f"из персоны скоупа пропал общий канон: «{must}»"
    assert "[[Ф-ONLY]]" not in clean and "[[/Ф-ONLY]]" not in clean, "маркеры уехали в промпт"


def test_flagship_persona_is_untouched():
    """Флагман обязан получать персону ЦЕЛИКОМ — маркеры режут только для скоупа."""
    from core import config
    persona = config.load_agent("creator")["persona"]
    assert "2800–4096" in persona and "post_standard.md" in persona
