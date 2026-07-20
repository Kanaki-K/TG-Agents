"""Тесты журнального линкера (core/threads_distill_link): ID → тугой текст серии."""
from core import threads_distill_link as dl

ENTRY = {
    "flagship_date": "2026-07-16", "theme": "IRR — иксы врут", "category": "рынок",
    "posts": ["иксы врут годовых процент дистанция", "доходность удвоение актив держать"],
    "post_ids": [],
}


def test_tight_text_match():
    posts = [{"id": "1", "text": "иксы врут годовых процент дистанция"}]
    r = dl.link([ENTRY], posts)
    assert len(r["groups"]) == 1
    g = r["groups"][0]
    assert g["entry"]["category"] == "рынок"
    assert g["posts"][0]["via"] == "text" and g["posts"][0]["coverage"] >= 0.55
    assert r["unmatched"] == []


def test_deterministic_by_id_ignores_text():
    e = dict(ENTRY, post_ids=["999"])
    posts = [{"id": "999", "text": "совсем другой текст даже без общих слов вообще"}]
    r = dl.link([e], posts)
    assert len(r["groups"]) == 1
    assert r["groups"][0]["posts"][0]["via"] == "id"


def test_low_coverage_unmatched():
    posts = [{"id": "2", "text": "посторонний личный пост совсем другими словами"}]
    r = dl.link([ENTRY], posts)
    assert r["groups"] == [] and len(r["unmatched"]) == 1


def test_no_entries_all_unmatched():
    r = dl.link([], [{"id": "1", "text": "что угодно тут написано"}])
    assert r["groups"] == [] and len(r["unmatched"]) == 1
