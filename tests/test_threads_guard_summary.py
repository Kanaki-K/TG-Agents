"""Тесты сводки расхода и адекватности бюджетов (connectors/threads/_guard)."""
from connectors.threads import _guard


def test_classify_endpoints():
    assert _guard._classify("17841400000/insights") == "метрики"
    assert _guard._classify("17999/replies") == "комменты"
    assert _guard._classify("17841400000/threads") == "лента/посты"
    assert _guard._classify("me") == "прочее"


def test_run_summary_shows_spend_and_usage(monkeypatch, tmp_path):
    monkeypatch.setattr(_guard, "LOG_FILE", tmp_path / "log.jsonl")   # пустой журнал → сутки 0
    monkeypatch.setattr(_guard, "_run_count", 3)
    monkeypatch.setattr(_guard, "_run_by_kind", {"метрики": 2, "комменты": 1})
    monkeypatch.setattr(_guard, "_peak_usage_pct", 12.5)
    s = _guard.run_summary()
    assert "всего: 3" in s
    assert "метрики: 2" in s and "комменты: 1" in s
    assert "пик 12.5%" in s
    assert f"/{_guard.DAY_BUDGET}" in s          # дневной остаток виден


def test_budgets_adequate_for_a_full_collect():
    # инкрементальный сбор стоит ~50-120 запросов — бюджеты не должны душить его
    assert _guard.RUN_BUDGET >= 150
    assert _guard.DAY_BUDGET >= 400
    # и всё ещё намного ниже пола Meta (~48 000/сутки)
    assert _guard.DAY_BUDGET < 5000
