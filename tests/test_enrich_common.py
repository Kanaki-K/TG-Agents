"""Тесты общего каркаса обогащения (connectors/enrich_common): парсинг ответа модели."""
from connectors import enrich_common as ec


def test_parse_json_plain():
    assert ec._parse_json('[{"id": 1, "theme": "рынок"}]') == [{"id": 1, "theme": "рынок"}]


def test_parse_json_markdown_json_fence():
    assert ec._parse_json('```json\n[{"id": 2}]\n```') == [{"id": 2}]


def test_parse_json_bare_fence():
    assert ec._parse_json('```\n[{"id": 3}]\n```') == [{"id": 3}]


def test_taxonomy_single_sourced():
    # каркас берёт категории/углы из общего источника — не копия-комментарий
    from core import post_angle, topic_category
    for slug in topic_category.all_slugs():
        assert f'"{slug}"' in ec._CATS
    for slug in post_angle.all_slugs():
        assert f'"{slug}"' in ec._ANGLES
