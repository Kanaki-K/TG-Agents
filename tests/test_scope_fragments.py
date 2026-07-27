"""Судья завершённости мыслей (scope_writer.fix_fragments) — enforcement завершённых предложений
(правило владельца 27.07: обрывки «тот же триггер - не двинулся» = мучительная ручная правка тела).
Достраивает обрывки, рубленую краткость не трогает, КОД-envelope бережёт тело от порчи моделью.
Запуск: python -m pytest tests/test_scope_fragments.py"""
from core import scope_writer as sw

FOOTER = "🖥 [Канал](https://t.me/x) | ▶️ [Медиа](https://linktr.ee/y)"


def _post(body_line: str) -> str:
    return ("**📊 Заголовок**\n\n"
            "Первый абзац тела с фактом и цифрой на своём месте\n\n"
            f"{body_line}\n\n"
            f"{FOOTER}")


def _setup(monkeypatch, draft: str, verdict: str, saved: dict) -> None:
    monkeypatch.setattr(sw.config, "load_agent", lambda n: {})
    monkeypatch.setattr(sw.config, "agent_api_key", lambda c: "k")
    monkeypatch.setattr(sw.runmode, "resolve", lambda m, ceiling=None: m)
    monkeypatch.setattr(sw.verify, "latest_draft", lambda: draft)
    monkeypatch.setattr(sw, "_turn", lambda *a, **k: verdict)
    monkeypatch.setattr(sw.creator_tools, "dispatch", lambda name, args: saved.update(args) or "ok")


def test_clean_untouched(monkeypatch):
    # «МЫСЛИ ОК» → пост не трогаем, save не зовём
    saved: dict = {}
    draft = _post("Биткоин не дрогнул")
    _setup(monkeypatch, draft, "МЫСЛИ ОК", saved)
    assert sw.fix_fragments() == draft
    assert saved == {}


def test_fragments_rewritten(monkeypatch):
    # обрывок → судья вернул исправленное тело → пересохраняем, футер цел
    saved: dict = {}
    draft = _post("тот же триггер - не двинулся")
    fixed = _post("Тот же триггер ударил по акциям - биткоин не двинулся")
    _setup(monkeypatch, draft, fixed, saved)
    out = sw.fix_fragments()
    assert "биткоин не двинулся" in out.lower()
    assert out.rstrip().endswith(FOOTER)
    assert saved.get("kind") == "scope" and "content" in saved


def test_envelope_rejects_gutted_body(monkeypatch):
    # правка опустошила тело (<60% исходного) → envelope отбраковывает, оставляем исходник
    saved: dict = {}
    draft = _post("Первый длинный осмысленный абзац тела про биткоин, техи и корреляцию")
    _setup(monkeypatch, draft, "Коротко", saved)
    assert sw.fix_fragments() == draft
    assert saved == {}


def test_envelope_rejects_lost_footer(monkeypatch):
    # правка потеряла футер → модель сломала пост → отбраковка
    saved: dict = {}
    draft = _post("тот же триггер - не двинулся")
    nofoot = ("**📊 Заголовок**\n\nПервый абзац тела с фактом и цифрой на своём месте\n\n"
              "Тот же триггер ударил по акциям, а биткоин остался стоять на месте без движения")
    _setup(monkeypatch, draft, nofoot, saved)
    assert sw.fix_fragments() == draft
    assert saved == {}


def test_keeps_split_media_tail(monkeypatch):
    # медиа-мету после [[SPLIT]] не теряем при правке тела
    saved: dict = {}
    draft = _post("тот же триггер - не двинулся") + "\n[[SPLIT]]\n[[MEDIA_SRC]] https://a.com/x"
    fixed = _post("Тот же триггер ударил по акциям - биткоин остался на месте")
    _setup(monkeypatch, draft, fixed, saved)
    out = sw.fix_fragments()
    assert "[[SPLIT]]" in out and "https://a.com/x" in out
    assert "биткоин остался на месте" in out.lower()
