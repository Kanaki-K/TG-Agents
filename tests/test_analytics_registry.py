"""Тесты общего реестра аналитич. инструментов (core/analytics_tools, дедуп P2-13).

Без данных/сети: проверяем ВИЛКУ (handle) и что дедуп dispatch НЕ удалил схемы у агентов
(модель по-прежнему видит инструменты — поменялась только внутренняя маршрутизация)."""
from core import analytics_tools, analyst_tools, creator_tools, scout_tools

SHARED = {"channel_summary", "find_posts", "by_theme", "themes_overview", "by_dimension", "recent_posts"}


def _names(mod):
    return {t["name"] for t in mod.TOOLS}


def test_handle_unknown_returns_none():
    assert analytics_tools.handle("definitely-not-a-tool", {}) is None


def test_shared_registry_keys():
    assert set(analytics_tools._SHARED) == SHARED


def test_schemas_preserved_after_dispatch_dedup():
    # схемы инструментов НЕ удалялись — убрали только дублирующиеся ветки dispatch
    assert {"find_posts", "by_theme", "themes_overview", "channel_summary"} <= _names(scout_tools)
    assert {"find_posts", "by_theme", "themes_overview", "channel_summary",
            "by_dimension", "recent_posts"} <= _names(analyst_tools)
    assert {"find_posts", "by_theme", "themes_overview", "by_dimension", "recent_posts"} <= _names(creator_tools)


def test_no_duplicate_tool_names_per_agent():
    for mod in (analyst_tools, scout_tools, creator_tools):
        names = [t["name"] for t in mod.TOOLS]
        assert len(names) == len(set(names)), mod.__name__
