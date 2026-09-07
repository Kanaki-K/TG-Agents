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
    # длинная сторона < _MIN_SIDE → мелкий thumbnail/фавикон, кандидатом не становится
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: (_png_bytes(200, 150), "image/png"))
    assert fetch.download("https://cdn.x/tiny.png") is None


def test_download_accepts_ok_resolution(monkeypatch, tmp_path):
    # нормальное разрешение (1000×800) → проходит, нормализуется в JPEG-обложку
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: (_png_bytes(1000, 800), "image/png"))
    out = fetch.download("https://cdn.x/big.png", name="scope")
    assert out is not None and out.suffix == ".jpg"



# --- КАДРЫ ИЗ ТЕЛА СТАТЬИ (26.08): пул из одних шапок структурно даёт только ИИ-сток ----------------

ARTICLE_HTML = """
<html><head>
  <meta property="og:image" content="https://cdn.x/hero.jpg">
</head><body>
  <header><img src="https://cdn.x/logo.svg" alt="лого"></header>
  <nav><img src="https://cdn.x/icon-menu.png"></nav>
  <article>
    <img src="/charts/deposits-2026.png" alt="график">
    <img data-src="https://cdn.x/scheme.jpg" alt="схема">
    <img src="https://cdn.x/avatar-author.jpg" alt="автор">
    <img src="data:image/png;base64,AAAA">
    <img src="/charts/deposits-2026.png" alt="тот же график">
  </article>
  <footer><img src="https://cdn.x/subscribe-banner.jpg"></footer>
</body></html>
"""


def test_article_images_takes_body_frames(monkeypatch):
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: _html(ARTICLE_HTML))
    assert fetch.article_images(PAGE) == ["https://news.example.com/charts/deposits-2026.png",
                                          "https://cdn.x/scheme.jpg"]


def test_article_images_skip_chrome_and_junk(monkeypatch):
    """Логотип шапки, иконка меню, аватар автора, баннер подписки, data: и дубль — не кандидаты."""
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: _html(ARTICLE_HTML))
    got = fetch.article_images(PAGE)
    assert not any(bad in u for u in got for bad in ("logo", "icon", "avatar", "subscribe", "data:"))
    assert len(got) == len(set(got))


def test_article_images_skip_og_duplicate(monkeypatch):
    """Шапка часто продублирована первым <img> в теле — второй раз её не тянем."""
    html = '<meta property="og:image" content="https://cdn.x/hero.jpg">' \
           '<article><img src="https://cdn.x/hero.jpg"><img src="https://cdn.x/chart.png"></article>'
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: _html(html))
    assert fetch.article_images(PAGE) == ["https://cdn.x/chart.png"]


def test_article_images_capped(monkeypatch):
    imgs = "".join(f'<img src="/p{i}.jpg">' for i in range(10))
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: _html(f"<article>{imgs}</article>"))
    assert len(fetch.article_images(PAGE)) == fetch.ARTICLE_IMG_CAP


def test_article_images_without_article_tag(monkeypatch):
    """Нет <article>/<main> — смотрим всю страницу, иначе на простой вёрстке пул остался бы пустым."""
    monkeypatch.setattr(feeds, "fetch_bytes",
                        lambda url, **k: _html('<body><img src="https://cdn.x/chart.png"></body>'))
    assert fetch.article_images(PAGE) == ["https://cdn.x/chart.png"]


def test_article_images_empty_page(monkeypatch):
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: None)
    assert fetch.article_images(PAGE) == []


def test_fetch_source_images_pool_is_header_plus_body(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    seen = {"pages": 0}

    def fake(url, **k):
        if url == PAGE:
            seen["pages"] += 1
            return _html(ARTICLE_HTML)
        return (_png_bytes(1000, 800), "image/png")

    monkeypatch.setattr(feeds, "fetch_bytes", fake)
    out = fetch.fetch_source_images(PAGE, name="scope_0")
    assert len(out) == 3, "шапка + два кадра из тела"
    assert [p.stem for p in out] == ["scope_0_0", "scope_0_1", "scope_0_2"], "имена не должны затирать друг друга"
    assert seen["pages"] == 1, "страницу тянем ОДИН раз на все кадры"


def test_fetch_source_images_drops_unusable(monkeypatch, tmp_path):
    """Мелкие/битые кадры выпадают, но пул из-за них не обнуляется."""
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)

    def fake(url, **k):
        if url == PAGE:
            return _html(ARTICLE_HTML)
        if "hero" in url:
            return (_png_bytes(1200, 900), "image/png")
        return (_png_bytes(100, 80), "image/png")      # тело статьи — мелочь

    monkeypatch.setattr(feeds, "fetch_bytes", fake)
    out = fetch.fetch_source_images(PAGE, name="scope_0")
    assert len(out) == 1


def test_fetch_source_images_empty_when_page_dead(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: None)
    assert fetch.fetch_source_images(PAGE) == []



# --- ПОЛ РАЗРЕШЕНИЯ ВЗЯТ ИЗ ПРИНЯТЫХ ОБЛОЖЕК (07.09) -----------------------------------------------
# Порог 800 стоял по одному багу 24.07 и бил по своим: замер 23 опубликованных обложек показал, что
# канал принял #440 в 499x281, #454 в 700x300 и #489 в 700x450. Роль кадра (шапка/тело) порог больше
# не меняет — он одинаково выведен из того, что владелец реально публиковал.

def test_smallest_published_cover_would_pass(monkeypatch, tmp_path):
    """499x281 — самая мелкая ПРИНЯТАЯ обложка канала (#440, Chainlink/Pangea). Порог 800 её убивал."""
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: (_png_bytes(499, 281), "image/png"))
    assert fetch.download("https://cdn.x/pangea.png") is not None


def test_header_and_body_share_one_floor(monkeypatch, tmp_path):
    """Кадр 600x400 годится и как шапка, и как кадр из тела — разного порога по роли больше нет."""
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: (_png_bytes(600, 400), "image/png"))
    assert fetch.download("https://cdn.x/chart.png") is not None
    assert fetch.download("https://cdn.x/chart.png", min_side=fetch._MIN_SIDE_BODY) is not None


def test_two_frames_from_one_page(monkeypatch, tmp_path):
    """Шапка + кадр из тела дают ДВА кандидата: пул должен быть, из чего выбирать."""
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    html = ('<meta property="og:image" content="https://cdn.x/hero.jpg">'
            '<article><img src="https://cdn.x/chart.png"></article>')

    def fake(url, **k):
        if url == PAGE:
            return _html(html)
        return (_png_bytes(1200, 800), "image/png") if "hero" in url else (_png_bytes(640, 420), "image/png")

    monkeypatch.setattr(feeds, "fetch_bytes", fake)
    assert len(fetch.fetch_source_images(PAGE, name="scope_0")) == 2


def test_body_frame_still_has_a_floor(monkeypatch, tmp_path):
    """Пол снижен, а не снят: 345x230 мельче самой мелкой принятой обложки — в ленте это мыло."""
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    html = '<article><img src="https://cdn.x/tiny.png"></article>'

    def fake(url, **k):
        return _html(html) if url == PAGE else (_png_bytes(345, 230), "image/png")

    monkeypatch.setattr(feeds, "fetch_bytes", fake)
    assert fetch.fetch_source_images(PAGE) == []


def test_header_of_accepted_size_passes(monkeypatch, tmp_path):
    """700x500 — размерный класс принятой обложки #489 (печать ФРС, 700x450). Порог 800 её резал.
    Правило 24.07 не отменено, у него сменилась граница: мелочью считается то, что мельче
    опубликованного каналом, а не то, что мельче круглого числа."""
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    html = '<meta property="og:image" content="https://cdn.x/hero.jpg">'

    def fake(url, **k):
        return _html(html) if url == PAGE else (_png_bytes(700, 500), "image/png")

    monkeypatch.setattr(feeds, "fetch_bytes", fake)
    assert len(fetch.fetch_source_images(PAGE)) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


# ── ЛОГО ТЕМЫ — ЗАКОННАЯ ОБЛОЖКА (владелец 28.08) ───────────────────────────────────────────────
# На канале лого компании/сети — один из самых частых кадров под 🔭. Фильтр выбрасывал ЛЮБОЙ адрес
# со словом logo, то есть ровно этот кадр, ещё до vision: 28.08 владелец ставил лого Solana руками,
# потому что пул его не предлагал. Послабление даём только внутри <article>/<main> — шапку сайта с её
# логотипом там уже отрезало структурно.

def test_subject_logo_inside_article_is_taken(monkeypatch):
    html = '<article><img src="https://cdn.x/solana-logo.png" alt="Solana"></article>'
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: _html(html))
    assert fetch.article_images(PAGE) == ["https://cdn.x/solana-logo.png"]


def test_site_logo_outside_article_still_dropped(monkeypatch):
    """Лого ИЗДАНИЯ отсекает сужение до <article>, а не список слов — поэтому послабление безопасно."""
    html = ('<header><img src="https://cdn.x/site-logo.png"></header>'
            '<article><img src="https://cdn.x/chart.png"></article>')
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: _html(html))
    assert fetch.article_images(PAGE) == ["https://cdn.x/chart.png"]


def test_logo_still_dropped_when_no_article_tag(monkeypatch):
    """Статью не нашли → смотрим всю страницу → лого снова мусор: отличить издание от темы нечем."""
    html = '<body><img src="https://cdn.x/site-logo.png"><img src="https://cdn.x/chart.png"></body>'
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: _html(html))
    assert fetch.article_images(PAGE) == ["https://cdn.x/chart.png"]


def test_true_junk_still_dropped_inside_article(monkeypatch):
    """Послабление ровно на logo/icon: аватар, трекер и баннер подписки — мусор в любом случае."""
    html = ('<article><img src="https://cdn.x/avatar-author.jpg">'
            '<img src="https://cdn.x/tracking-pixel.png">'
            '<img src="https://cdn.x/subscribe-banner.jpg">'
            '<img src="https://cdn.x/solana-logo.png"></article>')
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: _html(html))
    assert fetch.article_images(PAGE) == ["https://cdn.x/solana-logo.png"]


# --- ФОРМАТ: ГОРИЗОНТАЛЬ ОТБИРАЕМ, А НЕ ДОСТРАИВАЕМ (07.09) ---------------------------------------
# Замер: 21 из 23 обложек канала — снятая горизонталь. Код умел достраивать вертикаль полями до 16:9,
# и 07.09 так и сделал: башня DBS уехала в отложку узкой полосой посреди синих полей.

def test_original_ratio_is_remembered_after_padding(monkeypatch, tmp_path):
    """После достройки все файлы 16:9 — отличить снятую горизонталь от вертикали можно только так."""
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: (_png_bytes(600, 900), "image/png"))
    p = fetch.download("https://cdn.x/tower.png")
    assert p is not None
    assert 0.6 < fetch.orig_ratio(p) < 0.7, "исходная пропорция вертикали должна сохраниться"
    assert not fetch.is_landscape(p)


def test_landscape_photo_is_marked_landscape(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: (_png_bytes(1200, 800), "image/png"))
    p = fetch.download("https://cdn.x/hq.png")
    assert fetch.is_landscape(p), "3:2 — нормальная снятая горизонталь канала (#451, #472, #486)"


# --- ТИР-1 ЗАКРЫТ ДЛЯ СТРАНИЦ, НО ОТКРЫТ ДЛЯ RSS (07.09) ------------------------------------------
# coindesk отдаёт 429, theblock — 403: защита от ботов, заголовками не лечится. Замер 31.08 списал их
# в потери, и пул две недели кормили издания послабее — а лучшая художка среди 23 принятых обложек
# была как раз оттуда. Лента у обоих открыта и несёт тот же кадр, что стоит в шапке статьи.

_FEED = """<rss><channel>
<item><link>https://www.theblock.co/news/markets/2026-09-07-bitcoin-holds/</link>
<media:content url="https://www.tbstat.com/wp/uploads/2026/09/fed-1200x675.jpg"/></item>
<item><link>https://www.theblock.co/news/other/2026-09-06-something-else</link>
<media:content url="https://www.tbstat.com/wp/uploads/2026/09/other-1200x675.jpg"/></item>
</channel></rss>"""

ART = "https://www.theblock.co/news/markets/2026-09-07-bitcoin-holds"


def test_feed_image_found_for_blocked_page(monkeypatch):
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: (_FEED.encode(), "application/rss+xml"))
    got = fetch.feed_image_url(ART)
    assert got and got.endswith("fed-1200x675.jpg"), "ссылка сравнивается без слэшей и query"


def test_feed_never_substitutes_a_neighbouring_article(monkeypatch):
    """Чужая картинка из соседней новости хуже отсутствия обложки — подставлять нельзя."""
    monkeypatch.setattr(feeds, "fetch_bytes", lambda url, **k: (_FEED.encode(), "application/rss+xml"))
    assert fetch.feed_image_url("https://www.theblock.co/news/markets/2026-09-07-not-in-feed") is None


def test_unknown_host_has_no_feed(monkeypatch):
    assert fetch.feed_image_url("https://example.com/some/article") is None


def test_blocked_page_falls_back_to_feed(monkeypatch, tmp_path):
    """Сквозной путь: страница 403 → кадр всё равно приезжает, и он считается ШАПКОЙ."""
    monkeypatch.setattr(fetch, "OUT_DIR", tmp_path)

    def fake(url, **k):
        if url == ART:
            return None                                   # страница закрыта
        if url.endswith(".jpg"):
            return (_png_bytes(1200, 675), "image/png")   # кадр из ленты
        return (_FEED.encode(), "application/rss+xml")

    monkeypatch.setattr(feeds, "fetch_bytes", fake)
    got = fetch.fetch_source_images(ART, name="tier1")
    assert len(got) == 1 and fetch.is_header(got[0])
