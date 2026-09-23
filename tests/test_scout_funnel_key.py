"""Воронка Скаута ходит со СВОИМ ключом (24.09.2026).

Оба вызова sift() в scout_tools шли без ключа, llm брал общий ANTHROPIC_API_KEY — недействительный (401),
и воронка падала молча на каждом прогоне: Sonnet Скаута разбирал весь сырой вал."""
from core import scout_funnel


def test_sift_uses_the_scout_key_by_default(monkeypatch):
    seen = {}

    def reply(model, system, hist, user, tools, dispatch, api_key, *a, **k):
        seen["key"] = api_key
        return "KEEP: 0", None
    monkeypatch.setattr(scout_funnel.llm, "reply", reply)
    monkeypatch.setattr(scout_funnel.config, "load_agent", lambda n: {"api_key_env": "SCOUT_KEY"} if n == "scout" else {})
    monkeypatch.setattr(scout_funnel.config, "agent_api_key", lambda cfg: "scout-key" if cfg else "general")
    items = [{"text": f"пост {i}", "channel": "c"} for i in range(40)]
    scout_funnel.sift(items, keep=5)
    assert seen["key"] == "scout-key"


def test_funnel_failure_is_loud(monkeypatch, caplog):
    monkeypatch.setattr(scout_funnel.llm, "reply", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("401")))
    items = [{"text": f"пост {i}", "channel": "c"} for i in range(40)]
    assert scout_funnel.sift(items, keep=5, api_key="k") == items
    assert any("отсев не сработал" in r.message for r in caplog.records)
