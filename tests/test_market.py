"""Ценовой коннектор (connectors/market) — чистые юниты без сети."""
from connectors.market import price
from core import market_tools


def test_norm_symbols_sanitizes_and_dedups():
    assert price._norm_symbols("btc, eth ,btc") == ["BTC", "ETH"]
    assert price._norm_symbols(["sol", "x/y"]) == ["SOL", "XY"]
    assert price._norm_symbols("") == []
    assert len(price._norm_symbols(",".join(str(i) for i in range(40)))) <= price._MAX_SYMBOLS


def test_fmt_price_scales_by_magnitude():
    assert price._fmt_price(58804.3) == "$58,804"
    assert price._fmt_price(2.5) == "$2.50"
    assert price._fmt_price(0.0123) == "$0.0123"


def test_fmt_cap_units():
    assert price._fmt_cap(1.16e12) == "$1.16T"
    assert price._fmt_cap(7e9) == "$7.00B"


def test_spot_without_key_is_soft(monkeypatch):
    # нет ключа → понятное сообщение, без сети и без падения
    monkeypatch.delenv("COINMARKETCAP_API_KEY", raising=False)
    price._cache.clear()
    out = price.spot("BTC")
    assert "COINMARKETCAP_API_KEY" in out


def test_tool_dispatch_routes_market_price(monkeypatch):
    monkeypatch.setattr(price, "spot", lambda symbols="BTC,ETH": f"PRICED:{symbols}")
    assert market_tools.handle("market_price", {"symbols": "BTC"}) == "PRICED:BTC"
    assert market_tools.handle("market_price", {}) == "PRICED:BTC,ETH"
    assert market_tools.handle("something_else", {}) is None
