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

# Вёрстка настоящей страницы поста (снимок 09.09.2026): СНАЧАЛА список последних постов с их
# просмотрами, и только потом карточка самого поста. Именно поэтому нужен якорь по разделу.
POST_PAGE_HTML = """<html><body>
<div>Статистика профиля, зрителей и подписчиков</div>
<div>Последние публикации</div>
<div>Чужой пост из списка</div><div>1</div><div>22</div><div>Просмотры</div>
<div>Ещё один чужой пост</div><div>3</div><div>999</div><div>Просмотры</div>
<div>Статистика публикации</div><div>Просмотреть публикацию</div>
<div>kanaki.crypto</div><div>1 дн.</div>
<div>Биткоин чувствует деньги раньше почти всех активов</div>
<div>Сводка</div>
<div>Просмотры</div><div>309</div><div>Выше</div>
<div>Посещения профиля</div><div>4</div><div>Обычный</div>
<div>Зрители</div><div>276</div><div>Выше</div>
<div>Подписки</div><div>1</div><div>Обычный</div>
<div>Что влияет на число просмотров</div>
<div>Доля отметок "Нравится"</div><div>0,82 %</div><div>Обычный</div>
<div>Доля ответов</div><div>0 %</div><div>Обычный</div>
<div>Основные источники просмотров</div>
<div>Главная</div><div>99,45 %</div><div>Instagram</div><div>0,55 %</div></body></html>"""


def aged(path):
    """Состарить файл на 5 минут: свежие снимки intake намеренно не трогает (их ещё пишет браузер)."""
    import os
    import time as _t
    os.utime(path, (_t.time() - 300, _t.time() - 300))
    return path


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
    aged(env / "insights-2026-09-09.html")
    report = P.intake()
    assert "цифры аккаунта" in report
    assert not (env / "app.json").exists()
    row = json.loads((env / "account.jsonl").read_text(encoding="utf-8").strip())
    assert row["net_followers"] == 3 and row["followers"] == 619


def test_processed_file_is_moved_away(env):
    """Иначе следующий прогон перезапишет свежие цифры вчерашними — метрики растут со временем."""
    (env / "insights-2026-09-09.html").write_text(ACCOUNT_PAGE, encoding="utf-8")
    aged(env / "insights-2026-09-09.html")
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
    aged(env / "insights-post-DdEgJ0_CDig-2026-09-09.html")
    report = P.intake()
    saved = json.loads((env / "app.json").read_text(encoding="utf-8"))
    assert "✅" in report
    assert saved["1"]["profile_visits"] == 4 and saved["1"]["new_followers"] == 1


def test_unknown_code_is_not_guessed(env):
    (env / "insights-post-ZZZZZZZZZZZ-2026-09-09.html").write_text(POST_PAGE_HTML, encoding="utf-8")
    aged(env / "insights-post-ZZZZZZZZZZZ-2026-09-09.html")
    assert "не найден" in P.intake()


def test_post_page_reads_the_card_not_the_list_above_it():
    """Страница поста начинается со СПИСКА постов. Без якоря по разделу разбор брал 999 просмотров
    чужого поста из списка — то есть тихо приписывал посту чужие цифры."""
    nums, _ = P.parse_post_page(P.to_text(POST_PAGE_HTML))
    assert nums["views"] == 309 and nums["viewers"] == 276
    assert nums["profile_visits"] == 4


def test_subscriptions_row_is_new_followers():
    """На веб-странице метрика названа «Подписки», в приложении — «Нові читачі». Одна и та же."""
    nums, _ = P.parse_post_page(P.to_text(POST_PAGE_HTML))
    assert nums["new_followers"] == 1


def test_influence_shares_are_kept_apart_from_counters():
    """Проценты влияния — показание площадки о том, что двигало охват. Держим их отдельно от
    счётчиков: смешаешь — однажды сложишь 366 просмотров с 0,82 процента."""
    nums, factors = P.parse_post_page(P.to_text(POST_PAGE_HTML))
    assert factors["like_share"] == 0.82 and factors["reply_share"] == 0.0
    assert factors["src_home"] == 99.45 and factors["src_instagram"] == 0.55
    assert all(not isinstance(v, float) for v in nums.values())


def test_file_being_written_right_now_is_left_alone(env):
    """Браузер снимает страницы часами. Разобрать половину и увезти в processed = потерять пост."""
    f = env / "insights-post-DdEgJ0_CDig-2026-09-09.html"
    f.write_text(POST_PAGE_HTML, encoding="utf-8")     # свежий файл, mtime = сейчас
    P.intake()
    assert f.exists()                                  # не увезён
    assert not (env / "app.json").exists()             # и не разобран наполовину


def test_unparsed_file_stays_for_a_second_chance(env):
    """Увезённый файл — потерянный день: вёрстка могла измениться, и он понадобится после починки."""
    f = env / "insights-post-DdEgJ0_CDig-2026-09-09.html"
    f.write_text("<html><body>ничего похожего на статистику</body></html>", encoding="utf-8")
    aged(f)
    P.intake()
    assert f.exists() and not (env / "processed" / f.name).exists()
