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
    """Уводит ВСЕ пути записи обложки во временную папку — и файл-указатель, и журнал анти-повтора.
    Урок 26.08: тест, забывший увести хоть один путь, пишет в боевой data/ и портит рабочее состояние."""
    from core import creator_tools, scope_cover_log
    monkeypatch.setattr(creator_tools, "SCOPE_COVER", tmp_path / "cover.txt")
    monkeypatch.setattr(scope_cover_log, "LOG", tmp_path / "scope_cover_log.jsonl")


def _no_subject_search(monkeypatch):
    """Глушит ПОИСК КАДРА ПО ОБЪЕКТУ повода (31.08). Он ходит в сеть (Wikidata/Commons/сайт объекта),
    поэтому в юнит-тестах пула его не зовём: иначе тест мерит не свою логику, а сегодняшнюю выдачу
    Wikimedia — и падает от чужого 429. Маршрут проверяется отдельными тестами ниже."""
    monkeypatch.setattr(sw.source_media, "subject_image_urls", lambda subject, limit=3: [])


def _spy_pick(monkeypatch, seen: dict):
    """Подменяет vision-выбор и запоминает, СКОЛЬКО кандидатов до него доехало."""
    def pick(imgs, *a):
        seen["n"] = len(imgs)
        return (imgs[0], "ярлык") if imgs else None
    monkeypatch.setattr(sw, "_vision_pick", pick)


def test_attach_media_collects_frames_from_every_page(monkeypatch, tmp_path):
    _cover_to_tmp(monkeypatch, tmp_path)
    _no_subject_search(monkeypatch)
    monkeypatch.setattr(sw.source_media, "fetch_source_images",
                        lambda url, name="scope": [tmp_path / f"{name}_0.jpg", tmp_path / f"{name}_1.jpg"])
    seen = {}
    _spy_pick(monkeypatch, seen)
    out = sw._attach_media(["https://a.com/x", "https://b.com/y"], "тело", "Dallas Fed", "k")
    assert seen["n"] == 4, "два кадра с каждой из двух страниц"
    assert out.endswith("scope_0_0.jpg")


def test_attach_media_stops_at_pool_cap(monkeypatch, tmp_path):
    _cover_to_tmp(monkeypatch, tmp_path)
    _no_subject_search(monkeypatch)
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
    monkeypatch.setattr(sw, "_vision_pick", lambda imgs, *a: (imgs[0], "ярлык"))
    out = sw._attach_media(["https://bad.com/x", "https://ok.com/y"], "тело", "субъект", "k")
    assert out.endswith("scope_1_0.jpg")


def test_attach_media_empty_pool_goes_text(monkeypatch, tmp_path):
    _cover_to_tmp(monkeypatch, tmp_path)
    _no_subject_search(monkeypatch)
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
    assert sw._vision_pick(imgs, "тело поста", "Dallas Fed", "key")[0] == imgs[1]


def test_vision_pick_out_of_range_is_no_cover(monkeypatch, tmp_path):
    imgs = _fake_vision(monkeypatch, tmp_path, "7")
    assert sw._vision_pick(imgs, "тело поста", "Dallas Fed", "key") is None


def test_media_criteria_ban_ai_render():
    """Страж правила: запрет ИИ-стока — решение владельца, а не украшение промпта."""
    c = sw._MEDIA_CRITERIA
    assert "ИИ-СТОК «КРИПТО-ФУТУРИЗМ» НЕ БЕРЁМ" in c
    assert "неоново" in c or "неоновое" in c
    assert "Только ИИ-сток или псевдо-дашборд в пуле → 0" in c


# ── ТАКСОНОМИЯ ВЫВЕДЕНА ИЗ 23 ПРИНЯТЫХ ОБЛОЖЕК (замер 28.08) ────────────────────────────────────
# Владелец: «проанализируй картинки, которые уже на канале — вот тебе и будут характеристики».
# Раньше критерии были списком запретов, каждый добавлен после очередного промаха. Теперь у них есть
# положительная половина, и она держится на замере, а не на моих догадках.

def test_criteria_lists_measured_cover_types():
    c = sw._MEDIA_CRITERIA
    for t in ("СНЯТЫЙ ОБЪЕКТ КОМПАНИИ/ИНСТИТУТА", "ФИРМЕННОЕ ПОЛОТНО БРЕНДА", "ЧЕЛОВЕК ИЗ ПОВОДА",
              "ПРЕДМЕТ КРУПНО", "РЕДАКЦИОННАЯ ИЛЛЮСТРАЦИЯ"):
        assert t in c, f"тип «{t}» пропал из критериев — замер 23 обложек его нашёл"


def test_dashboard_screenshot_is_not_the_anchor():
    """Скриншот графика стоял вторым по приоритету, а среди 23 принятых таких НОЛЬ. Не ориентир."""
    c = sw._MEDIA_CRITERIA
    assert "НОЛЬ" in c and "специально не ищи" in c


def test_drawn_editorial_illustration_is_allowed():
    """Мой запрет 28.08 на «рваный коллаж» забраковал бы принятый #460 — снят по факту.
    Рисованное как таковое НЕ запрещено: запрещена претензия картинки быть источником данных."""
    c = sw._MEDIA_CRITERIA
    assert "НЕ запрет на рисованное вообще" in c
    assert "коллаж" in c
    assert "рваный" not in c, "признак снят: ровно так выглядит принятая обложка #460"


def test_ban_targets_data_pretension_not_drawing():
    c = sw._MEDIA_CRITERIA
    assert "ПРЕТЕНДУЮЩИЙ БЫТЬ ИСТОЧНИКОМ ДАННЫХ" in c
    assert "99.4" in c, "у запрета должен быть его повод — иначе правило сотрут как украшение"
    assert "примет цифры с этой картинки за факт" in c, "нужен рабочий тест, а не список признаков"


def test_text_on_cover_is_not_a_defect():
    """Почти на каждой принятой обложке есть надпись (бренд, вывеска, заголовок) — браковать нельзя."""
    assert "ТЕКСТ НА КАДРЕ — НОРМА" in sw._MEDIA_CRITERIA


def test_subject_logo_is_first_class():
    """Лого компании из повода — самый частый принятый кадр (7 из 23) и не вотермарк."""
    c = sw._MEDIA_CRITERIA
    assert "вотермарком НЕ считается" in c


def test_cover_pick_is_not_on_the_cheapest_tier():
    """Выбор обложки — РАЗЛИЧЕНИЕ рисунка и скриншота, а не грубый гейт «картинка осмысленная?».
    28.08 Haiku выбрал самую убедительную ИИ-инфографику вместо того, чтобы вернуть 0."""
    assert sw.VISION_PICK_MODEL != sw.VISION_MODEL
    assert sw.VISION_PICK_MODEL in cost.RATES, "новых моделей в учёт не заводим — цена должна быть известна"


# ── ЯРЛЫК КАДРА И АНТИ-ПОВТОР (владелец 28.08: «чтобы не повторялись — надо проверять») ──────────
# У флагмана журнал обложек есть с 16.07 и работает; у скоупа не было ничего, кроме пути к последнему
# файлу. Ярлык кадра даёт vision тем же вызовом, которым выбирает номер, — лишнего запроса это не стоит.

def test_vision_pick_returns_label(monkeypatch, tmp_path):
    imgs = _fake_vision(monkeypatch, tmp_path, "2 | лого Solana")
    path, label = sw._vision_pick(imgs, "тело поста", "Solana", "key")
    assert path == imgs[1] and label == "лого Solana"


def test_number_comes_from_head_not_from_label(monkeypatch, tmp_path):
    """Цифра в ЯРЛЫКЕ («Solana 2.0», «Q3 2026») не должна подменять выбранный номер."""
    imgs = _fake_vision(monkeypatch, tmp_path, "1 | лого Solana 2.0")
    assert sw._vision_pick(imgs, "тело", "Solana", "key")[0] == imgs[0]


def test_bare_number_still_works(monkeypatch, tmp_path):
    """Формата не удержал — старое поведение живо, обложку из-за этого не теряем."""
    imgs = _fake_vision(monkeypatch, tmp_path, "3")
    assert sw._vision_pick(imgs, "тело", "субъект", "key")[0] == imgs[2]


def test_zero_with_label_is_still_no_cover(monkeypatch, tmp_path):
    imgs = _fake_vision(monkeypatch, tmp_path, "0 | только ИИ-рендеры")
    assert sw._vision_pick(imgs, "тело", "субъект", "key") is None


def test_attach_media_writes_cover_log(monkeypatch, tmp_path):
    from core import scope_cover_log
    _cover_to_tmp(monkeypatch, tmp_path)
    monkeypatch.setattr(sw.source_media, "fetch_source_images",
                        lambda url, name="scope": [tmp_path / f"{name}_0.jpg"])
    monkeypatch.setattr(sw, "_vision_pick", lambda imgs, *a: (imgs[0], "лого Solana"))
    sw._attach_media(["https://a.com/x"], "**Solana урезала инфляцию**\n\nтело", "Solana", "k")
    assert scope_cover_log.recent() == ["лого Solana"]


def test_avoid_hint_empty_without_history(monkeypatch, tmp_path):
    """Пустой журнал не должен сорить в промпт выбора (первый прогон)."""
    from core import scope_cover_log
    monkeypatch.setattr(scope_cover_log, "LOG", tmp_path / "none.jsonl")
    assert scope_cover_log.avoid_hint() == ""


def test_avoid_hint_is_advice_not_veto(monkeypatch, tmp_path):
    """Похожесть НЕ повод уйти текстом: скоуп рисовать не может, значит один годный кадр важнее разнообразия."""
    from core import scope_cover_log
    monkeypatch.setattr(scope_cover_log, "LOG", tmp_path / "log.jsonl")
    scope_cover_log.record("лого Solana", "заголовок")
    hint = scope_cover_log.avoid_hint()
    assert "лого Solana" in hint
    assert "СОВЕТ, а не запрет" in hint and "текстом" in hint


def test_cover_log_keeps_window_order(monkeypatch, tmp_path):
    """Свежие первыми и не длиннее окна — иначе промпт растёт, а старые кадры давят на выбор."""
    from core import scope_cover_log
    monkeypatch.setattr(scope_cover_log, "LOG", tmp_path / "log.jsonl")
    for i in range(9):
        scope_cover_log.record(f"кадр {i}")
    got = scope_cover_log.recent()
    assert got[0] == "кадр 8" and len(got) == scope_cover_log.WINDOW


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
