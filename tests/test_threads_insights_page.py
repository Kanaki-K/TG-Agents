"""Разбор страницы Insights, снятой браузером владельца.

Главное, что держат тесты: разбор идёт по СЛОВАМ интерфейса, а не по вёрстке (она меняется), и с
одной страницы снимаются ВСЕ посты сразу — ради этого весь механизм и строился, ручной путь
владелец отверг прямо («мне нужно решение на дистанцию»)."""
import json

import pytest

from core import threads_app_metrics as A
from core import threads_insights_page as P

PAGE = """<html><body><script>var x = "Перегляди 999"</script>
<div class="x7a8b"><span>kanaki.crypto</span><span>22 год</span></div>
<div>Биткоин чувствует деньги раньше почти всех активов</div>
<div>Зведення</div><div>Перегляди</div><div>309</div><div>Як зазвичай</div>
<div>Відвідування профілю</div><div>4</div><div>Вище</div>
<div>Глядачі</div><div>276</div><div>Як зазвичай</div>
<div>Нові читачі</div><div>1</div><div>Вище</div>
<div><span>kanaki.crypto</span><span>2 дн</span></div>
<div>Защита сработала идеально</div>
<div>Зведення</div><div>Перегляди</div><div>297</div><div>Як зазвичай</div>
<div>Нові читачі</div><div>0</div><div>Як зазвичай</div></body></html>"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    posts = [{"id": "1", "date": "2026-09-08T16:00:00+0000",
              "text": "Биткоин чувствует деньги раньше почти всех активов"},
             {"id": "2", "date": "2026-09-07T16:00:00+0000", "text": "Защита сработала идеально"}]
    (tmp_path / "posts.json").write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(A, "THREADS_POSTS", tmp_path / "posts.json")
    monkeypatch.setattr(A, "STORE", tmp_path / "app.json")
    monkeypatch.setattr(P, "INCOMING", tmp_path)
    monkeypatch.setattr(P, "DONE", tmp_path / "processed")
    return tmp_path


def test_scripts_do_not_leak_numbers():
    """Число внутри <script> не должно стать метрикой — иначе разбор ловил бы мусор из кода."""
    assert "999" not in P.to_text(PAGE)


def test_whole_page_gives_every_post(env):
    (env / "insights-2026-09-09.html").write_text(PAGE, encoding="utf-8")
    report = P.intake()
    saved = json.loads((env / "app.json").read_text(encoding="utf-8"))
    assert report.count("✅") == 2
    assert saved["1"]["new_followers"] == 1 and saved["1"]["profile_visits"] == 4
    assert saved["2"]["views"] == 297 and saved["2"]["new_followers"] == 0


def test_processed_file_is_moved_away(env):
    """Иначе следующий прогон перезапишет свежие цифры вчерашними — метрики растут со временем."""
    (env / "insights-2026-09-09.html").write_text(PAGE, encoding="utf-8")
    P.intake()
    assert not (env / "insights-2026-09-09.html").exists()
    assert (env / "processed" / "insights-2026-09-09.html").exists()


def test_no_files_is_silence_not_an_error(env):
    assert P.intake() == ""
