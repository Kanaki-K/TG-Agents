"""Скаут — непокрытая машинерия капремонта 13.07: воронка (parse/sift) + watermark (filter/commit).
Аудит 20.07: scout_funnel/scout_seen чисто детерминированы, но без единого теста. Тесты ЗАЩИЩАЮТ
реконструированный код от регресса + локают фикс мис-атрибуции cost-контекста."""
from connectors.x_scan import read as x_read
from core import scout_funnel, scout_seen, scout_tools


# --- воронка: разбор ответа Haiku ---

def test_parse_keep_valid_in_range_dedup_order():
    # 40 вне диапазона [0,10), дубль 3 убран, порядок сохранён
    assert scout_funnel._parse_keep("KEEP: 3, 0, 3, 40, 7", 10) == [3, 0, 7]


def test_parse_keep_garbage_and_empty():
    assert scout_funnel._parse_keep("ничего не распарсил", 10) == []
    assert scout_funnel._parse_keep("", 10) == []


def test_parse_keep_without_prefix_reads_numbers():
    assert scout_funnel._parse_keep("оставил 1 и 4", 10) == [1, 4]   # нет 'KEEP:' → числа из всего текста


# --- воронка: sift (порог / фейл-открыто / пропуск ошибок) ---

def test_sift_below_threshold_is_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(scout_funnel.llm, "reply", lambda *a, **k: calls.append(1))
    items = [{"text": f"t{i}"} for i in range(5)]
    assert scout_funnel.sift(items, keep=20) is items   # ≤keep → Haiku не звали
    assert calls == []


def test_sift_filters_and_passes_errors(monkeypatch):
    monkeypatch.setattr(scout_funnel.llm, "reply", lambda *a, **k: ("KEEP: 0, 2", []))
    real = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    err = {"error": "источник упал"}
    out = scout_funnel.sift(real + [err], keep=2)
    assert {"text": "a"} in out and {"text": "c"} in out
    assert {"text": "b"} not in out
    assert err in out   # ошибки ВСЕГДА проходят к Скауту (он должен видеть падение источника)


def test_sift_failopen_on_unparseable(monkeypatch):
    monkeypatch.setattr(scout_funnel.llm, "reply", lambda *a, **k: ("бла-бла", []))
    items = [{"text": f"t{i}"} for i in range(25)]
    assert scout_funnel.sift(items, keep=2) is items   # не распарсили → всё как есть


def test_sift_failopen_on_model_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("haiku down")
    monkeypatch.setattr(scout_funnel.llm, "reply", boom)
    items = [{"text": f"t{i}"} for i in range(25)]
    assert scout_funnel.sift(items, keep=2) is items   # модель упала → не режем


def test_sift_restores_cost_context(monkeypatch):
    # ФИКС 20.07: воронка не должна оставлять контекст 'funnel' — иначе последующие турны Скаута
    # (дорогой Sonnet) билятся как 'funnel', искажая учёт расходов
    monkeypatch.setattr(scout_funnel.llm, "reply", lambda *a, **k: ("KEEP: 0", []))
    scout_funnel.cost.set_context("scout")
    scout_funnel.sift([{"text": f"t{i}"} for i in range(25)], keep=2)
    assert scout_funnel.cost.get_context() == "scout"


# --- watermark ---

def _reset_seen(monkeypatch, tmp_path):
    monkeypatch.setattr(scout_seen, "SEEN_FILE", tmp_path / "scout_seen.json")
    monkeypatch.setattr(scout_seen, "_pending", {})


def test_filter_new_hides_seen_across_runs(monkeypatch, tmp_path):
    _reset_seen(monkeypatch, tmp_path)
    idf = (lambda it: it["link"])
    items = [{"name": "rss", "link": "u1"}, {"name": "rss", "link": "u2"}]
    assert len(scout_seen.filter_new(items, "name", idf)) == 2   # первый прогон — всё новое
    scout_seen.commit()                                          # зафиксировали watermark
    out = scout_seen.filter_new(items + [{"name": "rss", "link": "u3"}], "name", idf)
    assert [it["link"] for it in out] == ["u3"]                  # старые скрыты, свежее видно


def test_filter_new_passes_errors(monkeypatch, tmp_path):
    _reset_seen(monkeypatch, tmp_path)
    err = {"name": "rss", "error": "down"}
    assert err in scout_seen.filter_new([err], "name", lambda it: it.get("link"))


def test_filter_new_no_disk_write_and_intra_run_dedup(monkeypatch, tmp_path):
    _reset_seen(monkeypatch, tmp_path)
    idf = (lambda it: it["link"])
    scout_seen.filter_new([{"name": "rss", "link": "u1"}], "name", idf)
    assert not (tmp_path / "scout_seen.json").exists()   # диск не тронут до commit
    # повторный скан того же В ОДНОМ прогоне — _pending дедупит
    assert scout_seen.filter_new([{"name": "rss", "link": "u1"}], "name", idf) == []


def test_commit_caps_at_seen_cap(monkeypatch, tmp_path):
    _reset_seen(monkeypatch, tmp_path)
    monkeypatch.setattr(scout_seen, "SEEN_CAP", 3)
    idf = (lambda it: it["link"])
    scout_seen.filter_new([{"name": "rss", "link": f"u{i}"} for i in range(5)], "name", idf)
    scout_seen.commit()
    seen = scout_seen._load()
    assert len(seen["rss"]) == 3                       # держим последние SEEN_CAP
    assert set(seen["rss"]) <= {f"u{i}" for i in range(5)}


# --- деградация источника: баннер + структурный след (аудит 20.07) ---

def test_banner_empty_when_live_records():
    scout_tools.reset_degraded()
    live = [{"handle": "a", "text": "живой твит"}, {"handle": "b", "error": "down"}]
    assert scout_tools._all_errors_banner(live, "X-скан") == ""   # есть живая запись → не баннер
    assert scout_tools.degraded_sources() == []                   # и след не ставим


def test_banner_and_degraded_when_all_errors():
    scout_tools.reset_degraded()
    allerr = [{"handle": "a", "error": "стена логина"}, {"handle": "b", "error": "down"}]
    assert "ИСТОЧНИК НЕДОСТУПЕН" in scout_tools._all_errors_banner(allerr, "X-скан")
    assert "X-скан" in scout_tools.degraded_sources()             # структурный след для _run_scout
    scout_tools.reset_degraded()
    assert scout_tools.degraded_sources() == []


# --- тихий login-wall X: пусто без ошибок → явная ошибка-запись ---

def test_recent_silent_empty_becomes_error(monkeypatch):
    monkeypatch.setattr(x_read, "load_leaders", lambda scope: [{"handle": "saylor", "track": "crypto"}])
    monkeypatch.setattr(x_read, "_collect_retry", lambda leaders, n: [])   # X отдал ПУСТО без ошибок
    out = x_read.recent(max_accounts=12)
    assert len(out) == 1 and "куки" in out[0]["error"].lower()   # помечено как сбой, не «тихий день»


def test_recent_live_tweets_pass_untouched(monkeypatch):
    monkeypatch.setattr(x_read, "load_leaders", lambda scope: [{"handle": "saylor", "track": "crypto"}])
    monkeypatch.setattr(x_read, "_collect_retry", lambda leaders, n: [{"handle": "saylor", "text": "BTC"}])
    assert x_read.recent() == [{"handle": "saylor", "text": "BTC"}]   # живые твиты не трогаем
