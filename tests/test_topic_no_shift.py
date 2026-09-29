"""Гейт сам признал, что сдвига нет, — тему не берём (прогон 23.09.2026, BitMEX).

Гейт написал в СЛАБО: «анонс закрытия был два месяца назад, само событие скорее формальная точка, а не
сюрприз — вытянуть можно только философским углом» — и выбрал. Владелец переписал пост на 70%: «тема
не очень интересная, пользы от прочтения практически нет».
"""
import inspect

import run_pipeline as rp
from core import topic_gate as tg


def _verdict(weak: str) -> str:
    return f"НАПРАВЛЕНИЕ: 1\nВХОД: сдвиг\nВЫБРАН: «BitMEX закрылся»\nСЛАБО: {weak}\nИСЧЕРПАНО: нет\n"


def test_live_23_09_admission_is_caught():
    weak = ("анонс закрытия был два месяца назад (23.07), само событие сегодня скорее формальная точка, "
            "а не сюрприз — вытянуть можно только философским/структурным углом")
    assert tg.is_no_shift(_verdict(weak))


def test_ordinary_weakness_is_not_a_stop():
    for weak in ("цифра 57% не подтверждена агрегатором — брать с оговоркой",
                 "драма слабая, нет героя", "возраст 2д, свежесть на грани"):
        assert tg.is_no_shift(_verdict(weak)) == "", weak


def test_only_the_weak_field_counts():
    """Те же слова в разборе ОТКЛОНЁННЫХ кандидатов не должны снимать выбранную тему."""
    v = "Разбор:\n- №4 формальная точка, не сюрприз — отклонён\n" + _verdict("драма слабая")
    assert tg.is_no_shift(v) == ""


def test_pipeline_reselects_on_admission():
    src = inspect.getsource(rp._choose_scope_topic)
    assert "topic_gate.is_no_shift(verdict)" in src
    i = src.index("topic_gate.is_no_shift(verdict)")
    assert "topic_gate.select(" in src[i:i + 600], "признание обязано вести к пере-выбору, а не к записи в лог"
