"""ПОИСК кадра по объекту повода + формат обложки под канал (31.08). Без сети: API-ответы подставляем.

Почему эти тесты существуют. 31.08 скоуп выдал пост без обложки, хотя бренд-полотно Robinhood лежало
в открытом доступе. Корней было четыре, и каждый ловится ниже:
  1) код НИКОГДА не искал кадр — только снимал картинки с чужих статей;
  2) одна и та же картинка в двух размерах занимала два места в пуле «из трёх кандидатов»;
  3) кадр не приводился к формату канала (16:9), лого уходило бы квадратом;
  4) отказ источника (403/429) проглатывался молча.
"""
from __future__ import annotations

import pytest

from connectors.source_media import fetch, subject_media as sm
from connectors.web_sources import feeds
from core import scope_writer as sw

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402


# ── ОПОЗНАНИЕ ОБЪЕКТА: та ли это сущность ──────────────────────────────────────────────────────
def test_split_subject_filters_noise():
    got = sm.split_subject("Michael Saylor, Strategy, MSTR, x, " + "я" * 80)
    assert got == ["Michael Saylor", "Strategy", "MSTR"], "мусор (2 буквы / целая фраза) отсеян"


def _stub_search(monkeypatch, hits: list[dict]):
    monkeypatch.setattr(sm, "_api_json", lambda url: {"search": hits})


def test_entity_id_skips_offtopic_description(monkeypatch):
    """«SEC» в Wikidata — это секунда и секанс. Обложка «по объекту» вышла бы не по теме."""
    _stub_search(monkeypatch, [
        {"id": "Q11574", "description": "SI unit of time, defined as 9 192 631 770 periods"},
        {"id": "Q1467935", "description": "ratio of the hypotenuse of a triangle"},
        {"id": "Q953944", "description": "U.S. federal agency that enforces securities laws"},
    ])
    assert sm.entity_id("SEC")[0] == "Q953944"


def test_entity_id_acronym_needs_ontopic_description(monkeypatch):
    """У аббревиатуры нейтрального описания мало: «FOMC» так становился фортом Мак-Генри."""
    _stub_search(monkeypatch, [{"id": "Q73122275", "description": "former military site"}])
    assert sm.entity_id("FOMC") == ("", ""), "нейтральное описание аббревиатуре не засчитываем"


def test_entity_id_full_name_accepts_neutral_description(monkeypatch):
    """А полному имени — засчитываем: «Robinhood» с чем попало не совпадёт."""
    _stub_search(monkeypatch, [{"id": "Q18155123", "description": "brokerage"}])
    assert sm.entity_id("Robinhood")[0] == "Q18155123"


def test_commons_search_wants_word_boundary(monkeypatch):
    """Подстрочный поиск находил «SEC» внутри «Secant.svg» — границей слова это отсекается."""
    monkeypatch.setattr(sm, "_api_json", lambda url: {"query": {"pages": {
        "1": {"title": "File:Secant.svg", "imageinfo": [{"url": "https://x/Secant.png", "width": 900,
                                                         "height": 900}]}}}})
    assert sm._commons_search("SEC logo", "SEC") is None


# ── ПОРЯДОК: живой кадр раньше голого лого ─────────────────────────────────────────────────────
def test_rich_frames_come_before_bare_logo(monkeypatch):
    """Владелец 31.08: «просто логотип на белом фоне — можно же немного интереснее подобрать».
    Полотно бренда и фото объекта обязаны стоять в пуле ПЕРЕД страховочным лого."""
    monkeypatch.setattr(sm, "entity_id", lambda e: ("Q1", "American financial services company"))
    monkeypatch.setattr(sm, "_claims", lambda qid: {
        "P856": [{"mainsnak": {"datavalue": {"value": "https://site.example"}}}],
        "P18": [{"mainsnak": {"datavalue": {"value": "HQ.jpg"}}}],
        "P154": [{"mainsnak": {"datavalue": {"value": "Logo.svg"}}}],
    })
    monkeypatch.setattr(sm, "_og_image", lambda site: "https://site.example/brand.jpg")
    monkeypatch.setattr(sm, "_commons_file_url", lambda f: f"https://commons/{f}.png")
    monkeypatch.setattr(sm, "wiki_page_image", lambda qid: None)
    monkeypatch.setattr(sm, "commons_photo", lambda e: None)
    got = sm.subject_image_urls("Robinhood", limit=4)
    assert got[0] == "https://site.example/brand.jpg", "первым — полотно бренда"
    assert got.index("https://commons/HQ.jpg.png") < got.index("https://commons/Logo.svg.png"), \
        "фото объекта раньше голого лого"


# ── ФОРМАТ КАНАЛА: 16:9, без чёрного под прозрачностью ─────────────────────────────────────────
def _save(tmp_path, im, name="x.png"):
    p = tmp_path / name
    im.save(p)
    return p


def _structured(w=1600, h=900, shift=0):
    """Кадр СО СТРУКТУРОЙ — как настоящая обложка (фигуры, перепады), а не ровная заливка.
    Чистый градиент отпечатку сравнивать нечего, и он честно отдаёт None: это его правило,
    а не поломка (см. frame_fingerprint)."""
    im = Image.new("RGB", (w, h), (240, 240, 240))
    d = ImageDraw.Draw(im)
    d.rectangle([w * 0.1, h * 0.2, w * 0.45, h * 0.7], fill=(20 + shift, 120, 30))
    d.ellipse([w * 0.55, h * 0.15, w * 0.9, h * 0.6], fill=(200, 40, 60 + shift))
    d.rectangle([w * 0.2, h * 0.75, w * 0.8, h * 0.85], fill=(15, 15, 15))
    return im


def test_square_frame_is_padded_to_channel_ratio(tmp_path):
    """Замер 23 обложек: 21 горизонталь, медиана 1.78. Квадратное лого уходило квадратом."""
    out = fetch._normalize(_save(tmp_path, Image.new("RGB", (900, 900), (12, 200, 30))), min_side=400)
    with Image.open(out) as im:
        w, h = im.size
    assert fetch._RATIO_MIN <= w / h <= fetch._RATIO_MAX


def test_wide_strip_is_padded_too(tmp_path):
    """Вордмарк-полоска 831x163 — тоже вне формата канала (2.0 сверху)."""
    out = fetch._normalize(_save(tmp_path, Image.new("RGB", (1200, 200), (9, 9, 9))), min_side=400)
    with Image.open(out) as im:
        w, h = im.size
    assert w / h <= fetch._RATIO_MAX


def test_frame_already_in_range_is_not_reframed(tmp_path):
    """Фотографию с нормальной пропорцией не трогаем: своя композиция дороже ровной цифры."""
    out = fetch._normalize(_save(tmp_path, Image.new("RGB", (1600, 900), (40, 40, 40))), min_side=400)
    with Image.open(out) as im:
        assert im.size == (1600, 900)


def test_transparent_logo_does_not_become_black_on_black(tmp_path):
    """convert('RGB') красил альфу ЧЁРНЫМ, и тёмное лого исчезало. Фон берём по контрасту."""
    im = Image.new("RGBA", (900, 900), (0, 0, 0, 0))
    im.paste((10, 10, 10, 255), (300, 400, 600, 500))          # тёмные «чернила» на прозрачном
    out = fetch._normalize(_save(tmp_path, im), min_side=400)
    with Image.open(out) as got:
        corner = got.convert("RGB").getpixel((5, 5))
    assert sum(corner) > 600, "под тёмным лого должен лечь светлый фон, а не чёрный"


# ── ДУБЛИ: одна картинка в двух размерах — это ОДИН кандидат ───────────────────────────────────
def test_fingerprint_matches_same_image_in_two_sizes(tmp_path):
    """31.08 «три кандидата» были двумя: шапка crypto.news и она же из тела в другой ширине."""
    base = _structured()
    a = fetch.frame_fingerprint(_save(tmp_path, base, "a.png"))
    b = fetch.frame_fingerprint(_save(tmp_path, base.resize((1200, 675)), "b.png"))
    assert a is not None
    assert fetch.looks_same(a, b), "тот же кадр в другом размере — один кандидат"


def test_flat_fill_gets_no_fingerprint(tmp_path):
    """Ровной заливке отпечаток НЕ выдаём: у неё нечего сравнивать, и два разных фирменных полотна
    склеились бы в один кандидат. None = дедуп для этого кадра выключен, лишний кандидат безопаснее."""
    assert fetch.frame_fingerprint(_save(tmp_path, Image.new("RGB", (900, 500), (30, 30, 30)))) is None


def test_fingerprint_separates_different_images(tmp_path):
    a = fetch.frame_fingerprint(_save(tmp_path, _structured(), "a.png"))
    b = fetch.frame_fingerprint(_save(tmp_path, _structured().transpose(Image.FLIP_LEFT_RIGHT), "b.png"))
    assert a is not None and b is not None
    assert not fetch.looks_same(a, b), "зеркальный кадр — другая картинка"


def test_pool_drops_duplicate_frames(monkeypatch, tmp_path):
    """Дубль не должен занимать место в пуле — иначе выбор из «трёх» на деле из двух."""
    from core import creator_tools, scope_cover_log
    monkeypatch.setattr(creator_tools, "SCOPE_COVER", tmp_path / "cover.txt")
    monkeypatch.setattr(scope_cover_log, "LOG", tmp_path / "log.jsonl")
    base = _structured()
    same_a, same_b = _save(tmp_path, base, "s1.jpg"), _save(tmp_path, base.resize((800, 450)), "s2.jpg")
    other = _save(tmp_path, _structured().transpose(Image.FLIP_LEFT_RIGHT), "o.jpg")
    monkeypatch.setattr(sw.source_media, "subject_image_urls", lambda subject, limit=3: [])
    monkeypatch.setattr(sw.source_media, "fetch_source_images",
                        lambda url, name="scope": [same_a, same_b, other])
    seen: dict = {}
    monkeypatch.setattr(sw, "_vision_pick", lambda imgs, *a: (seen.setdefault("n", len(imgs)),
                                                              (imgs[0], "ярлык"))[1])
    sw._attach_media(["https://a.com/x"], "тело", "субъект", "k")
    assert seen["n"] == 2, "две одинаковых картинки схлопнулись в одного кандидата"


def test_pool_takes_frames_found_by_subject(monkeypatch, tmp_path):
    """Главная правка 31.08: кадр, НАЙДЕННЫЙ по объекту повода, обязан попадать в пул."""
    from core import creator_tools, scope_cover_log
    monkeypatch.setattr(creator_tools, "SCOPE_COVER", tmp_path / "cover.txt")
    monkeypatch.setattr(scope_cover_log, "LOG", tmp_path / "log.jsonl")
    found = _save(tmp_path, Image.new("RGB", (1600, 900), (0, 120, 255)), "brand.jpg")
    monkeypatch.setattr(sw.source_media, "subject_image_urls",
                        lambda subject, limit=3, page_urls=None: ["https://site/brand.jpg"])
    monkeypatch.setattr(sw.source_media, "download", lambda url, name="scope", min_side=0: found)
    monkeypatch.setattr(sw.source_media, "fetch_source_images", lambda url, name="scope": [])
    monkeypatch.setattr(sw, "_vision_pick", lambda imgs, *a: (imgs[0], "полотно бренда"))
    out = sw._attach_media([], "тело", "Robinhood", "k")
    assert out == str(found), "статей нет — обложка всё равно есть, её принёс поиск"


# ── ОТКАЗ ИСТОЧНИКА БОЛЬШЕ НЕ МОЛЧИТ ──────────────────────────────────────────────────────────
def test_fetch_bytes_asks_for_gzip_and_accept():
    """Без этих заголовков Wikimedia отдавала 429 с третьего запроса — и обложка зависела от везения."""
    for headers in (feeds._BOT_HEADERS, feeds._BROWSER_HEADERS):
        assert headers.get("Accept-Encoding") == "gzip"
        assert headers.get("Accept")


def test_fetch_bytes_reports_reason(monkeypatch):
    """Причина отказа должна доезжать до вызывающего: молчаливый None и терял лучшие источники."""
    import urllib.error
    monkeypatch.setattr(feeds, "_url_blocked_reason", lambda url: None)

    def boom(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
    monkeypatch.setattr(feeds._SAFE_OPENER, "open", boom)
    assert feeds.fetch_bytes("https://x.example/a") is None
    assert "429" in feeds.last_error("https://x.example/a")


# ── ДВА ЗАЗОРА, ЗАКРЫТЫЕ 31.08 ПО ТРЕБОВАНИЮ «БЕЗ НО» ─────────────────────────────────────────
# Владелец: «мне нужно чтобы точно было без НО, потому что если я могу руками — значит и он должен
# уметь». Оба оставшихся «но» были зависимостями: от дисциплины писателя и от полноты справочника.

def test_subject_taken_from_post_when_meta_missing():
    """Нет [[MEDIA_SUBJECT]] — объект берём из самого поста, а не разводим руками."""
    post = ("**📉 Robinhood построил сеть под акции, а выкупили её мемы**\n\n"
            "30 августа сеть Robinhood Chain сделала рекордный день, обогнав Ethereum")
    got = sw._subject_from_post(post)
    assert "Robinhood" in got and "Ethereum" in got


def test_subject_from_post_skips_sentence_openers():
    """Служебные заглавные (начало вставки, тикеры, аббревиатуры) именем объекта не считаются."""
    assert sw._subject_from_post("The ETF is big. This DeFi thing. But USDC grew.") == ""


def test_official_site_found_by_link_from_the_article(monkeypatch):
    """Так делает человек: читает статью и кликает на проект. Проверено вживую на Ostium."""
    monkeypatch.setattr(sm.fetch, "page_html", lambda url:
                        '<a href="https://x.com/ostium">x</a> <a href="https://www.ostium.com/">сайт</a>')
    monkeypatch.setattr(sm.feeds, "fetch_bytes", lambda url, **kw:
                        (b"<title>Ostium | Trade the markets</title>", "text/html"))
    assert sm.official_site_from_pages("Ostium", ["https://media.example/a"]) == "https://www.ostium.com"


def test_socials_and_aggregators_are_never_the_official_site(monkeypatch):
    """Соцсети линкуют все и всегда — официальным сайтом объекта они не бывают."""
    monkeypatch.setattr(sm.fetch, "page_html", lambda url: '<a href="https://x.com/ostium">x</a>')
    monkeypatch.setattr(sm.feeds, "fetch_bytes", lambda url, **kw: (b"<title>Ostium</title>", "text/html"))
    assert sm.official_site_from_pages("Ostium", ["https://media.example/a"]) is None


def test_parked_domain_is_not_the_official_site(monkeypatch):
    """Живой промах 31.08: «Robinhood Chain» вывел на robinhoodchain.org с заголовком «For Sale
    Domain». Имя объекта в заголовке там есть — потому что торгуют его доменом, а не потому что это
    он. Проверки «называет себя» мало, нужен отсев заглушек."""
    monkeypatch.setattr(sm.fetch, "page_html", lambda url: '<a href="https://ostium.com/">сайт</a>')
    monkeypatch.setattr(sm.feeds, "fetch_bytes", lambda url, **kw:
                        (b"<title>For Sale Domain: ostium.com</title>", "text/html"))
    assert sm.official_site_from_pages("Ostium", ["https://media.example/a"]) is None


def test_domain_guessing_is_gone():
    """Угадывание домена по имени снято: «Robinhood Chain» так приводило на припаркованного
    сквоттера robinhoodchain.org с заголовком «For Sale Domain», и проверка имени его пропускала.
    Ссылка из статьи опирается на факт, догадка по имени — нет."""
    assert not hasattr(sm, "official_site_by_name")


def test_neutral_wikidata_description_is_never_accepted(monkeypatch):
    """«Jito» → императрица Японии (645-703), «Ethena» → «статья энциклопедии». Оба описания не
    запрещены явно и раньше проходили. Запретный список всегда отстаёт — разрешительный нет."""
    monkeypatch.setattr(sm, "_api_json", lambda url: {"search": [
        {"id": "Q232026", "description": "Empress of Japan (645-703)"},
        {"id": "Q104069387", "description": "encyclopedia article"},
    ]})
    assert sm.entity_id("Jito") == ("", "")
