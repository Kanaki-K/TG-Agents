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
