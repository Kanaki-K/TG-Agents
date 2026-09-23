"""Threads под правила языка v3 ТГ-канала — мини-скоуп 23.09.2026.

Владелец: «"Каждый перевод с биржи на личный кошелёк - это не транзакция. Это подпись" — не это, а вот
это; ошибка ровно та, что была у скоупа». Свод Threads запрещал это текстом, кода не было, и писатель
построил на антитезе заголовок, середину и финал.
"""
from core import threads_creator as tc
from core import threads_lint as tl

POST_23_09 = (
    "Каждый перевод с биржи (где Вы подтвердили паспорт) на личный кошелёк - это не транзакция. Это подпись.\n\n"
    "Время платежа, размер, частота газа по отдельности - шум. Вместе - почерк, уникальный как отпечаток пальца.\n\n"
    "Бутерин проверил это на себе: попросил AI найти текст, который он анонимно опубликовал годы назад. "
    "Модель вычислила его не по словам - по манере рассуждать.\n\n"
    "В блокчейне данных для такого разбора на порядок больше. И они лежат открыто. Навсегда.\n\n"
    "Псевдонимность означала не \"меня не найдут\". Она означала \"меня пока не искали\"."
)

CLEAN = (
    "AI сопоставляет переводы с биржи на кошелёк и находит владельца по привычкам\n\n"
    "Время платежа, размер и частота переводов вместе складываются в почерк.\n\n"
    "Бутерин проверил это на себе: модель нашла его старый анонимный текст по манере рассуждать.\n\n"
    "Каждый перевод с биржи с проверкой паспорта добавляет ещё одну связку между адресом и именем."
)


def test_live_23_09_post_is_caught_in_all_three_places():
    got = " | ".join(tl.language(POST_23_09))
    assert "ЗАГОЛОВКЕ" in got and "ФИНАЛЕ" in got and "передоз" in got and "Это не X. Это Y" in got


def test_clean_post_has_no_language_defects():
    assert tl.language(CLEAN) == []


def test_one_antithesis_in_the_body_is_allowed():
    """Замер: «не X, а Y» в 45% принятых постов канала — одна в теле не брак, брак в заголовке/финале."""
    body = CLEAN.replace("складываются в почерк.", "складываются не в шум, а в почерк.")
    assert tl.language(body) == []


def test_tg_formatting_rules_do_not_leak_into_threads():
    """Жирный заголовок, футер, эмодзи-набор — правила оформления ТГ, у Threads свои."""
    got = " ".join(tl.language(CLEAN))
    assert "жирный" not in got and "футер" not in got


def test_check_reports_language_to_the_owner():
    assert any("ЗАГОЛОВКЕ" in x for x in tl.check(POST_23_09))


def test_one_fix_round_by_the_author(monkeypatch):
    calls = []

    def reply(model, system, hist, user, *a, **k):
        calls.append(user)
        return CLEAN, None
    monkeypatch.setattr(tc.llm, "reply", reply)
    monkeypatch.setattr(tc, "_system", lambda kind: "")
    out = tc._enforce_language([POST_23_09], "scope", "k", "m")
    assert out == [CLEAN] and len(calls) == 1
    assert "⛔ ДЕФЕКТЫ" in calls[0]
    assert "→ 0" in tc.LAST_LANGUAGE_NOTE and "за 1 круг" in tc.LAST_LANGUAGE_NOTE


def test_clean_posts_cost_nothing(monkeypatch):
    monkeypatch.setattr(tc.llm, "reply", lambda *a, **k: (_ for _ in ()).throw(AssertionError("вызов")))
    assert tc._enforce_language([CLEAN], "scope", "k", "m") == [CLEAN]


def test_wrong_answer_keeps_the_originals(monkeypatch):
    monkeypatch.setattr(tc.llm, "reply", lambda *a, **k: ("пост1\n[[POST]]\nпост2", None))
    monkeypatch.setattr(tc, "_system", lambda kind: "")
    assert tc._enforce_language([POST_23_09], "scope", "k", "m") == [POST_23_09]
    assert "оставил исходные" in tc.LAST_LANGUAGE_NOTE


def test_manuals_no_longer_teach_the_antithesis():
    for f in ("memory/threads_scope_manual.md", "memory/threads_flagship_manual.md"):
        t = open(f, encoding="utf-8").read()
        assert "парадокс / контраст / вопрос" not in t and "парадокс/контраст/вопрос" not in t
        assert "формула-афоризм" not in t


def test_length_mark_names_the_cut_and_echo_is_stripped():
    assert tc._unmark("❌ [703 знаков — убрать минимум 224] Текст поста") == "Текст поста"


def test_second_length_round_if_the_first_falls_short(monkeypatch):
    """Живой мини-скоуп 23.09: один круг дал 703 → 654, всё ещё за потолком 499."""
    answers = iter(["я" * (tc.MAX_LEN + 100), "я" * (tc.MAX_LEN - 10)])
    monkeypatch.setattr(tc.llm, "reply", lambda *a, **k: (next(answers), None))
    monkeypatch.setattr(tc, "_system", lambda kind: "")
    out = tc._enforce_length(["я" * (tc.MAX_LEN + 200)], "scope", "k", "m")
    assert len(out[0]) <= tc.MAX_LEN and "в норму" in tc.LAST_LENGTH_NOTE


def test_forms_the_writer_escaped_to_are_caught():
    """Второй живой прогон 23.09: писатель ушёл в соседние формы антитезы."""
    got = " ".join(tl.language(
        "Приватность в блокчейне не взламывают - её вычисляют\n\n" + CLEAN.split("\n\n", 1)[1]
        + "\n\nВопрос не в том, знают ли его. В том, сколько связок осталось"))
    assert "ЗАГОЛОВКЕ" in got and "ФИНАЛЕ" in got


def test_plain_dash_after_negation_is_not_an_antithesis():
    """Замер канала: «Коду доверять не нужно - он либо пропускает операцию» — обычная фраза."""
    assert tl.language(CLEAN + "\n\nКоду доверять не нужно - он либо пропускает операцию, либо нет") == []


def test_second_language_round_if_the_first_leaves_a_defect(monkeypatch):
    """Живой прогон 23.09: антитеза в финале пережила один круг (1 → 1)."""
    answers = iter([POST_23_09, CLEAN])
    monkeypatch.setattr(tc.llm, "reply", lambda *a, **k: (next(answers), None))
    monkeypatch.setattr(tc, "_system", lambda kind: "")
    assert tc._enforce_language([POST_23_09], "scope", "k", "m") == [CLEAN]
    assert "за 2 круг" in tc.LAST_LANGUAGE_NOTE


def test_third_live_run_escapes_are_caught():
    """Третий живой прогон 23.09: заголовок буквально «Не X. Это Y» и финал «Вопрос не в том…»."""
    rest = CLEAN.split("\n\n", 1)[1]
    got = " ".join(tl.language("Не X. Это Y\n\n" + rest))
    assert "ШАБЛОН" in got and "ЗАГОЛОВКЕ" in got
    got = " ".join(tl.language(CLEAN + "\n\nВопрос не в том, знают ли Ваше имя. Вопрос - сколько переводов связать"))
    assert "ФИНАЛЕ" in got


def test_fourth_live_run_escapes_are_caught():
    rest = CLEAN.split("\n\n", 1)[1]
    got = " ".join(tl.language(CLEAN + "\n\nВопрос не \"знают ли Ваше имя\". Вопрос - сколько связок нужно"))
    assert "ФИНАЛЕ" in got
    got = " ".join(tl.language("Приватность в блокчейне уже не работает - и дело не в криптографии\n\n" + rest))
    assert "ЗАГОЛОВКЕ" in got


def test_vy_is_capitalized_by_code():
    """Живой прогон 23.09: «выдаёт вас», «о вас уже знают». Канал с 11.08: строчных 0, заглавных 55."""
    got = tc._capital_vy("Ваш кошелёк выдаёт вас манерой. Его сверяют с тем, что о вас знают, и вам не скрыться")
    assert got == "Ваш кошелёк выдаёт Вас манерой. Его сверяют с тем, что о Вас знают, и Вам не скрыться"
    assert tc._capital_vy("Вызов и вывод") == "Вызов и вывод"      # слова, начинающиеся с «вы», не трогаем


FACTORY_23_09 = (
    "Приватность будущего Вас предаст, но не сегодня.\n\n"
    "23 сентября Виталик Бутерин признал: прятать имя за адресом кошелька больше не работает. Модель "
    "сопоставляет время транзакций, размер, частоту газа - и получает поведенческий отпечаток. В июне AI "
    "вычислил самого Бутерина по манере рассуждения в старом тексте.\n\n"
    "Данные в блокчейне лежат открыто и навсегда, и сравнивать их будут моделями, которых ещё не написали. "
    "Псевдоним - это отложенный срок на раскрытие.")
OWNER_23_09 = (
    "Приватность будущего Вас предаст, но не сегодня\n\n"
    "23 сентября Виталик Бутерин признал: прятать имя за адресом кошелька больше не работает\n\n"
    "Модель сопоставляет время транзакций, размер, частоту газа - и получает поведенческий отпечаток\n\n"
    "В июне AI вычислил самого Бутерина по манере рассуждения в старом тексте\n\n"
    "Данные в блокчейне лежат открыто и навсегда, и сравнивать их будут моделями, которых ещё не написали\n\n"
    "Псевдоним - это отложенный срок на раскрытие")


def test_beats_reproduce_the_owner_edit_of_23_09():
    """Владелец: «переделал структуру и точки в конце предложения». Код делает ровно ту же правку."""
    assert tc._beats(FACTORY_23_09) == OWNER_23_09


def test_short_two_sentence_line_is_kept_and_numbers_are_safe():
    """Короткий абзац из двух предложений у владельца норма (медиана 66 знаков) — не режем; 6.25 не рвём."""
    t = "Мнение бесплатно. Поэтому оно ничего и не стоит\n\nВыплата упала с 6.25 до 3.125 BTC..."
    assert tc._beats(t) == t


def test_reverse_pair_split_by_beats_is_caught_in_the_finale():
    """Прогон после строк-битов: «Псевдоним прячет имя» / «Он не прячет то, как Вы думаете»."""
    got = " ".join(tl.language(CLEAN + "\n\nПсевдоним прячет имя\n\nОн не прячет то, как Вы думаете"))
    assert "ФИНАЛЕ" in got


def test_owner_edit_of_23_09_is_clean():
    """Пост в правке владельца проходит проверку языка — иначе линтер спорит с ним самим."""
    assert tl.language(OWNER_23_09) == []


def test_headline_split_by_beats_is_caught():
    """Прогон 23.09: «Приватность в блокчейне никогда не была про имя» / «Она была про то, сколько связок»."""
    rest = CLEAN.split("\n\n", 1)[1]
    t = ("Приватность в блокчейне никогда не была про имя\n\nОна была про то, сколько связок нужно\n\n" + rest)
    assert any("ЗАГОЛОВКЕ" in x for x in tl.language(t))


def test_language_is_rechecked_after_the_length_round():
    import inspect
    src = inspect.getsource(tc.write)
    assert src.index("_enforce_length(posts") < src.rindex("_enforce_language(posts")
