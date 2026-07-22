"""Гейт ТЕМЫ (core/topic_gate) — отбор ЛУЧШЕГО повода ДО генерации по свежести+пользе. ВСЕГДА даёт
повод (правило владельца 22.07: пост обязан быть, ПРОПУСКА нет). Судейское суждение модели тут не
проверяем (живой прогон) — проверяем ПЛУМБИНГ: парсинг ПОВОД/СЛАБО, фолбэк на сбое, always-return."""
from core import topic_gate


def test_parse_choice_picks_theme():
    v = "Лучший — BTC-драйвер, событие вчера, эдж про ликвидность.\nПОВОД: «BTC сменил драйвер на ликвидность»"
    theme, weak = topic_gate.parse_choice(v)
    assert theme == "BTC сменил драйвер на ликвидность"
    assert weak == ""


def test_parse_choice_extracts_weakness():
    v = ("Свежего мало.\nСЛАБО: повод протух (9д) — подать через долговечный механизм\n"
         "ПОВОД: «Индекс принятия банков — через механизм кастодии»")
    theme, weak = topic_gate.parse_choice(v)
    assert theme == "Индекс принятия банков — через механизм кастодии"
    assert "протух" in weak


def test_parse_choice_takes_last_povod_line():
    # контракт: финал — ПОСЛЕДНЯЯ строка ПОВОД (если модель черновала выше)
    v = "ПОВОД: «черновик»\nещё думаю...\nПОВОД: «финальный повод»"
    theme, _ = topic_gate.parse_choice(v)
    assert theme == "финальный повод"


def test_parse_choice_no_line_returns_empty():
    # нет строки ПОВОД (сбой/парсинг) → ('', '') → вызывающий делает фолбэк на recommend
    assert topic_gate.parse_choice("бла-бла без вердикта") == ("", "")
    assert topic_gate.parse_choice("") == ("", "")
    assert topic_gate.parse_choice(None) == ("", "")


def test_select_empty_candidates_no_model_call(monkeypatch):
    # нет разбора кандидатов → не зовём модель, отдаём пусто (writer возьмёт повод сам)
    calls = []
    monkeypatch.setattr(topic_gate.llm, "reply", lambda *a, **k: calls.append(1))
    theme, weak, verdict = topic_gate.select("")
    assert (theme, weak) == ("", "")
    assert calls == []
    assert "отбирать не из чего" in verdict


def test_select_parses_model_verdict(monkeypatch):
    fake = "BTC свежий, польза есть.\nПОВОД: «BTC сменил драйвер»"
    monkeypatch.setattr(topic_gate.llm, "reply", lambda *a, **k: (fake, None))
    theme, weak, verdict = topic_gate.select("🆕 «BTC» — событие 20.07", today="2026-07-22")
    assert theme == "BTC сменил драйвер"
    assert weak == ""
    assert verdict == fake


def test_select_failopen_on_model_error(monkeypatch):
    # сбой модели → ('', '', причина): НЕ роняем конвейер, вызывающий делает фолбэк на recommend
    def boom(*a, **k):
        raise RuntimeError("api down")
    monkeypatch.setattr(topic_gate.llm, "reply", boom)
    theme, weak, verdict = topic_gate.select("🆕 что-то", today="2026-07-22")
    assert (theme, weak) == ("", "")
    assert "не удался" in verdict


def test_select_passes_today_into_prompt(monkeypatch):
    # дата ДОЛЖНА уходить в промпт (гейт считает возраст события) — иначе «понимание даты» сломано
    seen = {}
    def cap(model, system, hist, user, tools, disp, key, thinking, **k):
        seen["user"] = user
        return ("ПОВОД: «x»", None)
    monkeypatch.setattr(topic_gate.llm, "reply", cap)
    topic_gate.select("🆕 повод — событие 13.07", today="2026-07-22")
    assert "2026-07-22" in seen["user"]
