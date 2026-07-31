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


# --- красная линия не должна зависеть от оформления (баг 31.07: выдумка ушла в канал) ---

def test_redline_catches_bold_wrapped_warning():
    # РЕАЛЬНЫЙ вердикт 31.07: строка начиналась с `**`, проверка требовала ⚠ первым символом →
    # снос не запустился, и непроверённая атрибуция осталась в опубликованном посте
    v = ("**⚠️ АТРИБУЦИЯ: «сам Coinkite делал AI-аудит за несколько недель до»** — не прослеживается "
         "ни в брифе, ни в вебе. Репутационный риск - убрать\nИТОГ: 9✅ / 4⚠️ / 0❓\nСТАТУС: ПРАВКИ")
    assert verify.has_redline(v) is True
    assert verify.has_issues(v) is True


def test_redline_catches_warning_inside_table_row():
    # в итоговой таблице значок стоит в третьей колонке, а не в начале строки
    v = "| 11 | АТРИБУЦИЯ: Coinkite сам делал AI-аудит | ⚠️ не прослеживается - убрать |"
    assert verify.has_redline(v) is True


def test_bullet_and_numbered_warnings_count_as_issues():
    assert verify.has_issues("- ⚠️ цифра расходится") is True
    assert verify.has_issues("1. ⚠️ цифра расходится") is True
    assert verify.has_issues("> **⚠️** цифра расходится") is True


def test_plain_numeric_line_is_not_a_warning():
    # строка, начинающаяся с цифр, не должна превращаться в конфликт после снятия мишуры
    assert verify.has_issues("594 BTC выведено - совпадает с источником") is False


def test_redline_ignores_lines_without_marker():
    v = "⚠️ «1.5 млрд$» — реально 1.76 млрд$\nИТОГ: 8✅ / 1⚠️ / 0❓\nСТАТУС: ПРАВКИ"
    assert verify.has_redline(v) is False      # числовой конфликт чинится подстановкой, это не выдумка


# --- ПОЛНОТА поста-инструкции: неполный список затронутых = красная линия ---

def test_incomplete_scope_reads_as_redline():
    # 2FA обязан пометить недостающую затронутую модель словом-маркером, чтобы конвейер снёс/поправил,
    # а не отправил владельцу «мелким нюансом» (случай Coldcard 31.07: пост назвал только Mk3)
    v = ("⚠️ «Mk3 с firmware 4.0.1+» — не подтверждено, что затронут ТОЛЬКО Mk3: источники называют "
         "также Mk4, Mk5 и Q\nИТОГ: 8✅ / 1⚠️ / 0❓\nСТАТУС: ПРАВКИ")
    assert verify.has_redline(v) is True
    assert verify.has_issues(v) is True
