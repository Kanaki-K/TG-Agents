"""core.llm._system_cache_control — срок метки кэша системного промпта (без сети).

Запись кэша биллится дороже входа: 5m = 1.25×, 1h = 2×. Переплата за 1h окупается только если
тот же системный промпт перечитают в СЛЕДУЮЩЕМ прогоне в пределах часа. Замер журнала расходов
17.08: в боевом это случилось 2 раза из 25 (и оба уложились бы в 5m — попадание в кэш продлевает
TTL бесплатно), а внутри прогона паузы 21-48 сек. В /test прогоны идут пачкой — там 1h реально
переиспользуется. Отсюда правило: боевой — 5m (метка по умолчанию), /test — 1h.
Запуск: python -m pytest tests/test_llm_cache_ttl.py"""
from core import llm


def test_main_mode_uses_default_5m(monkeypatch):
    # боевой прогон раз в день: 1h просто сгорает, платим 2× ни за что → метка БЕЗ ttl (=5m)
    monkeypatch.setattr(llm.runmode, "get", lambda: {"mode": "main", "model": None})
    assert llm._system_cache_control() == {"type": "ephemeral"}


def test_test_mode_keeps_1h(monkeypatch):
    # дев-итерации: несколько прогонов в час, системный промпт тот же → 1h окупается
    monkeypatch.setattr(llm.runmode, "get", lambda: {"mode": "test", "model": "claude-haiku-4-5"})
    assert llm._system_cache_control() == {"type": "ephemeral", "ttl": "1h"}


def test_broken_mode_state_falls_back_to_cheap(monkeypatch):
    # состояние режима недоступно — берём дешёвую метку, а не дорогую (фейл в сторону экономии)
    def _boom():
        raise OSError("нет доступа к data/run_mode.txt")

    monkeypatch.setattr(llm.runmode, "get", _boom)
    assert llm._system_cache_control() == {"type": "ephemeral"}
