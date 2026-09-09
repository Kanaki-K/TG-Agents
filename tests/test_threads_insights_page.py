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


ACCOUNT_PAGE = """<html><body>
<div>Übersicht</div><div>Letzte 30 Tage</div><div>Zusammenfassung</div>
<div>Aufrufe</div><div>70.797</div><div>-33,2%</div>
<div>Betrachter</div><div>59.282</div><div>-14,2%</div>
<div>Netto-Follower</div><div>+3</div><div>+0,5%</div>
<div>Interaktionen</div><div>837</div><div>-56,5%</div>
<div>Arten von Betrachtern</div><div>Follower</div><div>171</div><div>-9,5%</div>
<div>Nicht-Follower</div><div>59.111</div><div>-14,2%</div>
<div>Follower</div><div>619</div><div>+0,5%</div></body></html>"""

POST_PAGE_HTML = """<html><body><div>kanaki.crypto</div><div>22 год</div>
<div>Биткоин чувствует деньги раньше почти всех активов</div>
<div>Сводка</div><div>Просмотры</div><div>309</div><div>Как обычно</div>
<div>Посещения профиля</div><div>4</div><div>Выше</div>
<div>Зрители</div><div>276</div><div>Как обычно</div>
<div>Новые подписчики</div><div>1</div><div>Выше</div></body></html>"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    posts = [{"id": "1", "date": "2026-09-08T16:00:00+0000",
              "permalink": "https://www.threads.com/@kanaki.crypto/post/DdEgJ0_CDig",
              "text": "Биткоин чувствует деньги раньше почти всех активов"},
             {"id": "2", "date": "2026-09-07T16:00:00+0000", "text": "Защита сработала идеально"}]
    (tmp_path / "posts.json").write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(A, "THREADS_POSTS", tmp_path / "posts.json")
    monkeypatch.setattr(A, "STORE", tmp_path / "app.json")
    monkeypatch.setattr(P, "INCOMING", tmp_path)
    monkeypatch.setattr(P, "DONE", tmp_path / "processed")
    # Журнал аккаунта уводим ЗДЕСЬ, а не в отдельных тестах: пока он уводился по месту, два прогона
    # этого файла записали тестовые цифры в боевой data/threads_account_insights.jsonl. Дымовой
    # прогон обязан уводить ВСЕ пути записи модуля, а не те, о которых вспомнил автор теста.
    monkeypatch.setattr(P, "ACCOUNT_LOG", tmp_path / "account.jsonl")
    return tmp_path


def test_scripts_do_not_leak_numbers():
    """Число внутри <script> не должно стать метрикой — иначе разбор ловил бы мусор из кода."""
    assert "999" not in P.to_text(PAGE)


def test_overview_goes_to_the_account_journal_not_to_posts(env):
    """Общая страница НЕ даёт заходов в профиль — на живой странице их там нет вовсе. Поэтому её
    цифры идут в журнал аккаунта, а не в метрики постов: иначе мы записали бы половинчатые данные
    поверх полных, снятых со страницы самого поста."""
    (env / "insights-2026-09-09.html").write_text(ACCOUNT_PAGE, encoding="utf-8")
    report = P.intake()
    assert "цифры аккаунта" in report
    assert not (env / "app.json").exists()
    row = json.loads((env / "account.jsonl").read_text(encoding="utf-8").strip())
    assert row["net_followers"] == 3 and row["followers"] == 619


def test_processed_file_is_moved_away(env):
    """Иначе следующий прогон перезапишет свежие цифры вчерашними — метрики растут со временем."""
    (env / "insights-2026-09-09.html").write_text(ACCOUNT_PAGE, encoding="utf-8")
    P.intake()
    assert not (env / "insights-2026-09-09.html").exists()
    assert (env / "processed" / "insights-2026-09-09.html").exists()


def test_no_files_is_silence_not_an_error(env):
    assert P.intake() == ""


def test_account_numbers_read_by_words_not_layout(env):
    """Немецкий интерфейс — не гипотетика: свежий профиль headless отдал именно его."""
    acc = P.parse_account(P.to_text(ACCOUNT_PAGE))
    assert acc["views"] == 70797 and acc["viewers"] == 59282
    assert acc["net_followers"] == 3 and acc["interactions"] == 837


def test_two_meanings_of_followers_are_separated(env):
    """«Подписчики» на странице дважды: увидело 171, всего 619. Спутать их — испортить замер."""
    acc = P.parse_account(P.to_text(ACCOUNT_PAGE))
    assert acc["follower_viewers"] == 171
    assert acc["followers"] == 619


def test_post_page_binds_by_code_from_filename(env):
    (env / "insights-post-DdEgJ0_CDig-2026-09-09.html").write_text(POST_PAGE_HTML, encoding="utf-8")
    report = P.intake()
    saved = json.loads((env / "app.json").read_text(encoding="utf-8"))
    assert "✅" in report
    assert saved["1"]["profile_visits"] == 4 and saved["1"]["new_followers"] == 1


def test_unknown_code_is_not_guessed(env):
    (env / "insights-post-ZZZZZZZZZZZ-2026-09-09.html").write_text(POST_PAGE_HTML, encoding="utf-8")
    assert "не найден" in P.intake()
