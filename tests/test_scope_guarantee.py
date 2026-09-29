"""ГАРАНТИЯ СКОУПА: пост в формате v3 и с картинкой на КАЖДОМ прогоне (16.09.2026).

Владелец после дня из 14 прогонов и одного годного поста: «доделать так, чтобы я гарантированно
получал скоуп в правильном формате 3 версии с картинкой».

Гарантия держится не обещанием, а тем, что закрыты ПУТИ ОТКАЗА. Их было два рукотворных:
1. ГЕЙТ ПУБЛИКАЦИИ БЫЛ ТУПИКОМ. Он не пускал брак в отложку — и прогон кончался ничем. Дефекты
   там механические (длина, обращение, жанр-обзор), автор чинит их одним кругом. Теперь круг есть.
2. ПУСТОЙ ПУЛ ОБЛОЖКИ СДАВАЛСЯ СРАЗУ. Второй круг поиска existed только для «судья забраковал всё»,
   а при пустом пуле мы выходили молча — хотя это ровно случай, где искать шире нужнее: страницы
   отдали 429/403 и первый маршрут провалился целиком. Правило канала с 07.09: «картинка всегда».

Запуск: python -m pytest tests/test_scope_guarantee.py"""
from __future__ import annotations

import inspect

import run_pipeline as rp
from core import creator_tools as ct, scope_writer as sw


# ── запрет обязан быть починяемым ───────────────────────────────────────────────────────────────

def test_blockers_get_one_repair_round_before_refusal():
    src = inspect.getsource(rp.run_cycle) if hasattr(rp, "run_cycle") else open(rp.__file__, encoding="utf-8").read()
    assert "fix_blockers" in src, "гейт публикации снова тупик — правки нет"
    i_fix = src.index("fix_blockers")
    i_ref = src.index("В ОТЛОЖКУ НЕ СТАВЛЮ")
    assert i_fix < i_ref, "отказ обязан идти ПОСЛЕ попытки починить"


def test_repair_round_is_rechecked():
    """Круг правок без перепроверки — это вера на слово, а автор её уже подводил (07.08).

    Якорь — САМ ВЫЗОВ круга, а не первое слово «fix_blockers» в файле: с 18.09 у флагмана свой круг
    (`_run_creator_blockers`), и его докстрока поминает scope-круг раньше, чем тот вызывается."""
    src = inspect.getsource(rp.run_cycle)
    after = src[src.index("scope_writer.fix_blockers, _blockers"):]
    assert "publish_blockers" in after[:900], "после круга правок гейт не перепроверяется"


def test_repair_prompt_fixes_mechanics_not_meaning():
    for must in ("ЦЕЛЫМИ", "«Вы»", "МЕХАНИЗМОМ", "НЕ трогай то, на что не жаловались"):
        assert must in sw.BLOCKERS_FIX, must
    assert "footer.md" in sw.BLOCKERS_FIX, "футер по памяти выходит не тот — нужен дословный"


def test_repair_reports_whether_the_draft_was_saved():
    """В канал уходит драфт с диска, а не ответ модели: панель обязана знать правду."""
    src = inspect.getsource(sw.fix_blockers)
    assert "_newest_draft_stamp()" in src and "return (post or fixed), False" in src


# ── обложка: пустой пул больше не приговор ──────────────────────────────────────────────────────

def test_empty_pool_triggers_a_second_search():
    src = inspect.getsource(sw)
    i = src.index("пул пуст (страницы ничего не отдали)")
    assert "_second_cover_round" in src[i:i + 400], "при пустом пуле второй круг поиска не запускается"


def test_cover_has_three_vision_rounds_and_a_fallback():
    """Фото → полотно бренда → иллюстрация про повод, и слепой фолбэк как последний рубеж."""
    src = inspect.getsource(sw)
    assert "СНЯТУЮ КАМЕРОЙ ФОТОГРАФИЮ" in src
    assert "ФИРМЕННОЕ ПОЛОТНО БРЕНДА" in src
    assert sw._BLIND_FALLBACK, "слепой фолбэк снят — обложка перестала быть гарантированной"


def test_cover_doubt_keeps_the_picture():
    """Правило 07.09 «картинка всегда»: любая сверка при сомнении ОСТАВЛЯЕТ обложку."""
    assert ct._same_topic_draft("", "2026-09-17-x-scope.md")
    assert ct._same_topic_draft("2026-09-17-scope.md", "2026-09-17-fix-scope.md")


# ── формат v3 целиком ───────────────────────────────────────────────────────────────────────────

def test_v3_format_is_enforced_end_to_end():
    """Всё, что владелец назвал правилом, обязано ловиться кодом, а не жить просьбой в промпте."""
    checks = {
        "длина 800-1500": ct.SCOPE_TOTAL_MIN == 800 and ct.SCOPE_TOTAL_CAP == 1500,
        "обращение на Вы": bool(ct._TY_ADDRESS),
        "обзор токена": ct._TOKENOMICS_MIN == 3,
        "ответ без вопроса": bool(ct._FALSE_ANSWER),
        "финал не простыня": ct._FINALE_LONG == 150,
        "гейт публикации": callable(ct.publish_blockers),
    }
    missing = [k for k, v in checks.items() if not v]
    assert not missing, f"правила v3 без кода: {missing}"


def test_all_blockers_are_reachable_from_the_linter():
    """Запрет, который линтер не выдаёт, никогда не сработает — проверяем, что формулировки совпали."""
    src = inspect.getsource(ct._lint)
    for mark in ct._PUBLISH_BLOCKERS:
        assert mark in src or mark in inspect.getsource(ct._finale_defects), f"запрет-сирота: {mark}"


# ── повторные попытки вместо отказа (16.09) ─────────────────────────────────────────────────────

def test_writer_failure_gets_one_retry():
    """Писатель падает почти всегда по внешней причине — сеть, 429, таймаут. До этого любой сбой
    означал день без поста."""
    src = open(rp.__file__, encoding="utf-8").read()
    assert "Пробую ещё раз" in src
    assert "и со второй попытки" in src, "второй сбой обязан честно завершать прогон"
    assert 'panel["♻️ писатель"]' in src


def test_unsaved_draft_gets_one_retry():
    """Частая причина «нет драфта» — модель выдала пост текстом и не вызвала save_draft. Для
    конвейера это неотличимо от отказа писать, а отказываться нельзя (правило 22.07)."""
    src = open(rp.__file__, encoding="utf-8").read()
    assert "НЕ СОХРАНИЛ ДРАФТ" in src and "nudge=" in src
    from core import scope_writer
    assert "nudge" in inspect.signature(scope_writer.write).parameters


def test_replacement_topic_is_checked_too():
    """Судья понятия смотрел только ПЕРВЫЙ выбор — замена уходила непроверенной."""
    src = inspect.getsource(rp._choose_scope_topic)
    assert src.count("concept_repeat") >= 2, "замена темы не проверяется судьёй понятия"
    assert "И замена повторяет понятие" in src


def test_second_check_does_not_loop():
    """Третьего круга нет намеренно: на бедном брифе можно ходить бесконечно."""
    src = inspect.getsource(rp._choose_scope_topic)
    assert src.count("concept_repeat") == 2, "появился третий круг — это риск зацикливания"


# ── дубль в очереди и кривой заголовок (17.09) ──────────────────────────────────────────────────

def test_duplicate_of_a_queued_post_is_refused():
    """Финальный прогон положил в отложку ВТОРОЙ пост с тем же заголовком. Чек «уже написано» его
    пропустил закономерно: он сверяет ИМЕНА СОБСТВЕННЫЕ, а у темы их нет вовсе («H.R. 8957» именем
    не разбирается) — она вся на русских нарицательных. Сверяем ГОТОВЫЙ ТЕКСТ с очередью: это не
    зависит ни от языка, ни от формулировки. Порог 0.45 — замер: максимальное совпадение между
    РАЗНЫМИ принятыми постами канала 0.25."""
    src = open(rp.__file__, encoding="utf-8").read()
    assert "В ОТЛОЖКЕ УЖЕ ЛЕЖИТ" in src
    assert "0.45" in src
    i_dup, i_sched = src.index("В ОТЛОЖКЕ УЖЕ ЛЕЖИТ"), src.index("[3/3] Ставлю в отложенные")
    assert i_dup < i_sched, "сверка с очередью обязана идти ДО постановки"


def test_duplicate_check_has_no_repair_round():
    """Дубль не чинится правкой: пост уже написан, и он дубль. Честный отказ."""
    src = open(rp.__file__, encoding="utf-8").read()
    after = src[src.index("В ОТЛОЖКЕ УЖЕ ЛЕЖИТ"):]
    assert "fix_blockers" not in after[:600]


def test_speech_reader_checks_the_headline_first():
    """Заголовок — самая читаемая строка и самый машинный элемент (post_lessons 22.06), а читатель
    речи его не упоминал вовсе. Брак 17.09: «доказывать свои биткоины» — глагол не берёт такой
    объект. Владелец: «заголовок точно говно»."""
    from core import scope_writer as sw
    assert "ЗАГОЛОВОК" in sw.SPEECH_READ
    assert "доказывать" in sw.SPEECH_READ, "разбор реального брака из промпта пропал"
    assert sw.SPEECH_READ.index("ЗАГОЛОВОК") < 200, "проверка заголовка обязана идти ПЕРВОЙ"
