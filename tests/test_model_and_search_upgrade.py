"""АПГРЕЙД МОДЕЛИ И ВЕБ-ПОИСКА (16.09.2026) — аудит утилитарных механизмов.

ЗАЧЕМ. Аудит 16.09 нашёл два устаревания, которые било по качеству письма, а не по чистоте кода:

1. ПИСАТЕЛЬ НА ПРОШЛОМ ПОКОЛЕНИИ. SCOPE_MODEL стоял claude-opus-4-8, при том что Opus 5 стоит РОВНО
   столько же ($5/$25 за 1M). На этой роли тир решает всё: чужие проходы-редакторы сняты 31.07,
   вытянуть подачу может только сам автор.
   ⚠️ Переезд не механический: у скоупа мышление выключено, а на Opus 5 явное `disabled` даёт два
   известных сбоя — модель пишет ВЫЗОВ ИНСТРУМЕНТА текстом вместо блока tool_use (ход успешен,
   вызова нет, ошибки нет) и подтекает тегами <thinking>. Для завода первый критичен: пост попадает
   на диск ТОЛЬКО через save_draft. Лечение — адаптивное мышление на НИЗКОМ усилии.

2. ВЕБ-ПОИСК ВЕРСИИ МАРТА 2025 в шести местах. У текущего (web_search_20260209) есть динамическая
   фильтрация выдачи — прямо про нашу боль «получался пересказ пресс-релиза» (22.07). Но живёт он
   только на Opus 4.6+/Sonnet 4.6+, а /test и MODEL_OVERRIDE подменяют роль на Haiku, где новый тип
   вернёт 400 на весь прогон. Поэтому вариант выбирается ПО МОДЕЛИ в момент вызова.

Запуск: python -m pytest tests/test_model_and_search_upgrade.py"""
from __future__ import annotations

import inspect

from core import creator_tools as ct, llm, scope_writer as sw, topic_gate as tg


# ── модель писателя ─────────────────────────────────────────────────────────────────────────────

def test_scope_writer_is_on_current_generation():
    assert sw.SCOPE_MODEL == "claude-opus-5"


def test_gate_and_judges_stay_cheap():
    """Тир решает у ПИСАТЕЛЯ. Механические роли на Sonnet не трогаем — там он ничего не решал."""
    assert tg.GATE_MODEL == "claude-sonnet-5"
    assert sw.SPEECH_MODEL == "claude-sonnet-5"
    assert sw.ECHO_MODEL == "claude-sonnet-5"


def test_opus5_never_gets_disabled_thinking():
    """Главный предохранитель: на Opus 5 «disabled» роняет вызовы инструментов в текст."""
    assert llm._disabled_think_risky("claude-opus-5")
    assert not llm._disabled_think_risky("claude-opus-4-8")
    assert not llm._disabled_think_risky("claude-sonnet-5")


def test_no_think_role_on_opus5_gets_adaptive_low_effort():
    """Роль без мышления на Opus 5 должна получить адаптивное + низкое усилие, а не disabled."""
    src = inspect.getsource(llm.reply)
    assert '_disabled_think_risky(model)' in src
    assert '{"type": "adaptive"}' in src
    assert "_EFFORT_FOR_NO_THINK" in src
    assert llm._EFFORT_FOR_NO_THINK in ("low", "medium")


def test_older_models_still_get_disabled_thinking():
    """На Opus 4.8/Sonnet 5 поведение прежнее — «без мышления» надо говорить вслух (урок 10.09)."""
    src = inspect.getsource(llm.reply)
    assert '{"type": "disabled"}' in src, "фикс 10.09 про молчащий конфиг снесён"


def test_effort_is_pluggable():
    assert "effort" in inspect.signature(llm.reply).parameters


# ── веб-поиск ───────────────────────────────────────────────────────────────────────────────────

def test_modern_search_is_off_until_the_loop_can_carry_a_container():
    """ОТКАТ 16.09 по живому прогону. Новый вариант поиска фильтрует выдачу ЧЕРЕЗ ИСПОЛНЕНИЕ КОДА:
    ответ оставляет pending tool uses, и следующий шаг агентного цикла обязан нести container_id.
    Наш цикл его не возит → 400 на круге правок, пост не доехал до отложки.
    Тестом это не ловится — ошибку отдаёт только живой API, поэтому тест сторожит сам факт отката."""
    for model in ("claude-opus-5", "claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"):
        assert llm.web_search_tool(model)["type"] == "web_search_20250305", model


def test_modern_search_needs_container_plumbing_first():
    """Включать обратно можно только вместе с container_id в цикле — комментарий держит причину."""
    import inspect
    src = inspect.getsource(llm)
    assert "container_id" in src, "причина отката потеряна — включат снова и снова уронят прогон"


def test_max_uses_of_each_role_is_preserved():
    """У Скаута 4, у 2FA 1, у скоупа 5 — это настроенные числа, апгрейд их не трогает."""
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5},
             {"name": "save_draft"}]
    fixed = llm.fix_web_search(tools, "claude-opus-5")
    assert fixed[0]["max_uses"] == 5 and fixed[0]["type"] == "web_search_20250305"
    assert fixed[1] == {"name": "save_draft"}, "не-поисковые инструменты обязаны пройти нетронутыми"


def test_fix_is_applied_centrally_in_reply():
    """Роли объявляют поиск на импорте, модель известна только в вызове — чиним в одном месте."""
    assert "fix_web_search(tools_schema, model)" in inspect.getsource(llm.reply)


def test_fix_survives_empty_and_none():
    assert llm.fix_web_search([], "claude-opus-5") == []
    assert llm.fix_web_search(None, "claude-opus-5") == []


# ── чистка, найденная тем же аудитом ────────────────────────────────────────────────────────────

def test_dead_bank_helpers_are_gone():
    """dedup.bank_topics / pick_bank_theme не звал ни код, ни тесты — остатки старого пикера."""
    from core import dedup
    assert not hasattr(dedup, "bank_topics")
    assert not hasattr(dedup, "pick_bank_theme")
    assert hasattr(dedup, "available_bank_themes"), "живой помощник банка снесён по ошибке"


def test_contract_flags_read_the_last_occurrence():
    """Поля читались по последнему вхождению, флаги — по первому. Тихая мина: контракт велит
    выносить итог в конец, а разбор кандидатов выше пишется свободным текстом."""
    verdict = ("№1 🆕 «повод» — тут гейт рассуждает и пишет слово ИСЧЕРПАНО: нет\n"
               "ВЫБРАН: «повод»\nИСЧЕРПАНО: да\nОФФ-БРЕНД: нет")
    assert tg.is_exhausted(verdict), "итоговый флаг проигран разбору кандидатов выше"
    assert not tg.is_offbrand(verdict)


def test_paragraph_aim_matches_the_measurement():
    """Код говорил 120, свод — «~124 знака» по замеру 17 принятых постов. Теперь одно число."""
    assert ct.SCOPE_PARA_AIM == 124
    from core import config
    assert "124" in (config.ROOT / "memory" / "scope_manual.md").read_text(encoding="utf-8")


# ── диагностика петли само-обучения (восстановлена 16.09) ───────────────────────────────────────

def test_self_learn_check_runs_without_crashing(capsys):
    """Коммит ea10940 удалил три функции, а вызовы оставил — модуль падал NameError на первой
    строке main() и был мёртв всё это время. Никто не заметил: теста на диагностику не было.
    Тест простой намеренно — он ЗАПУСКАЕТ отчёт и требует, чтобы тот дошёл до конца."""
    from core import self_learn_check as slc
    for fn in ("_load_threads_posts", "_fresh_note", "_bank_distribution"):
        assert hasattr(slc, fn), f"{fn} снова потерян — модуль опять мёртв"
    slc.main()                                   # упадёт NameError, если вызов снова осиротеет
    out = capsys.readouterr().out
    assert "БАНК ТЕМ" in out and "ВЕСА ПИКЕРА" in out


def test_fresh_note_explains_immature_posts():
    """Балл None у свежего поста — это норма, и отчёт обязан сказать это словами, а не молчать."""
    from core import self_learn_check as slc
    from datetime import date
    assert "рано судить" in slc._fresh_note(date.today().isoformat())
    assert "нет зрелых данных" in slc._fresh_note("не-дата")
