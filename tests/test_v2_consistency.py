"""V2 не должна остаться текстом в сводах: проверяем, что КОД говорит то же самое.

Каждая проверка ниже — это место, где v2 однажды молча отменялась. Тест держит их вместе, чтобы
через месяц (или в новой сессии без контекста) было видно, что именно нельзя вернуть назад."""
from core import creator_tools, threads_creator, topic_gate, verify


def test_gate_keeps_drama_but_as_ranking():
    """Гейт — единственный орган выбора темы скоупа. Драма в нём осталась, но с 14.09 она ранжирует
    поводы про деньги криптана, а не отменяет их (v3: драма-вето выбросило свежие поводы и довело до
    склеенной «ловушки»)."""
    assert "ДРАМА" in topic_gate._SYSTEM
    assert "НЕ ВЕТО" in topic_gate._SYSTEM


def test_gate_has_no_second_entry_anymore():
    """Вход 2 «ловушка» снят 14.09: тема всегда реальное событие одного направления брифа."""
    assert "ЛОВУШКА" not in topic_gate._SYSTEM and "ВХОД:" not in topic_gate._SYSTEM
    assert "НАПРАВЛЕНИЕ:" in topic_gate._SYSTEM


def test_dead_genre_is_not_the_gate_standard_anymore():
    """В v1 эталонами стояли T.Rowe и ORANGE JUICE — измеренные нули. Возврат запрещён."""
    assert "T.Rowe TKNZ" not in topic_gate._SYSTEM
    assert "КОРПОРАТИВНАЯ НОВОСТЬ" in topic_gate._SYSTEM


def test_every_scope_post_gets_the_freshness_check():
    """Исключение для ловушки снято вместе с ней (14.09): у каждого scope-поста есть событие."""
    import inspect
    assert "trap" not in inspect.signature(verify.verify_post).parameters


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
