"""Контракт 2FA (core/verify) — машинные поля вердикта решают, а не значки в тексте разбора.

Переработка 31.07: has_issues видел ⚠️ в начале любой строки и объявлял конфликт. Модель же помечает
значком пункт, разбирает его и тут же закрывает как ✅, а в итоге честно пишет «0⚠️ / СТАТУС: ЧИСТО» —
прогон 31.07 из-за этого сделал лишний круг «правка + полная веб-сверка» (~$0.5) и отправил владельцу
пометку «остался числовой нюанс» на чистом вердикте. Запуск: python -m pytest tests/test_verify_contract.py"""
from core import verify


def test_self_closed_warning_is_not_an_issue():
    # реальный вердикт 31.07: значок в разборе, но оба машинных поля говорят «чисто»
    v = ("⚠️ «продала 218.4 млн$» — цифра верна, уточнение лишь в мотиве. ✅ по цифре\n"
         "✅ «843,775 BTC» — пресс-релиз\n"
         "ИТОГ: 10✅ / 0⚠️ / 0❓\n"
         "СТАТУС: ЧИСТО")
    assert verify.has_issues(v) is False


def test_real_warning_still_blocks():
    v = ("⚠️ «1.5 млрд$» — реально 1.76 млрд$\n"
         "ИТОГ: 8✅ / 1⚠️ / 0❓\n"
         "СТАТУС: ПРАВКИ")
    assert verify.has_issues(v) is True


def test_status_clean_alone_does_not_whitewash():
    # одного «СТАТУС: ЧИСТО» мало — нужен и нулевой счётчик; иначе рассогласование = конфликт
    v = "⚠️ «1.5 млрд$» — реально 1.76 млрд$\nИТОГ: 8✅ / 1⚠️ / 0❓\nСТАТУС: ЧИСТО"
    assert verify.has_issues(v) is True


def test_counter_alone_does_not_whitewash():
    v = "⚠️ «1.5 млрд$» — расходится\nИТОГ: 8✅ / 0⚠️ / 0❓\nСТАТУС: ПРАВКИ"
    assert verify.has_issues(v) is True


def test_redline_stays_paranoid_even_when_tally_clean():
    # фабрикация — другая цена ошибки: тут послабление НЕ действует, значку верим всегда
    v = ("⚠️ «BlackRock — клиент» — участник НЕ подтверждён ни одним источником\n"
         "ИТОГ: 9✅ / 0⚠️ / 0❓\n"
         "СТАТУС: ЧИСТО")
    assert verify.has_redline(v) is True


def test_no_contract_lines_falls_back_to_marker():
    assert verify.has_issues("⚠️ цифра расходится") is True
    assert verify.has_issues("всё сошлось") is False
    assert verify.has_issues("") is False
