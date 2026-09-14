"""ВЫБОР ТЕМЫ SCOPE V3 (14.09.2026): ловушки нет, первый фильтр — деньги криптана, склейка = стоп.

ЗАЧЕМ. Прогон 14.09 отклонил свежие поводы «нет драмы», ушёл во вход 2 «ловушка» и склеил тему из шапки
брифа: «Три макро-триггера на одной неделе» (Clarity Act + ФРС + Банк Японии). Владелец забраковал пост
целиком («сплетено 3 в 1, мнимая тревога, ФРС скучно»), а следом и Robinhood/AMC («криптану хуй пойми
зачем»). Каждая проверка ниже — место, через которое этот брак прошёл.
Запуск: python -m pytest tests/test_topic_gate_v3.py"""
from __future__ import annotations

import inspect

import run_pipeline as rp
from core import scope_writer, topic_gate as tg, verify

BRIEF = ("# Разведка 14.09.2026\n**Сигнал недели:** три одновременных макро-триггера\n\n"
         "## Направление 1 [Веб/TG]\nИндия Demat 2.0\n\n"
         "## Направление 2 [X/Веб]\nKaiko $110M\n\n"
         "## Направление 3 [X + TG/Веб]\nClarity Act\n")


def _v(choice: str, direction: str = "1", tail: str = "ИСЧЕРПАНО: нет\nОФФ-БРЕНД: нет") -> str:
    return f"НАПРАВЛЕНИЕ: {direction}\nВЫБРАН: «{choice}»\nСЛАБО: нет\n{tail}"


# ── склейка ─────────────────────────────────────────────────────────────────────────────────────

def test_real_choice_14_09_is_caught_as_a_splice():
    v = _v("Три макро-триггера на одной неделе (Clarity Act, ФРС, Банк Японии)", "3")
    assert "склеена" in tg.splice_problem(v, BRIEF)


def test_other_splice_wordings():
    for theme in ("Два события недели бьют по рынку", "Сразу три повода занервничать",
                  "Несколько крупных новостей за одну неделю"):
        assert tg.splice_problem(_v(theme), BRIEF), theme


def test_single_event_passes():
    assert tg.splice_problem(_v("Индия выпустила облигации на DLT с расчётом в CBDC"), BRIEF) == ""
    # «два» рядом не с событием — не склейка: живой конфликт двух людей это ОДНО событие
    assert tg.splice_problem(_v("Два CEO сцепились из-за токенов", "2"), BRIEF) == ""


def test_direction_must_be_one_real_number():
    assert "несколько" in tg.splice_problem(_v("Индия", "1, 3"), BRIEF)
    assert "нет" in tg.splice_problem(_v("Индия", "7"), BRIEF)
    assert "не назван" in tg.splice_problem("ВЫБРАН: «Индия»\nСЛАБО: нет", BRIEF)


def test_brief_without_marked_directions_is_fail_open():
    assert tg.splice_problem("ВЫБРАН: «Индия»", "бриф старого формата без заголовков") == ""


def test_empty_choice_is_not_judged_here():
    assert tg.splice_problem("(выбор темы не удался: сеть)", BRIEF) == ""


# ── промпт суда ─────────────────────────────────────────────────────────────────────────────────

def test_holder_money_check_goes_first_and_cuts():
    s = tg._SYSTEM
    assert "ПРО ДЕНЬГИ КРИПТАНА (ОТСЕКАЮЩАЯ" in s
    assert s.index("ПРО ДЕНЬГИ КРИПТАНА") < s.index("── 1. СВЕЖЕСТЬ")
    assert "Robinhood/AMC" in s                     # красивая чужая драма — пример отсечения


def test_routine_macro_is_a_stop_and_fed_is_not_a_hero():
    s = tg._SYSTEM
    assert "РУТИННОЕ МАКРО — СТОП" in s
    assert "Баффет, ФРС" not in s                   # ФРС стояла примером ГЕРОЯ — против канона бренда


def test_drama_ranks_but_does_not_veto():
    s = tg._SYSTEM
    assert "НЕ ВЕТО" in s
    assert "повод НЕ БЕРИ, каким бы важным" not in s


def test_trap_entry_is_gone():
    assert "ЛОВУШК" not in tg._SYSTEM.upper()
    assert not hasattr(tg, "parse_mode")


# ── писатель и 2FA ──────────────────────────────────────────────────────────────────────────────

def test_writer_has_no_trap_mode():
    assert "mode" not in inspect.signature(scope_writer.write).parameters
    assert "ЛОВУШКА" not in inspect.getsource(scope_writer.write)
    assert "trap" not in inspect.signature(verify.verify_post).parameters


def test_writer_is_told_one_event(monkeypatch):
    seen = {}
    monkeypatch.setattr(scope_writer, "_turn", lambda task, *a, **kw: seen.setdefault("task", task) or "")
    monkeypatch.setattr(scope_writer, "_newest_draft_stamp", lambda: "same")
    monkeypatch.setattr(scope_writer.config, "load_agent", lambda *_a, **_k: {})
    monkeypatch.setattr(scope_writer.config, "agent_api_key", lambda *_a, **_k: "k")
    scope_writer.write(recommend="Индия выпустила облигации на DLT")
    assert "ОДИН ПОВОД = ОДНО СОБЫТИЕ" in seen["task"]


# ── конвейер ────────────────────────────────────────────────────────────────────────────────────

def _fake_select(monkeypatch, verdicts: list[str]) -> list[dict]:
    calls: list[dict] = []

    def select(brief, **kw):
        calls.append(kw)
        v = verdicts[min(len(calls), len(verdicts)) - 1]
        theme, weak = tg.parse_choice(v)
        return theme, weak, v

    monkeypatch.setattr(rp.topic_gate, "select", select)
    monkeypatch.setattr(rp.verify, "latest_brief", lambda *a, **k: BRIEF)
    return calls


def test_splice_triggers_one_reselect_with_the_reason(monkeypatch):
    calls = _fake_select(monkeypatch, [_v("Три макро-триггера на одной неделе", "3"),
                                       _v("Индия выпустила облигации на DLT", "1")])
    panel: dict = {}
    rec, _, _ = rp._choose_scope_topic("k", [], panel, lambda s="": None)
    assert rec.startswith("Индия") and len(calls) == 2
    assert "склеена" in calls[1]["forbid_why"]
    assert "🧵 склейка" in panel


def test_good_choice_is_not_reselected(monkeypatch):
    calls = _fake_select(monkeypatch, [_v("Индия выпустила облигации на DLT", "1")])
    rp._choose_scope_topic("k", [], {}, lambda s="": None)
    assert len(calls) == 1


def test_shortfall_reasons():
    assert rp._topic_shortfall(_v("Индия"), "Индия", BRIEF) == ""
    exhausted = _v("Индия", tail="ИСЧЕРПАНО: да\nОФФ-БРЕНД: нет")
    assert "нет" in rp._topic_shortfall(exhausted, "Индия", BRIEF)
    spliced = _v("Три события недели", "3")
    assert "склеена" in rp._topic_shortfall(spliced, "Три события недели", BRIEF)
    # сбой API — не повод гонять Скаута: он модель не починит, а деньги сожжёт
    assert rp._topic_shortfall("(выбор темы не удался: timeout)", "", BRIEF) == ""
    assert rp._topic_shortfall("ВЫБРАН:\nСЛАБО: нет", "", BRIEF)


def test_wider_scan_note_carries_rejected_and_the_bans():
    v = (_v("Три события недели", "3", tail="ОТКЛОНЕНО: «Индия Demat 2.0» — нет драмы; «Kaiko» — корпоративная "
                                          "новость\nИСЧЕРПАНО: да\nОФФ-БРЕНД: нет"))
    note = rp._wider_scan_note(v, "годного повода в брифе нет")
    assert "до 8 направлений" in note
    assert "Индия Demat 2.0" in note and "Kaiko" in note and "Три события недели" in note
    assert "ФРС" in note and "склейку" in note


def test_second_scout_round_no_longer_requires_scout_not_run():
    """14.09 Скаут уже бегал, поэтому второй круг не включился — и гейт выдумал тему."""
    src = inspect.getsource(rp)
    assert "and not scout_ran and not skip_scout" not in src
    assert "_run_scout(_wider_scan_note(" in src
