"""Тесты наблюдаемости (P2-15): метки agent/req в логах через contextvars + фильтр (core/logging_setup)."""
import contextvars
import logging
import logging.handlers   # явно: без этого logging.handlers может быть недоступен как атрибут

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


# --- ФАЙЛОВЫЙ ЛОГ (add_file_log) --------------------------------------------------------------
# Этим логом живёт АВТОПИЛОТ — процесс без консоли (Планировщик задач Windows). Его stderr уходит в
# никуда, и файл на диске — единственный след после тихого сбоя. Если хендлер не подключится или
# начнёт дублироваться на каждый прогон, в работе мы этого не увидим.

def _detach(path):
    """Снять наши файловые хендлеры с КОРНЕВОГО логгера — иначе тест течёт в остальные тесты."""
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, logging.handlers.RotatingFileHandler) and str(path) in h.baseFilename:
            root.removeHandler(h)
            h.close()


def test_add_file_log_writes_record(tmp_path):
    p = tmp_path / "autopilot.log"
    try:
        assert ls.add_file_log(p) is True
        logging.getLogger("test.autopilot").warning("проверка записи")
        assert p.exists()
        assert "проверка записи" in p.read_text(encoding="utf-8")
    finally:
        _detach(p)


def test_add_file_log_is_idempotent(tmp_path):
    """Автопилот зовёт это на КАЖДОМ запуске (и в цикле демона) — хендлеры не должны накапливаться."""
    p = tmp_path / "autopilot.log"
    try:
        before = len(logging.getLogger().handlers)
        assert ls.add_file_log(p) is True
        added = len(logging.getLogger().handlers)
        assert ls.add_file_log(p) is True
        assert len(logging.getLogger().handlers) == added == before + 1
    finally:
        _detach(p)


def test_add_file_log_survives_bad_path(tmp_path):
    """Не смогли открыть файл — работаем без него и НЕ роняем прогон (лог не важнее публикации)."""
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("я файл, а не папка", encoding="utf-8")
    assert ls.add_file_log(blocker / "sub" / "autopilot.log") is False


def test_dump_json_is_atomic(tmp_path):
    """io_safe.dump_json — пара к load_json: пишем через temp+replace, чтобы читатель (другой процесс)
    никогда не увидел полуфабрикат, а обрыв записи не превратил настройки в «как будто их нет»."""
    from core import io_safe

    p = tmp_path / "sub" / "state.json"
    io_safe.dump_json(p, {"ключ": "значение", "число": 3})
    assert io_safe.load_json(p, {}) == {"ключ": "значение", "число": 3}
    assert list(p.parent.glob("*.tmp")) == []      # временный файл убран (os.replace), мусора нет
    io_safe.dump_json(p, {"ключ": "новое"})        # перезапись поверх существующего
    assert io_safe.load_json(p, {}) == {"ключ": "новое"}


def test_load_json_falls_back_on_truncated_file(tmp_path):
    """Обрезанный JSON (как после обрыва прямой записи) читается как default — вот почему нужна атомарность."""
    from core import io_safe

    p = tmp_path / "state.json"
    p.write_text('{"ключ": "знач', encoding="utf-8")
    assert io_safe.load_json(p, {"дефолт": True}) == {"дефолт": True}


def test_file_log_keeps_agent_context(tmp_path):
    """В формате есть %(agent)s: без контекст-фильтра запись из под-модуля уронила бы форматирование."""
    p = tmp_path / "autopilot.log"
    try:
        assert ls.add_file_log(p) is True
        ls.set_agent("autopilot")
        logging.getLogger("core.dedup").warning("из под-модуля")
        text = p.read_text(encoding="utf-8")
        assert "autopilot" in text and "из под-модуля" in text
    finally:
        ls.set_agent("-")
        _detach(p)
