"""Юнит-тесты парсинга медиа-меты scope (чистые функции, без сети/LLM). Контракт scope → обложка:
если формат маркеров поедет, эти тесты поймают молчаливую поломку. Запуск: python -m pytest."""
from __future__ import annotations

from core import cost
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


# ── ОТКАЗ ВЫБОРА: «0» обязан доехать как «обложки нет» (правило «ИИ-сток не берём», 26.08) ────────
# Запрет на ИИ-рендер живёт в _MEDIA_CRITERIA — это задача классификации, ей место в промпте.
# А вот РАЗБОР ответа — код, и он не должен молча превращать отказ в первую попавшуюся картинку.

class _FakeResp:
    def __init__(self, text):
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.usage = type("U", (), {"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": 0,
                                    "cache_read_input_tokens": 0})()


def _fake_vision(monkeypatch, tmp_path, answer):
    """Подменяет Anthropic-вызов внутри _vision_pick заранее заданным ответом модели."""
    imgs = []
    for i in range(3):
        p = tmp_path / f"c{i}.jpg"
        p.write_bytes(b"\xff\xd8" + b"0" * 100)
        imgs.append(p)

    class _Msgs:
        def create(self, **kw):
            return _FakeResp(answer)

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Msgs()

    monkeypatch.setattr(sw, "Anthropic", _Client)
    monkeypatch.setattr(sw.cost, "record", lambda *a, **k: None)
    return imgs


def test_vision_pick_zero_means_no_cover(monkeypatch, tmp_path):
    imgs = _fake_vision(monkeypatch, tmp_path, "0")
    assert sw._vision_pick(imgs, "тело поста", "Dallas Fed", "key") is None


def test_vision_pick_takes_number(monkeypatch, tmp_path):
    imgs = _fake_vision(monkeypatch, tmp_path, "2")
    assert sw._vision_pick(imgs, "тело поста", "Dallas Fed", "key") == imgs[1]


def test_vision_pick_out_of_range_is_no_cover(monkeypatch, tmp_path):
    imgs = _fake_vision(monkeypatch, tmp_path, "7")
    assert sw._vision_pick(imgs, "тело поста", "Dallas Fed", "key") is None


def test_media_criteria_ban_ai_render():
    """Страж правила: запрет ИИ-рендера — решение владельца, а не украшение промпта."""
    c = sw._MEDIA_CRITERIA
    assert "ИИ-РЕНДЕР НЕ БЕРЁМ" in c
    assert "неоново" in c or "неоновое" in c
    assert "ТОЛЬКО ИИ-рендеры/ИИ-инфографика → 0" in c


# --- ИИ-ИНФОГРАФИКА (баг 28.08) ----------------------------------------------------------------
# Пост про SGP-0002: в пул пришли ТРИ картинки, все три — ИИ-генерация, то есть по правилу 26.08
# обложки в пуле не было вовсе. Взяли ИИ-инфографику, потому что запрет описывал только «крипто-
# футуризм» (неон, парящие монеты, 3D), а разрешающий п.2 прямо велел брать «график/дашборд». Нарисован-
# ная инфографика формально проходила как график и обошла запрет ЗАКОННО. Хуже: на ней крупно стояло
# «99.4% from staking» — ровно та цифра, которую 2FA из ТЕКСТА выбросил как неподтверждённую (до
# картинки он не достаёт). Пост сказал бы «почти вся выручка», а обложка кричала бы 99.4%.

def test_media_criteria_ban_ai_infographic():
    c = sw._MEDIA_CRITERIA
    assert "ИИ-ИНФОГРАФИКА" in c
    assert "99.4" in c, "у запрета должен быть его повод — иначе правило сотрут как украшение"


def test_media_criteria_demands_screenshot_not_drawing():
    """П.2 обязан требовать СНЯТЫЙ кадр: иначе нарисованная картинка с цифрами снова пройдёт как график."""
    c = sw._MEDIA_CRITERIA
    assert "СКРИНШОТ РЕАЛЬНОГО" in c
    assert "оси" in c and "легенда" in c, "интерфейс — то, чем скриншот отличается от рисунка"


def test_media_criteria_resolves_doubt_against_the_picture():
    """Цена ошибки несимметрична: скучный настоящий кадр стоит ноль, ИИ-слоп в канале бьёт по бренду."""
    assert "считай рисованным" in sw._MEDIA_CRITERIA


def test_cover_pick_is_not_on_the_cheapest_tier():
    """Выбор обложки — РАЗЛИЧЕНИЕ рисунка и скриншота, а не грубый гейт «картинка осмысленная?».
    28.08 Haiku выбрал самую убедительную ИИ-инфографику вместо того, чтобы вернуть 0."""
    assert sw.VISION_PICK_MODEL != sw.VISION_MODEL
    assert sw.VISION_PICK_MODEL in cost.RATES, "новых моделей в учёт не заводим — цена должна быть известна"


# ── СКОУП НЕ РИСУЕТ КАРТИНКИ. НИКОГДА. (владелец 28.08, безоговорочно) ───────────────────────────
# «Генератор картинки только флагман — это безоговорочно должно быть». В пайплайне стоял фолбэк
# «нет кадра → рисуем GPT-обложку из поста» (22.07), про который владелец не знал. После вето на
# ИИ-рендер (26.08) он стал прямо вредным: вето отправляет чужой ИИ-сток в 0, а 0 вёл в рисование —
# запрет на ИИ-обложку отменял сам себя. Инструмент у scope_writer отобран давно; сторожим ОБА пути.

def test_scope_has_no_image_tool():
    assert "make_image" in sw._DROP, "рисование не входит в «руки» скоупа"


def test_pipeline_scope_branch_never_generates():
    """Страж ветки пайплайна: между выбором обложки 🔭 и публикацией не должно быть генерации."""
    from core import config
    src = (config.ROOT / "run_pipeline.py").read_text(encoding="utf-8")
    start = src.index("СКОУП КАРТИНКИ НЕ РИСУЕТ")
    end = src.index("[3/3] Ставлю в отложенные", start)
    branch = src[start:end]
    assert "make_image" not in branch, "скоуп снова научился рисовать обложку — это запрещено"
    assert "MEDIA_OUTBOX" not in branch, "аутбокс флагман-обложки к скоупу отношения не имеет"
