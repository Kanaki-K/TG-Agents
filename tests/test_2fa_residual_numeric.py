"""ОСТАТОЧНАЯ ЦИФРА ПОСЛЕ ВТОРОЙ ВЕБ-СВЕРКИ (14.09.2026) — пост BitMine.

ЗАЧЕМ. Вторая сверка нашла «около 12-13% всего застейканного эфира» при проверенных 11.8%. Это не красная
линия и не механика, поэтому пайплайн ушёл в ветку «остался числовой нюанс — публикую», и цифра уехала в
отложку нетронутой. Теперь один прицельный круг и проверка кодом, что фраза изменилась.
Запуск: python -m pytest tests/test_2fa_residual_numeric.py"""
from __future__ import annotations

import inspect

import run_pipeline as rp
from core import verify

SV2 = ("✅ «BitMine на 13 сентября держит 5.96 млн ETH» — совпадает\n"
       "⚠️ «около 12-13% всего застейканного эфира» — точное verified-значение 11.8%, диапазон завышен\n"
       "❓ «прошлый крупный расстейк ~1.6 млн ETH / 46 дней» — это сентябрь 2025, проверь формулировку\n"
       "- ⚠️ «около 12-13% всего застейканного эфира» — повтор в итоговом списке\n"
       "ИТОГ: 7✅ / 1⚠️ / 1❓\nСТАТУС: ПРАВКИ")


def test_real_verdict_14_09_gives_one_numeric_target():
    assert verify.numeric_targets(SV2) == ["около 12-13% всего застейканного эфира"]


def test_unverified_and_completeness_are_not_targets():
    v = ("❓ «дивиденд платят еженедельно» — не подтверждено\n"
         "⚠️ «три оператора» — ряд неполон, источники называют пятерых\nСТАТУС: ПРАВКИ")
    assert "дивиденд платят еженедельно" not in verify.numeric_targets(v)


def test_fixed_phrase_is_no_longer_left():
    before = "Это около 12-13% всего застейканного эфира в руках одной компании"
    after = "Это почти 12% всего застейканного эфира в руках одной компании"
    t = verify.numeric_targets(SV2)
    assert verify.targets_left(before, t) == t
    assert verify.targets_left(after, t) == []


def test_pipeline_fixes_residual_numeric_instead_of_silent_publish():
    src = inspect.getsource(rp)
    i = src.index("verify.numeric_targets(sv2)")
    assert src.index("scope_writer.fix_facts", i) < src.index("остался числовой нюанс/формулировка", i)
