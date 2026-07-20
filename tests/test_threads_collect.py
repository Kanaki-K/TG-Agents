"""Тесты бережного сбора Threads: watermark, пропуск старых, НЕзатирание метрик. Без сети.

Охраняют данные и аккаунт, а не фичу. Каждый тест соответствует конкретному багу, найденному
15.07.2026 при разборе того, как выгрузка 14.07 привела к проверке аккаунта.
"""
import time

import pytest

from connectors.threads import _api, collect


def _iso(days_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - days_ago * 86400))


def _post(pid: str, days_ago: float, text: str = "текст") -> dict:
    return {"platform": "threads", "id": pid, "text": text, "timestamp": _iso(days_ago),
            "permalink": f"https://threads.net/{pid}", "media_type": "TEXT_POST", "is_quote": False}


class _Net:
    """Подставная сеть: хранит, что «вернуть», и записывает, что у неё СПРОСИЛИ.

    Проверяем именно `asked` — суть всей работы в том, чтобы лишних запросов не было.
    """

    def __init__(self):
        self.posts: list[dict] = []
        self.metrics: dict[str, dict] = {}
        self.audience: dict[str, dict] = {}
        self.asked = {"since": None, "metrics": [], "replies": []}


@pytest.fixture
def net(monkeypatch):
    n = _Net()

    def fake_recent(limit=25, since=None, until=None):
        n.asked["since"] = since
        return n.posts

    def fake_metrics_for(ids):
        n.asked["metrics"] = list(ids)
        return {i: dict(n.metrics.get(i, {})) for i in ids}

    def fake_audience(ids):
        n.asked["replies"] = list(ids)
        return {i: dict(n.audience.get(i, {})) for i in ids}

    monkeypatch.setattr(collect.read, "recent", fake_recent)
    monkeypatch.setattr(collect.insights, "metrics_for", fake_metrics_for)
    monkeypatch.setattr(collect.replies, "audience_for_many", fake_audience)
    return n


# --- Затирание метрик: главный баг -------------------------------------------------

def test_metrics_error_does_not_wipe_earned_numbers():
    """При ошибке метрик прежние цифры ОСТАЮТСЯ. Раньше 429 молча превращал базу в нули."""
    old_row = {"id": "1", "views": 5000, "likes": 100, "engagement": 120, "er": 2.4,
               "people_replies": 7, "people_count": 5}
    new_row = {"id": "1", "views": 0, "likes": 0, "engagement": 0, "er": None,
               "people_replies": 0, "people_count": 0, "metrics_error": "Threads API 429: limit"}
    merged = collect._merge_keep(old_row, new_row)
    assert merged["views"] == 5000, "рейт-лимит затёр накопленные просмотры"
    assert merged["likes"] == 100
    assert merged["metrics_stale"] is True, "нет пометки, что цифра старая"


def test_successful_metrics_do_overwrite():
    """Обратная сторона: удачный прогон обязан обновлять цифры, иначе они замрут навсегда."""
    old_row = {"id": "1", "views": 100, "likes": 5}
    new_row = {"id": "1", "views": 900, "likes": 40, "metrics_error": None}
    merged = collect._merge_keep(old_row, new_row)
    assert merged["views"] == 900 and merged["likes"] == 40


def test_replies_error_does_not_wipe_people():
    old_row = {"id": "1", "people_replies": 9, "people_count": 6, "self_replies": 2}
    new_row = {"id": "1", "people_replies": 0, "people_count": 0, "self_replies": 0,
               "replies_error": "Threads API 500"}
    merged = collect._merge_keep(old_row, new_row)
    assert merged["people_replies"] == 9 and merged["people_count"] == 6


def test_new_post_passes_through():
    new_row = {"id": "new", "views": 10}
    assert collect._merge_keep(None, new_row) == new_row


# --- Watermark ---------------------------------------------------------------------

def test_watermark_none_on_empty_base():
    assert collect._watermark({}) is None, "первый сбор должен идти с начала ленты"


def test_watermark_from_newest_with_overlap():
    old = {"1": {"date": _iso(30)}, "2": {"date": _iso(3)}, "3": {"date": _iso(100)}}
    wm = collect._watermark(old)
    assert wm is not None
    age_days = (time.time() - wm) / 86400
    # самый свежий пост 3 дня назад + нахлёст 7 → окно примерно 10 дней
    assert 9 < age_days < 11, f"окно {age_days:.1f} дн — нахлёст потерян или неверен"


def test_collect_asks_feed_from_watermark(net):
    """Повторный прогон НЕ тянет ленту с нуля — это дыра, из-за которой 14.07 три захода
    превратились в три полных прохода."""
    net.posts = [_post("1", 1)]
    old = {"9": {"id": "9", "date": _iso(5), "views": 10}}
    collect.collect_posts(500, old)
    assert net.asked["since"] is not None, "since не передан — лента тянется заново"


# --- Пропуск старых постов ----------------------------------------------------------

def test_old_posts_skip_metrics(net):
    """Пост старше 30 дней уже не растёт — незачем на него тратить запрос."""
    net.posts = [_post("fresh", 2), _post("old", 200)]
    old = {"old": {"id": "old", "date": _iso(200), "views": 800, "likes": 30}}
    collect.collect_posts(500, old)
    assert "old" not in net.asked["metrics"], "запросили метрики старого поста впустую"
    assert "fresh" in net.asked["metrics"]


def test_skipped_post_keeps_its_metrics(net):
    """Пропуск по возрасту обязан ПЕРЕНЕСТИ старые цифры, а не оставить нули."""
    net.posts = [_post("old", 200, text="новый текст")]
    old = {"old": {"id": "old", "date": _iso(200), "views": 800, "likes": 30,
                   "people_replies": 4, "people_count": 3, "self_replies": 1}}
    rows = collect.collect_posts(500, old)
    row = rows[0]
    assert row["views"] == 800, "пропуск по возрасту обнулил метрики"
    assert row["people_replies"] == 4
    assert row["text"] == "новый текст", "текст должен обновляться даже без метрик"


def test_post_without_metrics_is_retried(net):
    """Если метрики так и не собрали — пробуем снова, независимо от возраста."""
    net.posts = [_post("old", 200)]
    old = {"old": {"id": "old", "date": _iso(200), "views": 0, "metrics_error": "прошлый сбой"}}
    collect.collect_posts(500, old)
    assert "old" in net.asked["metrics"]


def test_old_posts_skip_replies(net):
    """Под старым постом новые комменты не появятся — не перезапрашиваем разбор."""
    net.posts = [_post("old", 200)]
    old = {"old": {"id": "old", "date": _iso(200), "views": 800, "replies": 5,
                   "people_replies": 4, "people_count": 3, "self_replies": 1}}
    collect.collect_posts(500, old)
    assert net.asked["replies"] == [], "зря полезли за комментами старого поста"


# --- Защита останавливает сбор, не ломая базу ---------------------------------------

def test_blocked_run_does_not_touch_base(net, monkeypatch, tmp_path, capsys):
    """Сработала защита → база на диске НЕ трогается. Лучше вчерашние данные, чем мусор."""
    posts_file = tmp_path / "threads_posts.json"
    posts_file.write_text('[{"id": "1", "views": 5000, "date": "2026-07-01T10:00:00"}]',
                          encoding="utf-8")
    monkeypatch.setattr(collect, "POSTS_OUT", posts_file)
    monkeypatch.setattr(collect, "DATA", tmp_path)
    monkeypatch.setattr(collect.sys, "argv", ["collect"])

    def blocked(*a, **kw):
        raise _api.ThreadsBlocked("предохранитель после троттлинга")

    monkeypatch.setattr(collect, "collect_posts", blocked)
    collect.main()
    assert '"views": 5000' in posts_file.read_text(encoding="utf-8"), "база пострадала при блокировке"
    assert "остановлен защитой" in capsys.readouterr().out
