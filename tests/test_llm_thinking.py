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
