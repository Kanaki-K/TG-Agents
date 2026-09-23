"""Инструмент читателю — главный критерий после отсекающих (23.09.2026, критерий v1).

Флагманы v1 (16 из 16, приняты почти без правок) отдавали читателю проверку/правило/линзу для своих
денег; скоупы v3 — 7 из 30. Гейт ранжировал ДРАМУ выше пользы и 23.09 взял BitMEX, отклонив MVRV с
«докупать/держать». Реплей гейта после правки на том же брифе: 3 из 3 — не BitMEX, инструмент назван.
"""
import inspect

import run_pipeline as rp
from core import topic_gate as tg

BASE = "НАПРАВЛЕНИЕ: 1\nВЫБРАН: «X»\nСЛАБО: нет\n{tool}ИСЧЕРПАНО: нет\nОФФ-БРЕНД: нет"


def _v(tool_line: str) -> str:
    return BASE.format(tool=tool_line)


def test_named_tool_passes():
    v = _v("ИНСТРУМЕНТ: сверять цену с реализованной (MVRV) как индикатор фазы рынка\n")
    assert tg.no_tool(v) == "" and tg.parse_tool(v).startswith("сверять")


def test_missing_or_empty_or_knowledge_is_no_tool():
    for line in ("", "ИНСТРУМЕНТ: нет\n", "ИНСТРУМЕНТ: —\n",
                 "ИНСТРУМЕНТ: поймёт, как рынок деривативов сконцентрировался\n",
                 "ИНСТРУМЕНТ: читатель узнает историю BitMEX\n"):
        assert tg.no_tool(_v(line)), line


def test_last_field_wins_over_candidate_breakdown():
    v = "№1 … ИНСТРУМЕНТ: нет\n" + _v("ИНСТРУМЕНТ: проверять, кто держит ключи\n")
    assert tg.parse_tool(v) == "проверять, кто держит ключи"


def test_ranking_puts_tool_before_drama():
    sysp = tg._SYSTEM if hasattr(tg, "_SYSTEM") else inspect.getsource(tg)
    rank = sysp[sysp.index("КАК РАНЖИРОВАТЬ"):]
    assert rank.index("ИНСТРУМЕНТ") < rank.index("ДРАМЫ")
    assert "ИНСТРУМЕНТ: <" in sysp, "поле обязано быть в формате ответа"


def test_no_tool_reselects_but_never_leaves_the_day_empty():
    src = inspect.getsource(rp._choose_scope_topic)
    i = src.index("topic_gate.no_tool(verdict)")
    block = src[i:i + 1600]
    assert "topic_gate.select(" in block, "нет инструмента → пере-выбор"
    assert "rec, weak, verdict = _r0, _w0, _v0" in block, "замены нет → исходная тема, не пустой день"


def test_writer_gets_the_tool():
    assert "ИНСТРУМЕНТ ЧИТАТЕЛЮ (выбран гейтом): сверять" in rp._tool_note(
        _v("ИНСТРУМЕНТ: сверять цену с реализованной\n"))
    assert "гейт его не назвал" in rp._tool_note(_v(""))
    assert "_tool_note(tg_verdict)" in inspect.getsource(rp.run_cycle)
