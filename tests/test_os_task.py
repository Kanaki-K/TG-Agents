"""Тесты будильника в ОС (core/os_task): задача Планировщика Windows для автопилота.

Зачем покрыто: владелец включает автопилот ОДНОЙ фразой в чате, и Криейтор сам ставит задачу. Если
команда собрана неверно, «включено» будет означать «никто не проснётся» — а узнается это только по
тишине в канале в четверг. Сам `schtasks` не зовём (в тестах его нет и звать нельзя): подменяем
запускатель и проверяем, ЧТО именно ушло бы в ОС.
"""
import sys

import pytest

from core import os_task


@pytest.fixture
def fake_run(monkeypatch):
    """Перехватываем вызовы schtasks: возвращаем заданный код и запоминаем аргументы."""
    calls = []

    def factory(rc: int = 0, out: str = ""):
        def _run(args):
            calls.append(args)
            return rc, out
        monkeypatch.setattr(os_task, "_run", _run)
        monkeypatch.setattr(os_task, "supported", lambda: True)
        return calls
    return factory


def test_install_builds_correct_schtasks_command(fake_run):
    calls = fake_run(0)
    res = os_task.install(start="08:00", every=30, hours=12)
    assert res["ok"], res["detail"]
    args = calls[0]
    assert args[0] == "schtasks" and "/Create" in args
    assert "/F" in args                                  # перезапись: повторное «включи» не плодит дубли
    assert os_task.TASK_NAME in args
    assert args[args.index("/SC") + 1] == "DAILY"
    assert args[args.index("/ST") + 1] == "08:00"
    assert args[args.index("/RI") + 1] == "30"
    assert args[args.index("/DU") + 1] == "0012:00"       # формат ЧЧЧЧ:ММ, иначе schtasks не поймёт
    target = args[args.index("/TR") + 1]
    assert "run_autopilot.py" in target
    assert target.count('"') == 4                        # путь с пробелами обязан быть в кавычках


def test_install_reports_failure_instead_of_pretending(fake_run):
    """Не встал будильник — владелец обязан узнать: иначе «включено» = тишина в четверг."""
    fake_run(1, "Отказано в доступе")
    res = os_task.install()
    assert res["ok"] is False
    assert "Отказано" in res["detail"]


def test_remove_is_ok_when_nothing_to_remove(monkeypatch):
    monkeypatch.setattr(os_task, "supported", lambda: True)
    monkeypatch.setattr(os_task, "status", lambda: {"supported": True, "exists": False, "detail": ""})
    res = os_task.remove()
    assert res["ok"] is True          # снимать нечего — это успех, а не ошибка


def test_remove_deletes_when_task_exists(fake_run, monkeypatch):
    calls = fake_run(0)
    monkeypatch.setattr(os_task, "status", lambda: {"supported": True, "exists": True, "detail": ""})
    assert os_task.remove()["ok"] is True
    assert "/Delete" in calls[0] and "/F" in calls[0]


def test_status_says_not_supported_outside_windows(monkeypatch):
    monkeypatch.setattr(os_task, "supported", lambda: False)
    st = os_task.status()
    assert st["supported"] is False and st["exists"] is False


def test_install_refuses_outside_windows_with_explanation(monkeypatch):
    monkeypatch.setattr(os_task, "supported", lambda: False)
    res = os_task.install()
    assert res["ok"] is False
    assert "Windows" in res["detail"]


def test_python_exe_prefers_pythonw_when_present(monkeypatch, tmp_path):
    """pythonw.exe = без мигающего консольного окна каждые 30 минут. Есть — берём его."""
    quiet = tmp_path / "pythonw.exe"
    quiet.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    assert os_task.python_exe() == str(quiet)


def test_python_exe_falls_back_to_current(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    assert os_task.python_exe() == str(tmp_path / "python.exe")
