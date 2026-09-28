"""Скоуп 28.09 (Glassnode, владелец 0/10): обложка KuCoin, источник ×3, гейт вернул свой же отказ."""
import json

from core import creator_tools as ct, scope_writer as sw
import run_pipeline as rp

POST = ("**📊 Объём торгов альтами вчетверо обогнал биткоин и всё равно ему проигрывает**\n\n"
        "28 сентября Glassnode показал цифру: спот-объём альткоинов подошёл к 4x объёма биткоина\n\n"
        "Звучит как альтсезон. Только у той же конторы есть вторая цифра: из топ-50 его обогнали девять\n\n"
        "Glassnode добавляет ремарку, которую в лентах обрезают")


def test_source_named_three_times_blocks_publication():
    assert any("ИСТОЧНИК НАЗВАН" in w for w in ct.publish_blockers(POST, "scope"))


def test_single_source_mention_is_fine():
    one = "SEC одобрила фонд. По данным BlackRock приток вырос вдвое\n\nВывод простой"
    assert not any("ИСТОЧНИК" in w for w in ct.publish_blockers(one, "scope"))


def test_hero_name_repeats_are_not_sources():
    hero = "BitMEX закрылся после 11 лет\n\nBitMEX придумал перпетуал\n\nBitMEX проиграл рынку"
    assert ct.source_mentions(hero) == []


def test_channel_posts_never_hit_the_source_rule():
    posts = json.load(open("data/channel_posts.json", encoding="utf-8"))
    assert [p.get("id") for p in posts if len(ct.source_mentions(p.get("text") or "")) >= 2] == []


def test_publisher_site_logo_is_a_foreign_brand():
    assert sw._foreign_brand("Логотип KUCOIN на чёрном фоне со слоганом «Trust First. Trade Next.»",
                             "Glassnode показал цифру")
    assert not sw._foreign_brand("вывеска BitMEX на фасаде", "BitMEX закрылся")
    assert not sw._foreign_brand("печать регулятора на фасаде", "любой текст")


def test_reselect_catches_own_rejected_topic():
    rej = ["«Glassnode: альты 4x BTC объём» — тема уже закрыта", "«Vitalik: Hegota последний форк Ethereum»"]
    assert rp._returned_rejected("Спот-объём альтов 4x — Glassnode предупреждает", rej)
    assert not rp._returned_rejected("Ethereum стейкинг: ether.fi уходит от EigenLayer", rej)
