"""Вход 2 (ловушка) — v2: пост без новостного повода.

Без этих проверок правило живёт только в своде: гейт вернёт «ловушку», а писатель напишет по
новостному скелету и выдумает дату события, которого не было."""
from core import scope_writer, topic_gate


def test_gate_reports_trap_entry():
    assert topic_gate.parse_mode("ВХОД: ловушка\nВЫБРАН: «эффект якоря»") == "ловушка"
    assert topic_gate.parse_mode("ВХОД: сдвиг\nВЫБРАН: «ФРС развернулась»") == "сдвиг"


def test_old_verdict_without_the_field_is_a_shift():
    """Фолбэк консервативный: вердикт v1 не должен молча превратить новостной пост в ловушку."""
    assert topic_gate.parse_mode("ВЫБРАН: «что-то»\nПОЛЬЗА: ...") == "сдвиг"


def test_gate_prompt_carries_the_drama_check():
    """Гейт — единственный орган выбора темы: если правило драмы не дошло до него, оно не работает."""
    for word in ("ДРАМА", "ГЕРОЙ", "ПАРАДОКС", "ловушка"):
        assert word in topic_gate._SYSTEM


def test_gate_no_longer_holds_dead_genre_as_the_standard():
    """В v1 эталонами стояли ORANGE JUICE и T.Rowe — измеренные нули. Они не должны вернуться."""
    assert "ORANGE JUICE, " not in topic_gate._SYSTEM
    assert "Robinhood" in topic_gate._SYSTEM


def test_writer_gets_trap_skeleton(monkeypatch):
    """В режиме ловушки писателю должен уйти скелет входа 2, а не «дата + событие»."""
    seen = {}

    def fake_turn(task, *a, **kw):
        seen["task"] = task
        return ""

    monkeypatch.setattr(scope_writer, "_turn", fake_turn)
    monkeypatch.setattr(scope_writer, "_newest_draft_stamp", lambda: "same")
    monkeypatch.setattr(scope_writer.config, "load_agent", lambda *_a, **_k: {})
    monkeypatch.setattr(scope_writer.config, "agent_api_key", lambda *_a, **_k: "k")
    scope_writer.write(recommend="эффект якоря", mode="ловушка")
    assert "ЛОВУШКА" in seen["task"] and "сцена узнавания" in seen["task"]
    assert "НЕ выдумывай новостной повод" in seen["task"]


def test_shift_mode_does_not_mention_the_trap(monkeypatch):
    seen = {}
    monkeypatch.setattr(scope_writer, "_turn", lambda task, *a, **kw: seen.setdefault("task", task) or "")
    monkeypatch.setattr(scope_writer, "_newest_draft_stamp", lambda: "same")
    monkeypatch.setattr(scope_writer.config, "load_agent", lambda *_a, **_k: {})
    monkeypatch.setattr(scope_writer.config, "agent_api_key", lambda *_a, **_k: "k")
    scope_writer.write(recommend="ФРС развернулась", mode="сдвиг")
    assert "ЛОВУШКА" not in seen["task"]
