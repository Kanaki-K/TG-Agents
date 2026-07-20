"""Тесты доставки health-алерта через Bot API (core/bot_alert) — независимо от MTProto (N-45)."""
from core import bot_alert, config


def test_first_owner_id_parses_and_takes_first(monkeypatch):
    monkeypatch.setattr(config, "get_optional", lambda k: "111, 222; 333" if k == "OWNER_ID" else None)
    assert bot_alert._first_owner_id() == "111"


def test_first_owner_id_empty(monkeypatch):
    monkeypatch.setattr(config, "get_optional", lambda k: None)
    assert bot_alert._first_owner_id() is None


def test_bot_token_picks_first_available(monkeypatch):
    vals = {"CREATOR_BOT_TOKEN": None, "SCOUT_BOT_TOKEN": "tok2"}
    monkeypatch.setattr(config, "get_optional", lambda k: vals.get(k))
    assert bot_alert._bot_token() == "tok2"


def test_notify_owner_false_without_config(monkeypatch):
    # нет токена/OWNER_ID → возвращает False СРАЗУ, без HTTP-вызова (fail-safe, сеть не трогаем)
    monkeypatch.setattr(config, "get_optional", lambda k: None)
    assert bot_alert.notify_owner("тест") is False
