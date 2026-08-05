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


# --- расхождение источников ≠ конфликт поста (вред 03.08) --------------------------------------

def test_contract_forbids_edit_when_sources_disagree():
    # 03.08 2FA потребовал заменить верные 215 млн$ на 206 из витрины-агрегатора, а на перепроверке
    # сам написал «все репутабельные источники дают 214.7-215». Верное число менять запрещено.
    for text in (verify.VERIFIER_SYSTEM, verify.SCOPE_SOURCE_CHECK):
        assert "РАСХОДЯТСЯ" in text.upper()
    assert "агрегатор" in verify.SCOPE_SOURCE_CHECK.lower()
    assert "ПЕРВОИСТОЧНИК" in verify.SCOPE_SOURCE_CHECK      # приоритет истины задан явно


def test_contract_checks_completeness_of_counting_thesis():
    # «две точки складываются в линию», а банка было три (DBS, Deutsche Bank, JPMorgan)
    s = verify.VERIFIER_SYSTEM
    assert "ПОЛНОТА РЯДА" in s
    assert "Deutsche Bank" in s


# --- ПОЛНОТА РЯДА ≠ снос: класс «дописать» отделён от класса «убрать» (вред 05.08) --------------
# Прогон 05.08: пост верно назвал пятерых операторов сети Arc по CNBC. 2FA потребовал дополнить список
# до десяти ПО БРИФУ, сам оговорившись «веб-поиск этот анонс не подтвердил». Строку поймал has_redline
# (в ней были слова-маркеры «участник»/«не подтверждено»), пайплайн напечатал «сношу прицельно» и отдал
# fix_facts ВЕСЬ вердикт — а тот добросовестно выполнил и требование дописать. В отложку уехали Sumitomo
# и Standard Chartered, инвесторы предпродажи, никогда не бывшие операторами; панель отчиталась «снёс».

_COMPLETENESS_LINE = ("⚠️ «В списке: BlackRock, Visa, Mastercard, DTCC и ICE» — КОНФЛИКТ (ПОЛНОТА РЯДА). "
                      "По брифу участников 10: пропущены Galaxy, MoneyGram, SBI, Standard Chartered, "
                      "Sumitomo. Пост называет 5 из 10, счёт «два из пяти» искажён")
# ↑ слово «участников» тут не для красоты: именно оно (маркер _REDLINE_MARKERS) отправляло такую строку
# в снос-проход. Тест сторожит РАЗДЕЛЕНИЕ классов, а не просто отсутствие срабатывания.


def test_completeness_line_is_not_a_redline():
    assert verify.is_completeness(_COMPLETENESS_LINE) is True
    assert verify.has_redline(_COMPLETENESS_LINE) is False   # это «дописать», а не «снести»
    assert verify.has_issues(_COMPLETENESS_LINE) is True      # но правки пост всё ещё требует


def test_completeness_is_stripped_before_autofix():
    v = (_COMPLETENESS_LINE + "\n"
         "⚠️ «Mastercard и DTCC участвовали в пресейле» — АТРИБУЦИЯ: не подтверждено ни одним источником\n"
         "ИТОГ: 6✅ / 3⚠️ / 1❓\nСТАТУС: ПРАВКИ")
    stripped = verify.strip_completeness(v)
    assert "Sumitomo" not in stripped                  # правке не показываем то, что она вписала бы
    assert "Mastercard и DTCC участвовали" in stripped  # а настоящую выдумку — показываем
    assert verify.has_redline(v) is True                # атрибуция всё ещё красная линия
    assert verify.completeness_notes(v) == [" ".join(_COMPLETENESS_LINE.split())]


def test_fabrication_beats_completeness_in_same_line():
    # если рядом с полнотой стоит «выдумано» — это всё-таки снос, планка строгости не снижается
    v = "⚠️ ПОЛНОТА ряда нарушена, а имя Galaxy к тому же выдумано — не прослеживается ни в одном источнике"
    assert verify.is_completeness(v) is False
    assert verify.has_redline(v) is True


def test_advice_post_incompleteness_stays_a_redline():
    # ШАГ 0.8 требует ОБРАТНОГО: в посте-инструкции неназванная затронутая модель опаснее отсутствия
    # поста (Coldcard 31.07). Новый класс не должен снимать с таких строк снос.
    v = ("⚠️ ПОЛНОТА: названы не все затронутые модели — источники называют также Mk4, Mk5 и Q, "
         "участник ряда не подтверждён")
    assert verify.is_completeness(v) is False
    assert verify.has_redline(v) is True


def test_contract_demands_web_proof_for_added_names():
    s = verify.VERIFIER_SYSTEM
    assert "НЕПОЛНОТА ЛУЧШЕ" in s.upper()          # приоритет цены задан явно
    assert "Sumitomo" in s                          # разобранный случай 05.08 в контракте
    assert "полнот" in verify.SCOPE_SOURCE_CHECK.lower()


def test_contract_checks_role_not_only_presence():
    # «X есть в источнике» ≠ «источник говорит, что X делает ИМЕННО ЭТО» (валидатор vs партнёр-оператор)
    s = verify.VERIFIER_SYSTEM
    assert "РОЛЬ" in s.upper()
    assert "оператор" in s.lower()


# --- снос проверяется КОДОМ, а не на слово ------------------------------------------------------

def test_redline_targets_extracted_from_verdict():
    v = ("⚠️ «Mastercard и DTCC участвовали в пресейле» — АТРИБУЦИЯ: не подтверждено\n"
         "✅ «222 млн$» — CNBC подтверждает")
    assert verify.redline_targets(v) == ["Mastercard и DTCC участвовали в пресейле"]


def test_targets_left_reports_failed_removal():
    targets = ["Mastercard и DTCC участвовали в пресейле"]
    assert verify.targets_left("В мае Mastercard и DTCC участвовали в пресейле токена", targets) == targets
    assert verify.targets_left("В мае токены купили a16z и BlackRock", targets) == []


def test_completeness_targets_are_not_removal_targets():
    # из строки-полноты цели сноса не берём: её фрагмент как раз ДОЛЖЕН остаться в посте
    assert verify.redline_targets(_COMPLETENESS_LINE) == []


# --- страж новых имён вокруг авто-правки --------------------------------------------------------

def test_new_entities_catches_names_added_by_fix():
    before = "Среди них BlackRock, Visa, Mastercard, ICE, DTCC, Galaxy, MoneyGram"
    after = ("В списке десять участников: BlackRock, Visa, Mastercard, DTCC, ICE, Galaxy, MoneyGram, "
             "SBI, Standard Chartered, Sumitomo")
    added = verify.new_entities(before, after)
    assert "Sumitomo" in added and "SBI" in added and "Standard" in added
    assert "BlackRock" not in added


def test_new_entities_quiet_on_number_edits():
    # правка числа не должна поднимать стража — иначе флаг обесценится
    before = "Circle собрала 222 млн$ при оценке 3 млрд$"
    after = "Circle собрала 215 млн$ при оценке 3 млрд$"
    assert verify.new_entities(before, after) == []


def test_new_entities_ignores_currency_and_tickers():
    assert verify.new_entities("пост про биткоин", "расчёты в USDC и BTC на ETF") == []


def test_only_completeness_skips_the_edit_round():
    # вердикт, где ЕДИНСТВЕННОЕ замечание — полнота ряда: правке нечего делать, круг Sonnet не нужен
    v = _COMPLETENESS_LINE + "\nИТОГ: 9✅ / 1⚠️ / 0❓\nСТАТУС: ПРАВКИ"
    assert verify.has_issues(v) is True            # замечание есть — владельцу показать
    assert verify.only_completeness(v) is True     # но править пост нечем
    assert verify.strip_completeness(v).count("⚠") == 1   # осталась лишь строка ИТОГ


def test_mixed_verdict_still_goes_to_the_edit():
    v = (_COMPLETENESS_LINE + "\n⚠️ «222 млн$» — реально 215 млн$\n"
         "ИТОГ: 8✅ / 2⚠️ / 0❓\nСТАТУС: ПРАВКИ")
    assert verify.only_completeness(v) is False
    assert "215 млн$" in verify.strip_completeness(v)


def test_status_only_verdict_falls_back_to_the_edit():
    # модель не дала построчных ⚠️ — не считаем это «только полнотой», иначе правка молча пропадёт
    assert verify.only_completeness("ИТОГ: 8✅ / 1⚠️ / 0❓\nСТАТУС: ПРАВКИ") is False
    assert verify.only_completeness("") is False
