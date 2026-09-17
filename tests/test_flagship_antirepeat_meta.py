"""АНТИ-ПОВТОР И МЕТА ФЛАГМАНА (17.09.2026) — две дыры, найденные на прогоне про сеть Arc.

ЗАЧЕМ. 17.09 флагман вышел третьим заходом на одно событие: #472 от 05.08 в канале («Сеть Circle
обслуживают те же, кто в неё вложил деньги»), три скоуп-черновика 16.09 и сам флагман 17.09.
Владелец: «анти-повтор должен быть и у скоупа, и у флагмана, не важно чей, но ловить должен при том
и том прогоне».

ЧТО ПОКАЗАЛ АУДИТ КОДА:
  1. `_recent_made_titles()` (отложка + черновики ОБОИХ форматов) вычислялся ВНУТРИ ветки скоупа —
     флагман не видел ни вчерашних черновиков, ни очереди публикации;
  2. `avoid` у флагмана был МЁРТВЫМ параметром: принимался `_run_creator` и нигде не использовался;
  3. кодовых проверок повтора у флагмана не было вообще — только просьба в промпте пикера, а тема из
     банка проверялась метками [вышло]; сам УГОЛ пикер сочинял из свежего брифа Скаута и не сверял
     ни с чем;
  4. мета §7.9 ([[УЗЕЛ]]/[[ТИП]]/[[ВЫХОД]]) не писалась НИ РАЗУ: 40 записей журнала подряд с пустым
     `service`, то есть ротация типов услуги работала вслепую всё своё существование.

Запуск: python -m pytest tests/test_flagship_antirepeat_meta.py"""
from __future__ import annotations

import inspect
import json

import run_pipeline as RP
from core import creator_bot, creator_tools as ct, published_journal as PJ, topic_gate

FLAGSHIP = """**🌐 Почему Уолл-стрит строит на эфире**

16 сентября Circle включила Arc - сеть для расчётов в USDC

Среди 11 валидаторов BlackRock, Visa, DTCC

🖥 [Канал](https://t.me/x)
"""


# ── 1. Список «уже сделано» — общий для обоих форматов ──────────────────────────────────────────

def test_recent_is_computed_before_the_branch():
    """Реальная дыра 17.09: список жил внутри `if scope:` и до флагмана не доезжал."""
    src = inspect.getsource(RP.run_cycle)
    assert "_recent = _recent_made_titles()" in src
    assert src.index("_recent = _recent_made_titles()") < src.index("    if scope:"), \
        "список «уже сделано» снова считается только в ветке скоупа"


def test_avoid_reaches_the_flagship_writer():
    """`avoid` был мёртвым параметром: приходил в _run_creator и никуда не шёл."""
    src = inspect.getsource(RP._run_creator)
    assert "УЖЕ НАПИСАНО И ЖДЁТ ВЫХОДА" in src and "if avoid else" in src


def test_avoid_is_set_for_both_formats():
    """Отступ = принадлежность ветке: 4 пробела — тело run_cycle, 8 — снова «только для скоупа»."""
    line = next(l for l in inspect.getsource(RP.run_cycle).splitlines()
                if 'avoid = "; ".join(_recent[:6])' in l)
    assert len(line) - len(line.lstrip()) == 4, "avoid снова собирается внутри ветки скоупа"


# ── 2. Лестница анти-повтора у флагмана ─────────────────────────────────────────────────────────

def test_flagship_has_a_code_gate_not_a_request():
    src = inspect.getsource(RP.run_cycle)
    assert "topic_gate.already_written(probe, _recent)" in src, "нет детерминированной проверки"
    assert "topic_gate.concept_repeat(probe" in src, "нет судьи понятия"


def test_second_repeat_drops_the_angle():
    """Повод повторился дважды — пишем от темы: флагману новостной угол не обязателен."""
    src = inspect.getsource(RP.run_cycle)
    assert 'theme_angle = ""' in src.split("for _round in (1, 2):")[1][:1400]


def test_picker_takes_recent_and_forbid():
    sig = inspect.signature(RP._pick_timely_theme)
    assert "recent" in sig.parameters and "forbid" in sig.parameters
    src = inspect.getsource(RP._pick_timely_theme)
    assert "УЖЕ НАПИСАНО И ЖДЁТ ВЫХОДА" in src and "ПРОШЛЫЙ ВЫБОР ОТКЛОНЁН КОДОМ" in src


def test_real_case_17_09_would_be_caught():
    """Замок на живом случае: гист вчерашнего скоуп-черновика против сегодняшнего угла флагмана."""
    draft = (ct.DRAFTS_DIR / "2026-09-16-circle-arc-scope.md")
    if not draft.exists():          # черновики локальные — на чужой машине тест не падает
        return
    gist = RP._post_gist(draft.read_text(encoding="utf-8"))
    probe = "Стейблкоины — Circle включила сеть Arc, среди валидаторов BlackRock и DTCC"
    assert topic_gate.already_written(probe, [gist]), "дубль Arc снова прошёл бы молча"


# ── 3. Мета флагмана ────────────────────────────────────────────────────────────────────────────

def test_missing_meta_is_a_defect():
    assert ct.flagship_meta_defects(FLAGSHIP)


def test_full_meta_is_clean():
    ok = FLAGSHIP + ("\n\n[[SPLIT]]\n[[УЗЕЛ]] деньги в сети важнее цены её токена\n"
                     "[[ТИП]] линза\n[[ВЫХОД]] смотреть на объём стейблкоинов сети, а не на курс токена")
    assert ct.flagship_meta_defects(ok) == []


def test_type_must_be_from_the_list():
    bad = FLAGSHIP + "\n\n[[SPLIT]]\n[[УЗЕЛ]] деньги в сети важнее цены токена\n[[ТИП]] аналитика\n[[ВЫХОД]] смотреть на объём стейблкоинов сети"
    assert any("не из списка" in d for d in ct.flagship_meta_defects(bad))


def test_exit_of_knowledge_verbs_is_illusion():
    bad = FLAGSHIP + "\n\n[[SPLIT]]\n[[УЗЕЛ]] деньги в сети важнее цены токена\n[[ТИП]] линза\n[[ВЫХОД]] читатель узнает про стейблкоины на эфире"
    assert any("иллюзия знания" in d for d in ct.flagship_meta_defects(bad))


def test_honest_no_exit_is_accepted():
    ok = FLAGSHIP + "\n\n[[SPLIT]]\n[[УЗЕЛ]] деньги в сети важнее цены токена\n[[ТИП]] линза\n[[ВЫХОД]] выхода нет: пост даёт понимание, не защиту"
    assert ct.flagship_meta_defects(ok) == []


def test_meta_round_is_wired_and_does_not_touch_the_body():
    src = inspect.getsource(RP.run_cycle)
    assert "creator_tools.flagship_meta_defects" in src
    assert "ни слова, ни цифры, ни заголовка не трогай" in creator_bot.FIX_META


# ── 4. Ротация типов услуги получает данные даже без меты ───────────────────────────────────────

def test_service_falls_back_to_the_picker(tmp_path, monkeypatch):
    monkeypatch.setattr(PJ, "JOURNAL", tmp_path / "j.jsonl")
    PJ.record("тело поста", "тема", kind="flagship", service="линза")
    e = json.loads((tmp_path / "j.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert e["service"] == "линза"


def test_meta_type_wins_over_the_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(PJ, "JOURNAL", tmp_path / "j.jsonl")
    PJ.record("тело\n\n[[SPLIT]]\n[[ТИП]] инструмент", "тема", kind="flagship", service="линза")
    e = json.loads((tmp_path / "j.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert e["service"] == "инструмент"


def test_pipeline_passes_the_picked_type_to_the_journal():
    src = inspect.getsource(RP.run_cycle)
    assert 'service=meas.get("тип услуги", "")' in src
