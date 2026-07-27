"""Судья финала scope (scope_writer.fix_finale) — enforcement концовки (scope_manual §4.5).

Advisory-слой (мануал/уроки) финал не держал 10+ сессий — владелец правил концовку руками. Этот пасс
мерит последнюю строку и слабую (сомнение/вопрос/хедж/пересказ) переписывает кикером. Запуск:
python -m pytest tests/test_scope_finale.py"""
from __future__ import annotations

from core import scope_writer as sw

FOOTER = "🖥 [Канал](https://t.me/x) | ▶️ [Медиа](https://linktr.ee/y)"


def _post(finale: str) -> str:
    return ("**⚡️ Заголовок поста**\n\n"
            "Первый абзац тела с фактом и цифрой\n\n"
            "Второй абзац — механизм и вывод\n\n"
            f"{finale}\n\n"
            f"{FOOTER}")


def _setup(monkeypatch, draft: str, verdict: str, saved: dict) -> None:
    monkeypatch.setattr(sw.config, "load_agent", lambda n: {})
    monkeypatch.setattr(sw.config, "agent_api_key", lambda c: "k")
    monkeypatch.setattr(sw.runmode, "resolve", lambda m, ceiling=None: m)
    monkeypatch.setattr(sw.verify, "latest_draft", lambda: draft)
    monkeypatch.setattr(sw, "_turn", lambda *a, **k: verdict)
    monkeypatch.setattr(sw.creator_tools, "dispatch", lambda name, args: saved.update(args) or "ok")


def test_finale_strong_untouched(monkeypatch):
    # сильный кикер → «ФИНАЛ ОК» → пост не меняем, save не зовём
    saved: dict = {}
    draft = _post("Годами строили под Биткоин. А первыми выкупил AI")
    _setup(monkeypatch, draft, "ФИНАЛ ОК", saved)
    assert sw.fix_finale() == draft
    assert saved == {}


def test_finale_weak_rewritten(monkeypatch):
    # слабый финал (сомнение) → судья вернул кикер → вклеиваем ТОЛЬКО финал, заголовок+футер целы
    saved: dict = {}
    draft = _post("Те, кто платит за защиту, не договорились, когда она нужна")
    _setup(monkeypatch, draft,
           "ФИНАЛ: Впервые те, у кого есть что терять, платят за протокол, которым не управляют", saved)
    out = sw.fix_finale()
    assert "не договорились" not in out                       # старый слабый финал ушёл
    assert "Впервые те, у кого есть что терять" in out         # новый кикер вклеен
    assert out.split("\n\n")[0] == "**⚡️ Заголовок поста**"    # заголовок цел
    assert out.rstrip().endswith(FOOTER)                       # футер цел
    assert saved.get("kind") == "scope" and "content" in saved  # пересохранили драфт


def test_finale_no_footer_untouched(monkeypatch):
    # нет футера → структуру не угадать → не трогаем (пост обязан быть)
    saved: dict = {}
    draft = "**Заголовок**\n\nтело без футера\n\nещё строка"
    _setup(monkeypatch, draft, "ФИНАЛ: новый кикер", saved)
    assert sw.fix_finale() == draft
    assert saved == {}


def test_finale_unparseable_untouched(monkeypatch):
    # судья ответил без метки «ФИНАЛ:» → финал оставляем как есть
    saved: dict = {}
    draft = _post("Слабоватый финал")
    _setup(monkeypatch, draft, "мутный ответ без контракта", saved)
    assert sw.fix_finale() == draft
    assert saved == {}


def test_finale_keeps_split_media_tail(monkeypatch):
    # медиа-мету после [[SPLIT]] не трогаем при переписи финала
    saved: dict = {}
    draft = _post("Финал на сомнении, повиснет") + "\n[[SPLIT]]\n[[MEDIA_SRC]] https://a.com/x"
    _setup(monkeypatch, draft, "ФИНАЛ: Кикер, который стоит сам", saved)
    out = sw.fix_finale()
    assert "[[SPLIT]]" in out and "https://a.com/x" in out
    assert "Кикер, который стоит сам" in out
