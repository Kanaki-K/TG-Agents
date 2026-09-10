"""Тип услуги читателю и его ротация (v2.1, правка владельца 10.09).

Почему это тест, а не строка в своде: замер меряет ИНТЕРЕС (заходы в профиль), а не ПОЛЬЗУ.
Оптимизируя только его, система сползает к «личной угрозе» в каждом посте — страх дешевле всего
покупает внимание. Ротация типов и гейт выхода — противовес, который метрика дать не может."""
import json

import pytest

from core import published_journal as J

META = "\n\n[[SPLIT]]\n[[УЗЕЛ]] платите за чужую ошибку\n[[ТИП]] личная ставка\n[[ВЫХОД]] спросит у провайдера про страховой фонд"


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "JOURNAL", tmp_path / "j.jsonl")
    monkeypatch.setattr(J, "LEGACY_JOURNAL", tmp_path / "legacy.jsonl")
    return tmp_path


def test_service_type_is_read_from_meta():
    assert J.service_of("текст" + META) == "личная ставка"


def test_unknown_type_is_empty_not_guessed():
    """Лучше пусто, чем ложь: выдуманный тип испортил бы ротацию молча."""
    assert J.service_of("текст\n\n[[SPLIT]]\n[[ТИП]] что-то своё") == ""


def test_type_in_the_body_is_ignored():
    assert J.service_of("[[ТИП]] инструмент\n\nтекст") == ""


def test_journal_keeps_type_and_exit(journal):
    J.record("Пост про слэшинг" + META, theme="слэшинг", kind="flagship")
    e = J.latest("flagship")
    assert e["service"] == "личная ставка"
    assert "страховой фонд" in e["exit"]
    assert "[[ТИП]]" not in e["text"]          # мета в канал не уходит


def test_recent_services_newest_first(journal):
    J.record("A\n\n[[SPLIT]]\n[[ТИП]] механизм", kind="flagship")
    J.record("B\n\n[[SPLIT]]\n[[ТИП]] линза", kind="flagship")
    J.record("C\n\n[[SPLIT]]\n[[ТИП]] инструмент", kind="flagship")
    assert J.recent_services(3) == ["инструмент", "линза", "механизм"]


def test_posts_without_type_do_not_break_rotation(journal):
    """Старые записи (до v2.1) типа не имеют — они просто не участвуют."""
    J.record("старый пост без меты", kind="flagship")
    J.record("новый\n\n[[SPLIT]]\n[[ТИП]] переворот", kind="flagship")
    assert J.recent_services(3) == ["переворот"]


def test_picker_prompt_forbids_repeating_the_type():
    import run_pipeline as RP
    import inspect
    src = inspect.getsource(RP._pick_timely_theme)
    assert "ДВА ПОСТА ПОДРЯД ОДНОГО ТИПА ЗАПРЕЩЕНЫ" in src
    assert "recent_services" in src


def test_exit_gate_reaches_the_writer():
    import run_pipeline as RP
    import inspect
    src = inspect.getsource(RP._run_creator)
    assert "ГЕЙТ ВЫХОДА" in src and "иллюзия знания" in src
