"""core.llm.resolve_thinking — маппинг config['thinking'] в API-конфиг мышления (без сети).

Единый маппинг для всех агентов: 'adaptive' | целое-бюджет | off. Ветко-специфичность
(Скаут — бюджет, флагман — adaptive, scope — off) держится на ЭТОЙ функции + конфигах."""
from core import llm


def test_adaptive_unchanged():
    # обратная совместимость: старое `thinking: adaptive` работает как раньше (важно — флагман на нём)
    assert llm.resolve_thinking("adaptive") == {"type": "adaptive"}


def test_int_becomes_budget():
    assert llm.resolve_thinking(2500) == {"type": "enabled", "budget_tokens": 2500}
    assert llm.resolve_thinking(4000) == {"type": "enabled", "budget_tokens": 4000}


def test_off_variants_return_none():
    assert llm.resolve_thinking(None) is None
    assert llm.resolve_thinking("") is None
    assert llm.resolve_thinking(0) is None          # не >0 → выключено
    assert llm.resolve_thinking(-1) is None


def test_bool_is_not_budget():
    # bool — подкласс int; `thinking: true/false` НЕ должно стать бюджетом
    assert llm.resolve_thinking(True) is None
    assert llm.resolve_thinking(False) is None


# ── КОНФИГ МЫШЛЕНИЯ ПРИВОДИМ К ТОМУ, ЧТО МОДЕЛЬ ПРИНИМАЕТ (28.08) ───────────────────────────────
# `budget_tokens` снят на Opus 4.7/4.8/5, Sonnet 5 и Fable 5 — там это 400 на весь прогон. Пока
# бюджет просил один Скаут (Sonnet 4.6), это было неважно; но роли теперь переезжают на модели
# новее ради цены, и молчащий конфиг превратился бы в упавший прогон.

def test_budget_dropped_on_models_without_it():
    assert llm._thinking_for("claude-sonnet-5", {"type": "enabled", "budget_tokens": 2500}) is None
    assert llm._thinking_for("claude-opus-4-8", {"type": "enabled", "budget_tokens": 2500}) is None


def test_budget_kept_where_it_still_works():
    th = {"type": "enabled", "budget_tokens": 2500}
    assert llm._thinking_for("claude-sonnet-4-6", th) == th


def test_adaptive_passes_on_sonnet_5():
    """Sonnet 5 мышление УМЕЕТ — просто адаптивное; молча снимать его нельзя."""
    assert llm._thinking_for("claude-sonnet-5", {"type": "adaptive"}) == {"type": "adaptive"}


def test_adaptive_still_stripped_for_haiku():
    """Старое поведение цело: в /test-режиме Haiku не умеет adaptive, иначе 400."""
    assert llm._thinking_for("claude-haiku-4-5", {"type": "adaptive"}) is None


def test_no_thinking_stays_none():
    assert llm._thinking_for("claude-sonnet-5", None) is None


# ── «БЕЗ МЫШЛЕНИЯ» НАДО ГОВОРИТЬ ВСЛУХ (10.09.2026) ─────────────────────────────────────────────
# Мини-флагман Threads на Sonnet 5 вернул пустую серию: 16384 токена вывода (весь потолок) и ни
# одного блока текста — модель новее думает ПО УМОЛЧАНИЮ, а конфиг роли (THREADS_THINKING = off)
# просто не присылал параметр. «Не прислать» ≠ «выключить». Тот же корень ловили 07.09 у судьи
# обложек и лечили точечно; теперь он закрыт в llm.reply для всех ролей сразу.

class _Resp:
    def __init__(self, text="", stop="end_turn", out=10):
        self.stop_reason = stop
        self.content = ([type("B", (), {"type": "text", "text": text})()] if text
                        else [type("B", (), {"type": "thinking", "thinking": "..."})()])
        self.usage = type("U", (), {"input_tokens": 1, "output_tokens": out,
                                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0})()


def _fake_client(monkeypatch, answers):
    """Клиент, отдающий заранее заготовленные ответы; собирает параметры каждого вызова."""
    seen = []

    class _Msgs:
        def create(self, **kw):
            seen.append(kw)
            return answers[len(seen) - 1]

    class _Client:
        messages = _Msgs()

    monkeypatch.setattr(llm, "_client", lambda *a, **k: _Client())
    monkeypatch.setattr(llm.cost, "record", lambda *a, **k: None)
    return seen


def test_off_is_sent_as_disabled_on_thinking_models(monkeypatch):
    """Конфиг сказал off → в запрос уходит ЯВНОЕ thinking=disabled, а не молчание."""
    seen = _fake_client(monkeypatch, [_Resp("готово")])
    text, _ = llm.reply("claude-sonnet-5", "sys", [], "задача", [], lambda *_: "", "key", None)
    assert text == "готово"
    assert seen[0].get("thinking") == {"type": "disabled"}


def test_model_without_thinking_gets_no_param(monkeypatch):
    """Haiku мышления не умеет — параметр не шлём вовсе (иначе 400 на весь прогон)."""
    seen = _fake_client(monkeypatch, [_Resp("готово")])
    llm.reply("claude-haiku-4-5", "sys", [], "задача", [], lambda *_: "", "key", None)
    assert "thinking" not in seen[0]


def test_thinking_ate_the_ceiling_is_retried_without_it(monkeypatch):
    """Пустой текст + упор в потолок = повтор с выключенным мышлением, а не пустой прогон."""
    seen = _fake_client(monkeypatch, [_Resp("", stop="max_tokens", out=16384), _Resp("серия")])
    text, _ = llm.reply("claude-sonnet-5", "sys", [], "задача", [], lambda *_: "", "key",
                        {"type": "adaptive"})
    assert text == "серия", "после повтора текст обязан прийти"
    assert seen[0].get("thinking") == {"type": "adaptive"}
    assert seen[1].get("thinking") == {"type": "disabled"}
