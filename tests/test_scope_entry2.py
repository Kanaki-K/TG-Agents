"""ВХОД 2 «МЕХАНИЗМ» — доделка v3 скоупа (16.09.2026).

ЗАЧЕМ. v2 (10.09) дала скоупу два входа и была права: с одним входом в слабый день рождается пересказ.
14.09 вход 2 сняли — но не потому, что он плох, а потому, что гейт по нему ВЫДУМЫВАЛ механизм и склеивал
его из шапки брифа («три решающих события недели»). Обе причины теперь держит код: splice_problem не даёт
взять тему вне направлений брифа, фильтр 0 режет рутинное макро.

Итог одного входа владелец сформулировал 16.09: «я блять как новостник уже». Замер того же дня: у
флагманов v1 свежая новость была входом лишь у 3 постов из 16 — остальные 13 заходили из истории или
вечного наблюдения; у скоупов кости «так уже было» нет НИ В ОДНОМ из 30.

Запуск: python -m pytest tests/test_scope_entry2.py"""
from __future__ import annotations

import inspect

import run_pipeline as rp
from core import scope_writer, topic_gate as tg

BRIEF = "## Направление 1 [Веб]\nОтток ETF\n\n## Направление 2 [X]\nСтоп-лоссы и карты ликвидности\n"


def _v(entry: str, date: str = "10.09.2026", direction: str = "2") -> str:
    return (f"НАПРАВЛЕНИЕ: {direction}\nВХОД: {entry}\n"
            "ВЫБРАН: «Где Вы сами оставляете след — карты ликвидности и охота за стопами»\n"
            f"ДАТА ДЕЙСТВИЯ: {date}\nПОВТОР: нет\nЧТО НОВОГО: —\n"
            "ПОЛЬЗА: читатель поймёт, почему его выбило\nСЛАБО: нет\nИСЧЕРПАНО: нет\nОФФ-БРЕНД: нет")


# ── разбор поля ─────────────────────────────────────────────────────────────────────────────────

def test_entry_kind_reads_the_field():
    assert tg.entry_kind(_v("механизм")) == "механизм"
    assert tg.entry_kind(_v("сдвиг")) == "сдвиг"


def test_missing_field_falls_back_to_strict():
    """Старый вердикт без поля ВХОД → «сдвиг»: свежесть продолжает действовать, как раньше."""
    assert tg.entry_kind("ВЫБРАН: «что-то»\nДАТА ДЕЙСТВИЯ: 01.01.2026") == "сдвиг"
    assert tg.entry_kind("") == "сдвиг"


def test_markdown_wrapped_entry_still_reads():
    assert tg.entry_kind(_v("механизм").replace("ВХОД: механизм", "**ВХОД: механизм**")) == "механизм"


# ── свежесть: главное механическое отличие входа 2 ──────────────────────────────────────────────

def test_stale_action_does_not_trigger_rescout_on_entry_2():
    """Механизм живёт дольше новости — гонять Скаута за свежим поводом бессмысленно и дорого."""
    assert rp._topic_shortfall(_v("механизм", date="01.08.2026"), "повод", BRIEF) == ""


def test_stale_action_still_triggers_rescout_on_entry_1():
    """Вход 1 остаётся строгим: протухший сдвиг — это старая новость, за такое гнали и гоним."""
    why = rp._topic_shortfall(_v("сдвиг", date="01.08.2026"), "повод", BRIEF)
    assert "старше" in why


def test_other_safeguards_still_fire_on_entry_2():
    """Вход 2 не должен быть лазейкой: склейка, пустой выбор и офф-бренд ловятся так же."""
    spliced = _v("механизм").replace(
        "«Где Вы сами оставляете след — карты ликвидности и охота за стопами»",
        "«Три решающих события недели»")
    assert tg.splice_problem(spliced, BRIEF), "склейка обязана ловиться и на входе 2"
    # ⚠️ Флаги контракта (_flag) читаются по ПЕРВОМУ вхождению, в отличие от полей (ВЫБРАН/ПОЛЬЗА —
    # по последнему). Поэтому подменяем строку, а не дописываем вторую.
    offbrand = _v("механизм").replace("ОФФ-БРЕНД: нет", "ОФФ-БРЕНД: да")
    assert rp._topic_shortfall(offbrand, "повод", BRIEF), "бренд-вето обязано работать и на входе 2"
    exhausted = _v("механизм").replace("ИСЧЕРПАНО: нет", "ИСЧЕРПАНО: да")
    assert rp._topic_shortfall(exhausted, "повод", BRIEF), "«годного повода нет» работает и на входе 2"


def test_invented_theme_is_still_blocked_on_entry_2():
    """Запрет №1 входа 2: механизм не выдумывается — он из направления брифа."""
    assert tg.splice_problem(_v("механизм", direction="9"), BRIEF)


# ── контракт и свод ─────────────────────────────────────────────────────────────────────────────

def test_contract_declares_both_entries():
    for must in ("ВХОД 1 — СДВИГ", "ВХОД 2 — МЕХАНИЗМ", "ВХОД: <сдвиг | механизм>"):
        assert must in tg._SYSTEM, must


def test_contract_carries_the_three_bans():
    assert "МЕХАНИЗМ НЕ ВЫДУМЫВАЕТСЯ" in tg._SYSTEM
    assert "привязки к моменту рынка" in tg._SYSTEM
    assert "Рутинное макро — стоп на ОБОИХ входах" in tg._SYSTEM


def test_freshness_block_is_scoped_to_entry_1():
    assert "на входе 2 не применяется" in tg._SYSTEM


def test_manual_has_both_entries_and_the_history_bone():
    from core import config
    manual = (config.ROOT / "memory" / "scope_manual.md").read_text(encoding="utf-8")
    assert "ВХОД 2 — МЕХАНИЗМ" in manual
    assert "ТАК УЖЕ БЫЛО" in manual, "кость истории — то, чего нет ни в одном из 30 скоупов"
    assert "2800–4096" in manual, "в таблице сравнения осталась длина флагмана из v2.1"


# ── проводка до писателя ────────────────────────────────────────────────────────────────────────

def test_writer_is_told_which_entry():
    assert "entry" in inspect.signature(scope_writer.write).parameters
    src = inspect.getsource(scope_writer.write)
    assert "ВХОД 2 — МЕХАНИЗМ" in src and "ТАК УЖЕ БЫЛО" in src


def test_pipeline_passes_entry_to_the_writer():
    src = open(rp.__file__, encoding="utf-8").read()
    assert "topic_gate.entry_kind(tg_verdict)" in src
    assert 'panel["🚪 вход"]' in src


def test_history_bone_must_not_be_invented():
    """Выдуманный прецедент хуже отсутствующего — правило 29.07 действует и здесь."""
    src = inspect.getsource(scope_writer.write)
    assert "ВЫДУМЫВАТЬ НЕЛЬЗЯ" in src
