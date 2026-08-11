"""Тесты файлового лога (core/logging_setup.add_file_log).

Зачем покрыто: этим логом живёт АВТОПИЛОТ — процесс без консоли (Планировщик задач Windows). Его
stderr уходит в никуда, и файл на диске — единственный след после тихого сбоя. Если хендлер тихо не
подключится или начнёт дублироваться на каждый прогон, мы этого никак не увидим в работе.
"""
import logging
import logging.handlers   # явно: без этого logging.handlers может быть недоступен как атрибут

from core import logging_setup


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
        assert logging_setup.add_file_log(p) is True
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
        assert logging_setup.add_file_log(p) is True
        added = len(logging.getLogger().handlers)
        assert logging_setup.add_file_log(p) is True
        assert len(logging.getLogger().handlers) == added == before + 1
    finally:
        _detach(p)


def test_add_file_log_survives_bad_path(tmp_path):
    """Не смогли открыть файл — работаем без него и НЕ роняем прогон (лог не важнее публикации)."""
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("я файл, а не папка", encoding="utf-8")
    assert logging_setup.add_file_log(blocker / "sub" / "autopilot.log") is False


def test_file_log_keeps_agent_context(tmp_path):
    """В формате есть %(agent)s: без контекст-фильтра запись из под-модуля уронила бы форматирование."""
    p = tmp_path / "autopilot.log"
    try:
        assert logging_setup.add_file_log(p) is True
        logging_setup.set_agent("autopilot")
        logging.getLogger("core.dedup").warning("из под-модуля")
        text = p.read_text(encoding="utf-8")
        assert "autopilot" in text and "из под-модуля" in text
    finally:
        logging_setup.set_agent("-")
        _detach(p)
