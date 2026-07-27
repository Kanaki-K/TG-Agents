"""Юнит-тесты медиа первоисточника — БЕЗ сети (мокаем feeds.fetch_bytes).

Проверяем то, что легко ломается молча: парсинг og:image (порядок атрибутов, относительный URL,
разные теги) и гарды скачивания (только image/*, размерный коридор). Запуск: python -m pytest.
"""
from __future__ import annotations

import pytest

from connectors.source_media import fetch
from connectors.web_sources import feeds

PAGE = "https://news.example.com/article/xyz"


def _html(bytes_body: str):
    return (bytes_body.encode("utf-8"), "text/html; charset=utf-8")


# --- og_image_url: парсинг ------------------------------------------------------------------------

def test_og_image_property_then_content(monkeypatch):
    monkeypatch.setattr(feeds, "fetch_bytes",
                        lambda url, **k: _html('<meta property="og:image" content="https://cdn.x/p.jpg">'))
    assert fetch.og_image_url(PAGE) == "https://cdn.x/p.jpg"


def test_og_image_content_then_property(monkeypatch):
    monkeypatch.setattr(feeds, "fetch_bytes",
                        lambda url, **k: _html('<meta content="https://cdn.x/q.png" property="og:image"/>'))
    assert fetch.og_image_url(PAGE) == "https://cdn.x/q.png"


def test_twitter_image_fallback(monkeypatch):
    monkeypatch.setattr(feeds, "fetch_bytes",
                        lambda url, **k: _html('<meta name="twitter:image" content="https://cdn.x/t.webp">'))
    assert fetch.og_image_url(PAGE) == "https://cdn.x/t.webp"


def test_relative_url_made_absolute(monkeypatch):
    monkeypatch.setattr(feeds, "fetch_bytes",
                        lambda url, **k: _html('<meta property="og:image" content="/img/hero.jpg">'))
    assert fetch.og_image_url(PAGE) == "https://news.example.com/img/hero.jpg"


def test_no_meta_returns_none(monkeypatch):
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: _html("<html><body>no image</body></html>"))
    assert fetch.og_image_url(PAGE) is None


def test_blocked_or_error_returns_none(monkeypatch):
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: None)  # SSRF-блок/таймаут
    assert fetch.og_image_url(PAGE) is None


# --- download: гарды ------------------------------------------------------------------------------

def test_download_rejects_non_image(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: (b"x" * 5000, "text/html"))
    assert fetch.download("https://cdn.x/notimage") is None


def test_download_rejects_too_small(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: (b"tiny", "image/png"))
    assert fetch.download("https://cdn.x/p.png") is None


def test_download_ok_png(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    body = b"\x89PNG" + b"0" * 5000
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: (body, "image/png"))
    out = fetch.download("https://cdn.x/p.png", name="scope")
    assert out is not None and out.suffix == ".png" and out.read_bytes() == body


def test_download_ext_from_content_type(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: (b"J" * 5000, "image/jpeg"))
    out = fetch.download("https://cdn.x/whatever")  # расширение из content-type, не из URL
    assert out is not None and out.suffix == ".jpg"


# --- fetch_source_image: сквозной путь ------------------------------------------------------------

def test_fetch_source_image_none_when_no_og(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: _html("<html>no og</html>"))
    assert fetch.fetch_source_image(PAGE) is None


def test_fetch_source_image_happy_path(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)

    def fake(url, **k):
        if url == PAGE:
            return _html('<meta property="og:image" content="https://cdn.x/hero.png">')
        return (b"\x89PNG" + b"0" * 5000, "image/png")  # сама картинка

    monkeypatch.setattr(feeds, "fetch_bytes", fake)
    out = fetch.fetch_source_image(PAGE, name="scope")
    assert out is not None and out.suffix == ".png"


# --- порог РАЗРЕШЕНИЯ обложки (баг 24.07: 8.5КБ мелкая og:image ушла в канал «корявой») -------------

def _png_bytes(w: int, h: int) -> bytes:
    """Реальный PNG-шум w×h (шум не жмётся → байтовый гейт _MIN_BYTES проходит, проверяем именно пиксели)."""
    import io
    import os

    from PIL import Image
    img = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_download_rejects_low_resolution(monkeypatch, tmp_path):
    # длинная сторона < _MIN_SIDE (800) → мелкий thumbnail → отклоняем (сработает фолбэк «уйдём текстом»)
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: (_png_bytes(200, 150), "image/png"))
    assert fetch.download("https://cdn.x/tiny.png") is None


def test_download_accepts_ok_resolution(monkeypatch, tmp_path):
    # нормальное разрешение (1000×800) → проходит, нормализуется в JPEG-обложку
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: (_png_bytes(1000, 800), "image/png"))
    out = fetch.download("https://cdn.x/big.png", name="scope")
    assert out is not None and out.suffix == ".jpg"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
