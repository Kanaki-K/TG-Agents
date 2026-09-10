"""V2 не должна остаться текстом в сводах: проверяем, что КОД говорит то же самое.

Каждая проверка ниже — это место, где v2 однажды молча отменялась. Тест держит их вместе, чтобы
через месяц (или в новой сессии без контекста) было видно, что именно нельзя вернуть назад."""
from core import creator_tools, threads_creator, topic_gate, verify


def test_gate_ranks_by_drama_first():
    """Гейт — единственный орган выбора темы скоупа. Нет драмы в нём — нет её нигде."""
    assert "ДРАМА" in topic_gate._SYSTEM
    assert "минимум ДВА" in topic_gate._SYSTEM or "МИНИМУМ ДВА" in topic_gate._SYSTEM


def test_gate_knows_the_second_entry():
    assert "ЛОВУШКА" in topic_gate._SYSTEM and "ВХОД: <сдвиг|ловушка>" in topic_gate._SYSTEM


def test_dead_genre_is_not_the_gate_standard_anymore():
    """В v1 эталонами стояли T.Rowe и ORANGE JUICE — измеренные нули. Возврат запрещён."""
    assert "T.Rowe TKNZ" not in topic_gate._SYSTEM
    assert "КОРПОРАТИВНАЯ НОВОСТЬ" in topic_gate._SYSTEM


def test_trap_post_is_exempt_from_the_freshness_check():
    """У ловушки нет новостного повода по замыслу: 2FA не должен требовать свежесть."""
    import inspect
    src = inspect.getsource(verify.verify_post)
    assert "trap" in src and "not trap" in src


def test_linter_no_longer_recommends_a_question_headline():
    src = creator_tools._lint.__doc__ or ""
    import inspect
    body = inspect.getsource(creator_tools._lint)
    assert "чистый вопрос" not in body            # старая формула ушла из совета
    assert "ПЕРЕВОРОТ" in body


def test_threads_anchors_do_not_teach_the_old_register():
    """Эталоны написаны при «ты» — модель обязана взять из них голос, но не регистр."""
    system = threads_creator._system("scope")
    assert "РЕГИСТР ИЗ ЭТАЛОНОВ НЕ БЕРИ" in system


def test_node_hint_reaches_the_threads_writer():
    import inspect
    src = inspect.getsource(threads_creator.write)
    assert "УЗЛЫ, ПОМЕЧЕННЫЕ АВТОРОМ" in src
