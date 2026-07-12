"""Тесты наблюдаемости (P2-15): метки agent/req в логах через contextvars + фильтр (core/logging_setup)."""
import contextvars
import logging

from core import logging_setup as ls


def test_defaults_are_dash():
    # вне запроса/агента метки — «-» (стартовый/фоновый код), а не падение форматтера.
    # Свежий Context: не зависим от того, что другие тесты уже выставили set_agent/new_request.
    ctx = contextvars.Context()
    assert ctx.run(ls._agent_var.get) == "-"
    assert ctx.run(ls._req_var.get) == "-"


def test_set_agent():
    ls.set_agent("creator")
    assert ls._agent_var.get() == "creator"
    ls.set_agent("")           # пусто → «-», не пустая строка
    assert ls._agent_var.get() == "-"


def test_new_request_monotonic_and_tag():
    r1 = ls.new_request()
    r2 = ls.new_request("777")
    assert r1 != r2
    assert r2.endswith("-777")           # метка (uid) приклеена
    assert ls._req_var.get() == r2       # contextvar обновлён


def test_filter_injects_fields_onto_record():
    ls.set_agent("scout")
    ls.new_request("42")
    rec = logging.LogRecord("core.test", logging.INFO, __file__, 1, "msg", None, None)
    assert ls._ContextFilter().filter(rec) is True
    assert rec.agent == "scout"
    assert rec.req.endswith("-42")


def test_setup_idempotent():
    ls.setup()
    ls.setup()   # повторный вызов безвреден (не бросает, не дублирует хендлеры)
