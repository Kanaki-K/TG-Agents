"""Тесты линкера (core/threads_flagship_link): Threads-пост → флагман по дате+покрытию."""
from core import threads_flagship_link as lk

FL_IRR = {"date": "2026-07-16", "theme": "IRR — иксы врут",
          "text": "иксы врут доходность годовых процент удвоение дистанция актив"}
FL_OLD = {"date": "2026-07-05", "theme": "Стейблкоины",
          "text": "стейблкоины рельсы платежи инфраструктура доллары банки переводы"}


def test_post_matches_flagship_in_window():
    posts = [{"date": "2026-07-16", "text": "иксы врут годовых процент"}]
    res = lk.link([FL_IRR, FL_OLD], posts)
    assert len(res["groups"]) == 1
    g = res["groups"][0]
    assert g["flagship"]["theme"] == "IRR — иксы врут"
    assert g["posts"][0]["coverage"] >= 0.30
    assert res["unmatched"] == []


def test_post_out_of_date_window_unmatched():
    posts = [{"date": "2026-07-25", "text": "иксы врут годовых процент"}]  # +9 дней от флагмана
    res = lk.link([FL_IRR], posts)
    assert res["groups"] == [] and len(res["unmatched"]) == 1


def test_low_coverage_unmatched():
    posts = [{"date": "2026-07-16", "text": "совсем посторонний текст без общих слов вообще"}]
    res = lk.link([FL_IRR], posts)
    assert res["groups"] == [] and len(res["unmatched"]) == 1


def test_picks_correct_flagship_by_date():
    # пост в окне СТАРОГО флагмана и с его лексикой → должен уйти к нему, не к IRR
    posts = [{"date": "2026-07-06", "text": "стейблкоины рельсы переводы банки"}]
    res = lk.link([FL_IRR, FL_OLD], posts)
    assert len(res["groups"]) == 1
    assert res["groups"][0]["flagship"]["theme"] == "Стейблкоины"


def test_post_without_date_unmatched():
    res = lk.link([FL_IRR], [{"text": "иксы врут годовых"}])
    assert len(res["unmatched"]) == 1
