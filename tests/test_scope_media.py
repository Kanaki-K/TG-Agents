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


# ── ДВА КРУГА СУДЬИ: НОЛЬ ПЕРВОГО КРУГА — НЕ РЕШЕНИЕ (07.09) ────────────────────────────────────
# С 31.08 по 07.09 судья не выбрал НИ ОДНОЙ обложки: четыре скоупа подряд ушли голым текстом, хотя
# 07.09 в пуле лежали фирменное полотно Liquid Network и редакционный коллаж ровно про этот повод.
# Ноль стоил столько же, сколько выбор, — теперь он стоит второго вопроса: «что здесь ВРЕДНОГО».

def _fake_vision_seq(monkeypatch, tmp_path, answers):
    """Как _fake_vision, но отдаёт ответы по очереди — чтобы проверить ВТОРОЙ круг."""
    imgs = []
    for i in range(3):
        q = tmp_path / f"c{i}.jpg"
        q.write_bytes(b"\xff\xd8" + b"0" * 100)
        imgs.append(q)
    seq = list(answers)

    class _Msgs:
        def create(self, **kw):
            return _FakeResp(seq.pop(0) if seq else "0")

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Msgs()

    monkeypatch.setattr(sw, "Anthropic", _Client)
    monkeypatch.setattr(sw.cost, "record", lambda *a, **k: None)
    return imgs


def test_second_round_rescues_the_cover(monkeypatch, tmp_path):
    """Первый круг сказал 0 — обложка всё равно обязана найтись среди невредных кадров."""
    imgs = _fake_vision_seq(monkeypatch, tmp_path, ["0 | только ИИ-рендеры", "2 | вордмарк Bitmine"])
    got = sw._vision_pick(imgs, "тело поста", "Bitmine", "key")
    assert got is not None, "ноль первого круга не должен оставлять пост без картинки"
    assert got[0] == imgs[1] and got[1] == "вордмарк Bitmine"
    assert "второго круга" in sw.LAST_COVER_NOTE, "панель обязана показать, каким кругом взят кадр"


def test_first_round_pick_does_not_ask_twice(monkeypatch, tmp_path):
    """Нормальный случай: выбрал сразу — второго вызова (и лишних денег) быть не должно."""
    imgs = _fake_vision_seq(monkeypatch, tmp_path, ["2 | печать SEC"])
    got = sw._vision_pick(imgs, "тело поста", "SEC", "key")
    assert got[0] == imgs[1]
    assert sw.LAST_COVER_NOTE == "выбор с первого круга"


def test_zero_twice_is_the_only_refusal(monkeypatch, tmp_path):
    """Отказ остаётся возможным — но только когда ОБА круга сказали «весь пул вредный»."""
    imgs = _fake_vision_seq(monkeypatch, tmp_path, ["0", "0 | всё ИИ-слоп"])
    assert sw._vision_pick(imgs, "тело поста", "Dallas Fed", "key") is None
    assert "вредный" in sw.LAST_COVER_NOTE


# ── ИНСТРУКЦИЯ ОТБОРА ЖИВЁТ В ПАМЯТИ, А НЕ В КОДЕ ───────────────────────────────────────────────
# Владелец 07.09: «проведи анализ всех скоупов и картинок к постам, собери инструкцию подбора».
# Инструкция выведена из 23 опубликованных обложек, прочитанных вместе с ТЕКСТАМИ их постов, и
# лежит в memory/scope_cover_manual.md — владелец правит её руками, как остальные мануалы.

def test_cover_rules_come_from_memory():
    r = sw._cover_rules()
    assert "ПОРТРЕТ ГЕРОЯ ПОВОДА" in r, "главное правило замера пропало из инструкции"
    assert "НЕ РИСУЕТ" in r, "запрет рисовать — решение владельца, он должен доезжать до судьи"
    assert "## 8." not in r, "каталог замера — материал для человека, в промпт его не тянем"


def test_cover_manual_keeps_all_measured_routes():
    """Пять маршрутов = то, откуда обложки реально брались. Пропал маршрут — сузился поиск."""
    r = sw._cover_rules()
    for route in ("Снятый объект компании или института", "Фирменное полотно или пресс-материал",
                  "Человек из повода", "Предмет повода крупно", "Иллюстрация издания-первоисточника"):
        assert route in r, f"маршрут «{route}» пропал из инструкции"


def test_cover_manual_forbids_zero():
    """§7: «ничего не подошло» — не ответ. Это ровно тот сбой, из-за которого чинили 07.09."""
    r = sw._cover_rules()
    assert "Ноль запрещён" in r
    assert "наименее плохой" in r


def test_text_on_cover_is_not_a_defect():
    """18 из 23 принятых обложек несут надпись (бренд, вывеска, заголовок) — браковать нельзя."""
    assert "Надпись на кадре — норма" in sw._cover_rules()


def test_small_frame_is_not_a_reason_to_refuse():
    """Самая мелкая ПРИНЯТАЯ обложка канала — 499x281 (#440). Порог «мелко» бил по принятому."""
    assert "499×281" in sw._cover_rules()


def test_harm_list_is_the_only_ground_for_refusal():
    """Второй круг отсекает по ВРЕДУ. Если в список просочится «скучно» — вернётся старый сбой."""
    h = sw._COVER_HARM
    for sign in ("ИИ-генерация", "вотермарк", "18+", "мерч", "квитанция", "скриншот интерфейса",
                 "просто дом", "полями по бокам", "ПРОТИВОРЕЧАЩИЙ углу"):
        assert sign in h, f"пункт стоп-листа «{sign}» пропал из списка вреда"
    assert "«Скучно», «слабовато», «не идеально по смыслу», «похожее уже было» — НЕ вред" in h


def test_rules_fall_back_when_manual_missing(monkeypatch):
    """Файл памяти не доехал — судья всё равно получает ядро правил, а не пустую строку."""
    monkeypatch.setattr(sw, "_read", lambda rel: "")
    r = sw._cover_rules()
    assert "ПОРТРЕТ ГЕРОЯ ПОВОДА" in r and len(r) > 200


def test_cover_pick_is_not_on_the_cheapest_tier():
    """Выбор обложки — РАЗЛИЧЕНИЕ рисунка и скриншота, а не грубый гейт «картинка осмысленная?».
    28.08 Haiku на этом ошибся: из трёх ИИ-картинок выбрал самую убедительную ИИ-инфографику."""
    assert "haiku" not in sw.VISION_PICK_MODEL
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


# ── КОРЕНЬ СБОЯ 28.08–07.09: СУДЬЯ МОЛЧАЛ, А КОД ЗВАЛ ЭТО «НЕ НАШЛОСЬ» ───────────────────────────
# Роль переехала на claude-sonnet-5 (0fba26b, 28.08). Модель новее думает по умолчанию, а вызов стоял
# с max_tokens=40 — весь бюджет уходил в блок thinking, текста в ответе не оставалось. Пять скоупов
# подряд ушли голым текстом, и панель всё это время писала «годного кадра не нашлось».

class _ThinkingOnlyResp:
    """Ответ модели, где весь бюджет съело мышление: блок есть, текста нет."""
    def __init__(self):
        self.stop_reason = "max_tokens"
        self.content = [type("B", (), {"type": "thinking", "thinking": "..."})()]
        self.usage = type("U", (), {"input_tokens": 1, "output_tokens": 40,
                                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0})()


def test_judge_is_asked_without_thinking(monkeypatch, tmp_path):
    """Мышление гасим ЯВНО и держим запас токенов: иначе судья снова замолчит."""
    seen = {}

    class _Msgs:
        def create(self, **kw):
            seen.update(kw)
            return _FakeResp("1 | печать ФРС")

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Msgs()

    imgs = _fake_vision(monkeypatch, tmp_path, "1 | печать ФРС")
    monkeypatch.setattr(sw, "Anthropic", _Client)
    sw._vision_pick(imgs, "тело", "ФРС", "key")
    assert seen.get("thinking") == {"type": "disabled"}, "мышление у судьи должно быть выключено явно"
    assert seen.get("max_tokens", 0) >= 100, "40 токенов не оставляли запаса — ровно на этом всё и встало"


def test_silent_judge_is_reported_as_breakage(monkeypatch, tmp_path):
    """Пустой ответ — техническая поломка. Панель не должна выдавать её за «нет годных кадров»."""
    imgs = _fake_vision(monkeypatch, tmp_path, "")

    class _Msgs:
        def create(self, **kw):
            return _ThinkingOnlyResp()

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Msgs()

    monkeypatch.setattr(sw, "Anthropic", _Client)
    assert sw._vision_pick(imgs, "тело", "ФРС", "key") is None
    assert "сбой" in sw.LAST_COVER_NOTE and "не ответил" in sw.LAST_COVER_NOTE


def test_model_without_thinking_param_still_works(monkeypatch, tmp_path):
    """Модель не знает параметра (400) — повторяем без него, а не остаёмся без обложки."""
    from anthropic import BadRequestError
    imgs = _fake_vision(monkeypatch, tmp_path, "2 | вывеска BNY")
    calls = []

    class _Msgs:
        def create(self, **kw):
            calls.append(kw)
            if "thinking" in kw:
                raise BadRequestError("thinking not supported", response=type("R", (), {
                    "status_code": 400, "headers": {}, "request": None})(), body=None)
            return _FakeResp("2 | вывеска BNY")

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Msgs()

    monkeypatch.setattr(sw, "Anthropic", _Client)
    got = sw._vision_pick(imgs, "тело", "BNY", "key")
    assert got is not None and got[0] == imgs[1]
    assert len(calls) == 2 and "thinking" not in calls[1]


def test_old_sdk_without_thinking_param_still_works(monkeypatch, tmp_path):
    """Параметра не знает не модель, а старый SDK — это TypeError. Обложка теряться не должна."""
    imgs = _fake_vision(monkeypatch, tmp_path, "1 | фасад BNY")
    calls = []

    class _Msgs:
        def create(self, **kw):
            calls.append(kw)
            if "thinking" in kw:
                raise TypeError("create() got an unexpected keyword argument 'thinking'")
            return _FakeResp("1 | фасад BNY")

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Msgs()

    monkeypatch.setattr(sw, "Anthropic", _Client)
    got = sw._vision_pick(imgs, "тело", "BNY", "key")
    assert got is not None and got[0] == imgs[0]
    assert len(calls) == 2 and "thinking" not in calls[1]


# ── ФОРМАТ КАНАЛА: ВЕРТИКАЛЬ ДО СУДЬИ НЕ ДОХОДИТ, ПОКА ЕСТЬ ГОРИЗОНТАЛЬ (07.09) ─────────────────
# Владелец: «нам нужно горизонтальное фото, как было раньше — если я прошу провести анализ того,
# что было, то и формат должен быть такой же». Замер: 21 из 23 обложек — снятая горизонталь.

def _pool(monkeypatch, tmp_path, ratios):
    """Пул из готовых файлов с заданными ИСХОДНЫМИ пропорциями."""
    _cover_to_tmp(monkeypatch, tmp_path)
    _no_subject_search(monkeypatch)
    made = []
    for i, r in enumerate(ratios):
        q = tmp_path / f"p{i}.jpg"
        q.write_bytes(b"\xff\xd8" + b"0" * 100)
        monkeypatch.setitem(sw.source_media.fetch._ORIG_RATIO, str(q), r)
        made.append(q)
    monkeypatch.setattr(sw.source_media, "fetch_source_images", lambda url, name="scope": list(made))
    monkeypatch.setattr(sw.source_media, "frame_fingerprint", lambda p: str(p))
    monkeypatch.setattr(sw.source_media, "looks_same", lambda a, b: a == b)
    return made


def test_vertical_is_dropped_while_horizontal_exists(monkeypatch, tmp_path):
    made = _pool(monkeypatch, tmp_path, [0.66, 1.78, 1.0])   # вертикаль, горизонталь, квадрат
    seen = {}
    monkeypatch.setattr(sw, "_vision_pick", lambda imgs, *a: seen.update(pool=list(imgs)) or (imgs[0], "кадр"))
    sw._attach_media(["https://a.com/x"], "тело", "субъект", "k")
    assert seen["pool"] == [made[1]], "судья обязан видеть только снятую горизонталь"
    assert "не-горизонталь отсеяна: 2" in sw.LAST_POOL_NOTE, "панель должна показать, что отсеяно"


def test_vertical_is_never_padded_into_the_pool(monkeypatch, tmp_path):
    """Владелец 07.09 внёс поля в стоп-лист первым пунктом: «вертикальные фото в горизонтальном
    формате» — нельзя. Раньше тут был фолбэк «нет горизонтали — берём вертикаль с полями», и он же
    отправил в отложку башню DBS посреди синих полей. Пустой пул честнее плохой обложки."""
    made = _pool(monkeypatch, tmp_path, [0.66, 1.0])
    monkeypatch.setattr(sw, "_vision_pick", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("судью звать не с чем — весь пул это поля по бокам")))
    assert sw._attach_media(["https://a.com/x"], "тело", "субъект", "k") == ""
    assert "не-горизонталь отсеяна: 2" in sw.LAST_POOL_NOTE


# ── ПУЛ: ШАПКИ ПЕРЕД ТЕЛОМ, ПОИСК ПО ОБЪЕКТУ — СТРАХОВКА (07.09) ────────────────────────────────
# Владелец, сравнив data/source_media с data/published_covers: «соурс медиа — низкокачественное
# дерьмо, публишед коверс — отличный формат. Он продолжает делать дерьмо, когда есть отличный».
# Все 23 принятые обложки — шапки материала. Из тела статьи не пришла ни одна: там живут аватарки
# колумнистов, инлайн-инфографика и превью соседних новостей.

def test_body_frames_dropped_while_headers_exist(monkeypatch, tmp_path):
    _cover_to_tmp(monkeypatch, tmp_path)
    _no_subject_search(monkeypatch)
    made = []
    for i, role in enumerate(("шапка", "тело", "тело")):
        q = tmp_path / f"h{i}.jpg"
        q.write_bytes(b"\xff\xd8" + b"0" * 100)
        monkeypatch.setitem(sw.source_media.fetch._ROLE, str(q), role)
        monkeypatch.setitem(sw.source_media.fetch._ORIG_RATIO, str(q), 1.78)
        made.append(q)
    monkeypatch.setattr(sw.source_media, "fetch_source_images", lambda url, name="scope": list(made))
    monkeypatch.setattr(sw.source_media, "frame_fingerprint", lambda p: str(p))
    monkeypatch.setattr(sw.source_media, "looks_same", lambda a, b: a == b)
    seen = {}
    monkeypatch.setattr(sw, "_vision_pick", lambda imgs, *a: seen.update(pool=list(imgs)) or (imgs[0], "кадр"))
    sw._attach_media(["https://a.com/x"], "тело", "субъект", "k")
    assert seen["pool"] == [made[0]], "инлайн-картинки статьи до судьи доходить не должны"
    assert "кадры из тела статей отсеяны: 2" in sw.LAST_POOL_NOTE


def test_subject_search_is_a_fallback_not_the_first_route(monkeypatch, tmp_path):
    """31.08 поиск по объекту стоял ПЕРВЫМ и подменял «кадр про событие» на «фото фирмы вообще».
    Страницы дали достаточно — поиск не запускаем (и не тратим на него сеть и время)."""
    _cover_to_tmp(monkeypatch, tmp_path)
    called = []
    monkeypatch.setattr(sw.source_media, "subject_image_urls",
                        lambda *a, **k: called.append(1) or [])
    made = []
    for i in range(2):
        q = tmp_path / f"g{i}.jpg"
        q.write_bytes(b"\xff\xd8" + b"0" * 100)
        monkeypatch.setitem(sw.source_media.fetch._ORIG_RATIO, str(q), 1.78)
        made.append(q)
    monkeypatch.setattr(sw.source_media, "fetch_source_images", lambda url, name="scope": list(made))
    monkeypatch.setattr(sw.source_media, "frame_fingerprint", lambda p: str(p))
    monkeypatch.setattr(sw.source_media, "looks_same", lambda a, b: a == b)
    monkeypatch.setattr(sw, "_vision_pick", lambda imgs, *a: (imgs[0], "кадр"))
    sw._attach_media(["https://a.com/x"], "тело", "субъект", "k")
    assert not called, "две шапки со страниц повода — поиск по объекту не нужен"


def test_subject_search_still_saves_an_empty_pool(monkeypatch, tmp_path):
    """А когда страницы молчат (429/403, как 31.08) — страховка обязана сработать."""
    _cover_to_tmp(monkeypatch, tmp_path)
    q = tmp_path / "subj.jpg"
    q.write_bytes(b"\xff\xd8" + b"0" * 100)
    monkeypatch.setitem(sw.source_media.fetch._ORIG_RATIO, str(q), 1.78)
    monkeypatch.setattr(sw.source_media, "fetch_source_images", lambda url, name="scope": [])
    monkeypatch.setattr(sw.source_media, "subject_image_urls", lambda *a, **k: ["https://cdn/x.jpg"])
    monkeypatch.setattr(sw.source_media, "download", lambda url, name="scope", min_side=0: q)
    monkeypatch.setattr(sw.source_media, "frame_fingerprint", lambda p: str(p))
    monkeypatch.setattr(sw.source_media, "looks_same", lambda a, b: a == b)
    monkeypatch.setattr(sw, "_vision_pick", lambda imgs, *a: (imgs[0], "кадр"))
    assert sw._attach_media(["https://a.com/x"], "тело", "субъект", "k")


def test_forced_pick_that_admits_a_violation_is_a_refusal(monkeypatch, tmp_path):
    """Второй круг запрещает ноль — и на мусорном пуле модель называет номер, а в ярлыке пишет, за
    что кадр браковать («не по теме», «это ИИ-генерация»). Номер из-под палки — не выбор."""
    imgs = _fake_vision_seq(monkeypatch, tmp_path, ["0", "2 | старинная церковь, не по теме"])
    assert sw._vision_pick(imgs, "тело", "Binance", "key") is None
    assert "забраковал весь пул" in sw.LAST_COVER_NOTE


def test_normal_label_is_not_mistaken_for_a_confession(monkeypatch, tmp_path):
    imgs = _fake_vision_seq(monkeypatch, tmp_path, ["0", "2 | вход в штаб-квартиру BNY"])
    got = sw._vision_pick(imgs, "тело", "BNY", "key")
    assert got is not None and got[0] == imgs[1]


def test_first_round_confession_goes_to_second_round(monkeypatch, tmp_path):
    """07.09 первый круг вернул «ИИ-рисунок кита. Однако по стоп-листу это ИИ-генерация» — и номер.
    Признание в ярлыке = ноль на ЛЮБОМ круге, дальше второй заход по остальным кадрам."""
    imgs = _fake_vision_seq(monkeypatch, tmp_path,
                            ["1 | ИИ-рисунок кита, по стоп-листу это ИИ-генерация",
                             "3 | печать ФРС на фасаде"])
    got = sw._vision_pick(imgs, "тело", "Bitcoin", "key")
    assert got is not None and got[0] == imgs[2]
    assert "второго круга" in sw.LAST_COVER_NOTE


def test_number_without_label_is_not_a_choice(monkeypatch, tmp_path):
    """Живой ответ 07.09: «1 |» без описания — и код взял маскот издания как обложку. Ярлык нужен и
    журналу анти-повтора, так что номер без ярлыка = сбой формата, а не выбор."""
    imgs = _fake_vision_seq(monkeypatch, tmp_path, ["1 |", "3 | фасад Citi с вывеской"])
    got = sw._vision_pick(imgs, "тело", "Citi", "key")
    assert got is not None and got[0] == imgs[2] and got[1] == "фасад Citi с вывеской"


def test_camera_shot_beats_drawing_is_in_the_prompt():
    """Ступень 0 «снято камерой бьёт нарисованное» — из провала 07.09 (3D-лого Ethereum, маскот)."""
    r = sw._cover_rules()
    assert "СНЯТО КАМЕРОЙ БЬЁТ НАРИСОВАННОЕ" in r


def test_mascot_outlets_are_dropped_when_alternatives_exist(monkeypatch, tmp_path):
    """Cointelegraph иллюстрирует всё своим маскотом — к поводу он не относится по построению.
    Среди 23 принятых обложек таких нет ни одной, а судья на них ловится."""
    _cover_to_tmp(monkeypatch, tmp_path)
    _no_subject_search(monkeypatch)
    made = []
    for i in range(2):
        q = tmp_path / f"m{i}.jpg"
        q.write_bytes(b"\xff\xd8" + b"0" * 100)
        monkeypatch.setitem(sw.source_media.fetch._ORIG_RATIO, str(q), 1.78)
        made.append(q)
    pages = ["https://cointelegraph.com/news/x", "https://www.theblock.co/news/y"]
    monkeypatch.setattr(sw.source_media, "fetch_source_images",
                        lambda url, name="scope": [made[0] if "cointelegraph" in url else made[1]])
    monkeypatch.setattr(sw.source_media, "frame_fingerprint", lambda p: str(p))
    monkeypatch.setattr(sw.source_media, "looks_same", lambda a, b: a == b)
    seen = {}
    monkeypatch.setattr(sw, "_vision_pick",
                        lambda imgs, *a, **k: seen.update(pool=list(imgs)) or (imgs[0], "кадр"))
    sw._attach_media(pages, "тело", "субъект", "k")
    assert seen["pool"] == [made[1]], "маскот не должен доходить до судьи при живой альтернативе"
    assert "мультяшные шапки отсеяны: 1" in sw.LAST_POOL_NOTE


def test_mascot_is_kept_if_it_is_all_there_is(monkeypatch, tmp_path):
    """Обложка обязана быть: единственный кандидат не выбрасываем, даже если это маскот."""
    _cover_to_tmp(monkeypatch, tmp_path)
    _no_subject_search(monkeypatch)
    q = tmp_path / "only.jpg"
    q.write_bytes(b"\xff\xd8" + b"0" * 100)
    monkeypatch.setitem(sw.source_media.fetch._ORIG_RATIO, str(q), 1.78)
    monkeypatch.setattr(sw.source_media, "fetch_source_images", lambda url, name="scope": [q])
    monkeypatch.setattr(sw.source_media, "frame_fingerprint", lambda p: str(p))
    monkeypatch.setattr(sw.source_media, "looks_same", lambda a, b: a == b)
    monkeypatch.setattr(sw, "_vision_pick", lambda imgs, *a, **k: (imgs[0], "кадр"))
    assert sw._attach_media(["https://cointelegraph.com/news/x"], "тело", "субъект", "k")


def test_small_frames_dropped_when_sharp_ones_exist(monkeypatch, tmp_path):
    """Владелец 07.09: «качество картинок должно быть выше среднего — высокое». Пол 460 это
    минимум, чтобы не остаться без обложки; ориентир — медиана канала 1024."""
    _cover_to_tmp(monkeypatch, tmp_path)
    _no_subject_search(monkeypatch)
    made = []
    for i, side in enumerate((600, 1400, 500)):
        q = tmp_path / f"q{i}.jpg"
        q.write_bytes(b"\xff\xd8" + b"0" * 100)
        monkeypatch.setitem(sw.source_media.fetch._ORIG_RATIO, str(q), 1.78)
        monkeypatch.setitem(sw.source_media.fetch._LONG_SIDE, str(q), side)
        made.append(q)
    monkeypatch.setattr(sw.source_media, "fetch_source_images", lambda url, name="scope": list(made))
    monkeypatch.setattr(sw.source_media, "frame_fingerprint", lambda p: str(p))
    monkeypatch.setattr(sw.source_media, "looks_same", lambda a, b: a == b)
    seen = {}
    monkeypatch.setattr(sw, "_vision_pick",
                        lambda imgs, *a, **k: seen.update(pool=list(imgs)) or (imgs[0], "кадр"))
    sw._attach_media(["https://a.com/x"], "тело", "субъект", "k")
    assert seen["pool"] == [made[1]], "мелкие кадры не должны доходить до судьи при наличии крупных"
    assert "мелкие кадры отсеяны: 2" in sw.LAST_POOL_NOTE


def test_single_small_frame_is_still_used(monkeypatch, tmp_path):
    """Единственный мелкий кадр остаётся: #440 вышел в канал в 499x281. Обложка обязана быть."""
    _cover_to_tmp(monkeypatch, tmp_path)
    _no_subject_search(monkeypatch)
    q = tmp_path / "small.jpg"
    q.write_bytes(b"\xff\xd8" + b"0" * 100)
    monkeypatch.setitem(sw.source_media.fetch._ORIG_RATIO, str(q), 1.78)
    monkeypatch.setitem(sw.source_media.fetch._LONG_SIDE, str(q), 500)
    monkeypatch.setattr(sw.source_media, "fetch_source_images", lambda url, name="scope": [q])
    monkeypatch.setattr(sw.source_media, "frame_fingerprint", lambda p: str(p))
    monkeypatch.setattr(sw.source_media, "looks_same", lambda a, b: a == b)
    monkeypatch.setattr(sw, "_vision_pick", lambda imgs, *a, **k: (imgs[0], "кадр"))
    assert sw._attach_media(["https://a.com/x"], "тело", "субъект", "k")
