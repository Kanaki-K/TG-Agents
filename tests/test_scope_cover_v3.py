"""ОБЛОЖКА SCOPE (14.09.2026): панорама не формат канала; судья отказал всем → второй круг поиска.

ЗАЧЕМ. 14.09 в пуле лежали лого Bitcoin Cash, вагон электрички (~3.4:1) и печать ФРС. Панорама прошла
как «горизонталь» (верхней границы не было), судья отказал всем, и фолбэк «обложка есть всегда» взял
первый кадр — вагон, достроенный серыми полями до 16:9. Без сети и LLM.
Запуск: python -m pytest tests/test_scope_cover_v3.py"""
from __future__ import annotations

from connectors.source_media import fetch
from core import scope_writer as sw


def test_panorama_is_not_channel_landscape(tmp_path):
    cases = {"train.jpg": 3.4, "orange_juice.jpg": 2.333, "normal.jpg": 1.78, "square.jpg": 1.0}
    for name, ratio in cases.items():
        fetch._ORIG_RATIO[str(tmp_path / name)] = ratio
    assert not fetch.is_landscape(tmp_path / "train.jpg")
    assert fetch.is_landscape(tmp_path / "orange_juice.jpg")   # самая широкая ПРИНЯТАЯ обложка (#454)
    assert fetch.is_landscape(tmp_path / "normal.jpg")
    assert not fetch.is_landscape(tmp_path / "square.jpg")


def _patch_media(monkeypatch, tmp_path, urls, ratios, seen_prints=()):
    asked = {}

    def subject_image_urls(subject, limit=4, page_urls=None):
        asked["subject"], asked["limit"] = subject, limit
        return urls

    def download(url, name="", min_side=0):
        p = tmp_path / f"{name}.jpg"
        p.write_bytes(b"x")
        fetch._ORIG_RATIO[str(p)] = ratios[url]
        return p

    m = sw.source_media
    monkeypatch.setattr(m, "subject_image_urls", subject_image_urls)
    monkeypatch.setattr(m, "download", download)
    monkeypatch.setattr(m, "frame_fingerprint", lambda p: ratios_by_path(p))
    monkeypatch.setattr(m, "looks_same", lambda a, b: a == b)
    monkeypatch.setattr(m, "kind_of", lambda url: "поиск")

    def ratios_by_path(p):
        return fetch._ORIG_RATIO.get(str(p))

    return asked


def test_second_round_goes_wider_and_keeps_only_new_landscapes(monkeypatch, tmp_path):
    urls = ["u_pano", "u_good", "u_dup"]
    ratios = {"u_pano": 3.4, "u_good": 1.9, "u_dup": 1.5}
    asked = _patch_media(monkeypatch, tmp_path, urls, ratios)
    prints = [1.5]                                   # «u_dup» первый круг уже видел
    routes: dict = {}
    got = sw._second_cover_round("Clarity Act, Federal Reserve", "тело поста", [], prints, routes)
    assert [p.name for p in got] == ["scope_subj2_1.jpg"]
    assert asked["limit"] == sw.SECOND_ROUND_FRAMES
    assert asked["subject"].startswith("Federal Reserve")   # главная сущность уходит в конец


def test_second_round_without_subject_is_empty(monkeypatch, tmp_path):
    _patch_media(monkeypatch, tmp_path, [], {})
    assert sw._second_cover_round("", "тело поста по-русски без имён", [], [], {}) == []


def test_blind_fallback_notes_match_vision_pick():
    """Второй круг включается по пометке _vision_pick — если её текст поедет, круг молча отключится."""
    import inspect
    src = inspect.getsource(sw._vision_pick)
    for marker in sw._BLIND_FALLBACK:
        assert marker in src
