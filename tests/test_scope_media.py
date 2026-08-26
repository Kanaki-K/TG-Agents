"""Юнит-тесты парсинга медиа-меты scope (чистые функции, без сети/LLM). Контракт scope → обложка:
если формат маркеров поедет, эти тесты поймают молчаливую поломку. Запуск: python -m pytest."""
from __future__ import annotations

from core import scope_writer as sw


def test_parse_multiple_urls():
    post = ("тело поста\n[[SPLIT]]\nзаметка проверки\n"
            "[[MEDIA_SRC]] https://a.com/x, https://b.com/y\n[[MEDIA_SUBJECT]] Saylor, Strategy")
    assert sw._parse_media_srcs(post) == ["https://a.com/x", "https://b.com/y"]


def test_parse_dedup_and_cap():
    urls = " ".join(f"https://s{i}.com/a" for i in range(6))
    got = sw._parse_media_srcs(f"[[MEDIA_SRC]] {urls} https://s0.com/a")  # 6 уник + дубль
    assert len(got) == 4 and len(set(got)) == 4  # дедуп + кап 4


def test_parse_no_marker():
    assert sw._parse_media_srcs("нет никакой меты тут") == []


def test_parse_srcs_ignores_non_http():
    assert sw._parse_media_srcs("[[MEDIA_SRC]] ftp://x, потом https://ok.com/a") == ["https://ok.com/a"]


def test_parse_subject():
    assert sw._parse_media_subject("[[MEDIA_SUBJECT]] Michael Saylor, Strategy, MSTR") == \
        "Michael Saylor, Strategy, MSTR"


def test_parse_subject_absent():
    assert sw._parse_media_subject("поста без сущностей") == ""


# ── ПУЛ КАНДИДАТОВ (26.08): со страницы берём шапку И кадры из тела, но держим кап ──────────────
# До 26.08 с каждой статьи приходила ровно одна картинка — og:image, то есть декоративная шапка.
# Пул из одних шапок структурно не мог дать ничего, кроме ИИ-стока. Кап нужен, чтобы расширение
# не превратило один дешёвый vision-вызов в дорогой (каждый кадр ~1.1к токенов).

def _cover_to_tmp(monkeypatch, tmp_path):
    from core import creator_tools
    monkeypatch.setattr(creator_tools, "SCOPE_COVER", tmp_path / "cover.txt")


def _spy_pick(monkeypatch, seen: dict):
    """Подменяет vision-выбор и запоминает, СКОЛЬКО кандидатов до него доехало."""
    def pick(imgs, *a):
        seen["n"] = len(imgs)
        return imgs[0] if imgs else None
    monkeypatch.setattr(sw, "_vision_pick", pick)


def test_attach_media_collects_frames_from_every_page(monkeypatch, tmp_path):
    _cover_to_tmp(monkeypatch, tmp_path)
    monkeypatch.setattr(sw.source_media, "fetch_source_images",
                        lambda url, name="scope": [tmp_path / f"{name}_0.jpg", tmp_path / f"{name}_1.jpg"])
    seen = {}
    _spy_pick(monkeypatch, seen)
    out = sw._attach_media(["https://a.com/x", "https://b.com/y"], "тело", "Dallas Fed", "k")
    assert seen["n"] == 4, "два кадра с каждой из двух страниц"
    assert out.endswith("scope_0_0.jpg")


def test_attach_media_stops_at_pool_cap(monkeypatch, tmp_path):
    _cover_to_tmp(monkeypatch, tmp_path)
    pages = {"hit": 0}

    def many(url, name="scope"):
        pages["hit"] += 1
        return [tmp_path / f"{name}_{j}.jpg" for j in range(4)]

    monkeypatch.setattr(sw.source_media, "fetch_source_images", many)
    seen = {}
    _spy_pick(monkeypatch, seen)
    sw._attach_media([f"https://s{i}.com/a" for i in range(4)], "тело", "субъект", "k")
    assert seen["n"] == sw.MEDIA_POOL_CAP
    assert pages["hit"] == 2, "упёрлись в кап — остальные страницы не тянем"


def test_attach_media_survives_dead_page(monkeypatch, tmp_path):
    """Одна страница упала — обложку всё равно ищем по остальным (пост не блокируем)."""
    _cover_to_tmp(monkeypatch, tmp_path)

    def flaky(url, name="scope"):
        if "bad" in url:
            raise RuntimeError("сеть")
        return [tmp_path / f"{name}_0.jpg"]

    monkeypatch.setattr(sw.source_media, "fetch_source_images", flaky)
    monkeypatch.setattr(sw, "_vision_pick", lambda imgs, *a: imgs[0])
    out = sw._attach_media(["https://bad.com/x", "https://ok.com/y"], "тело", "субъект", "k")
    assert out.endswith("scope_1_0.jpg")


def test_attach_media_empty_pool_goes_text(monkeypatch, tmp_path):
    _cover_to_tmp(monkeypatch, tmp_path)
    monkeypatch.setattr(sw.source_media, "fetch_source_images", lambda url, name="scope": [])
    assert sw._attach_media(["https://a.com/x"], "тело", "субъект", "k") == ""
