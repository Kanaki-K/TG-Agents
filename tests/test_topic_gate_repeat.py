"""АНТИ-ПОВТОР V3.1 (16.09.2026): тему 1в1 нельзя — либо другая, либо значительное улучшение.

ЗАЧЕМ. Канал получил ВТОРОЙ пост про сеть Arc у Circle: #472 от 05.08 «Сеть Circle обслуживают те же,
кто в неё вложил деньги» и драфт 16.09 «Сеть для расчётов запустили те, кого она должна сторожить» —
тот же список операторов (BlackRock, Visa, ICE, DTCC), тот же BUIDL, тот же DTCC-клиринг, тот же вывод.
Владелец: «1в1 тему нельзя, только значительное улучшение или другая тема».

ПОЧЕМУ ПРОШЛО. Правило про повтор стояло в контракте гейта дословно — вместе с разбором ПРОШЛОГО дубля
Arc от 05.08 — и не сработало: при слиянии судей 31.07 из v1-дедупа (core/dedup.py) переехал ТЕКСТ, но
не МЕХАНИЗМ. Машинный «СТАТУС: ПОВТОР», останавливавший конвейер, исчез; значки 🆕/🔁 гейт ставил в
разборе, а код их не читал вообще. Тот же класс, что склейка 14.09 и мост 12.09: правило-вопрос не
срабатывает, проверять должен код.

Каждый тест ниже — место, через которое этот дубль прошёл.
Запуск: python -m pytest tests/test_topic_gate_repeat.py"""
from __future__ import annotations

import inspect

import run_pipeline as rp
from core import scope_writer, topic_gate as tg

# Реальная сводка канала: строки собраны из data/post_topics.json + data/channel_posts.json.
DIGEST = (
    "#504 [2026-09-15] Регулирование | Регуляторная ясность пришла — CLARITY Act 14 месяцев спустя\n"
    "#499 [2026-09-09] Институции | Бывший CEO Твиттера строит банк для стейблкоинов — Дорси и расчёты\n"
    "#488 [2026-08-25] Институции | Почему за проданную акцию деньги идут два дня — DTCC и клиринг T+2\n"
    "#472 [2026-08-05] Институции | Инвесторы Circle стали операторами сети — Крупные инвесторы Arc "
    "токена (BlackRock, ICE) одновременно стали операторами сети, создавая конфликт интересов.\n"
    "#466 [2026-07-29] Институции | Старейший банк США сделал блокчейн реестром — BNY Mellon\n"
)

# Повод, который гейт РЕАЛЬНО выбрал 16.09 (формулировка из брифа и вышедшего драфта).
ARC_AGAIN = ("Circle запустила публичный мейннет Arc — блоки производят 11 отобранных институтов "
             "вместо открытых валидаторов")


def _v(choice: str, repeat: str = "нет", whats_new: str = "—") -> str:
    return (f"НАПРАВЛЕНИЕ: 1\nВЫБРАН: «{choice}»\nДАТА ДЕЙСТВИЯ: 16.09.2026\n"
            f"ПОВТОР: {repeat}\nЧТО НОВОГО: {whats_new}\nПОЛЬЗА: проверить сеть одним вопросом\n"
            "СЛАБО: нет\nИСЧЕРПАНО: нет\nОФФ-БРЕНД: нет")


# ── тот самый дубль ─────────────────────────────────────────────────────────────────────────────

def test_real_arc_duplicate_16_09_is_caught():
    """Главный тест: заголовки не совпадают НИ ОДНИМ словом, но это один и тот же пост."""
    problem = tg.repeat_problem(_v(ARC_AGAIN), DIGEST)
    assert problem, "дубль Arc 16.09 снова прошёл бы в канал"
    assert "#472" in problem and "ПОВТОР: нет" in problem


def test_headlines_share_no_words_but_entities_match():
    """ЗАГОЛОВОК — КРЮЧОК, он событие не называет (урок 05.08). Сверяемся по именам участников."""
    pid, date, shared = tg.closest_published(ARC_AGAIN, DIGEST)
    assert (pid, date) == ("472", "2026-08-05")
    assert shared == ["arc", "circle"]


# ── три исхода правила владельца ────────────────────────────────────────────────────────────────

def test_declared_upgrade_passes():
    """🔼 признан честно: гейт назвал #id и что изменилось — код не спорит, решение за гейтом."""
    v = _v(ARC_AGAIN, repeat="#472 05.08.2026",
           whats_new="в августе список операторов был обещанием, теперь в сети лежит BUIDL на 2.87 млрд$")
    assert tg.repeat_problem(v, DIGEST) == ""


def test_upgrade_without_saying_what_changed_is_a_repeat():
    """Признал повтор, но «что нового» не назвал — по правилу это 🔁, а не 🔼 (условие «б»)."""
    problem = tg.repeat_problem(_v(ARC_AGAIN, repeat="#472 05.08.2026"), DIGEST)
    assert "не сказано, что изменилось" in problem


def test_empty_what_changed_variants_do_not_count_as_an_answer():
    """«—», «нет», «стало официально» одним словом — то же молчание, за ответ не считаем."""
    for filler in ("—", "нет", "-", "не применимо", "официально"):
        assert tg.repeat_problem(_v(ARC_AGAIN, repeat="#472", whats_new=filler), DIGEST), filler


def test_different_topic_passes():
    """🆕 другая тема — проверка молчит, лишних пере-выборов не устраиваем."""
    other = "Отток из биткоин-ETF составил 450 млн$ за день — крупнейший с июня"
    assert tg.repeat_problem(_v(other), DIGEST) == ""


# ── точность: ложных срабатываний быть не должно ────────────────────────────────────────────────

def test_one_shared_name_is_not_enough():
    """BlackRock есть в 21 посте канала. Одного общего имени мало — нужно минимум два."""
    assert tg.repeat_problem(_v("BlackRock подал заявку на спотовый ETF по Solana"), DIGEST) == ""


def test_ubiquitous_domain_words_do_not_count():
    """BTC/ETH/AI/DeFi есть почти везде — по ним дубли не считаем."""
    assert tg._entities("BTC и ETH на фоне AI и DeFi") == set()
    assert "circle" in tg._entities("Circle открыла сеть Arc")


def test_cyrillic_acronyms_are_entities():
    """ФРС/ЦБ — тоже имена, а не слова: кириллические аббревиатуры ловим."""
    assert {"фрс", "цб"} <= tg._entities("ФРС и ЦБ приняли решение")


# ── fail-open: анти-повтор не роняет прогон ─────────────────────────────────────────────────────

def test_no_digest_fails_open():
    assert tg.repeat_problem(_v(ARC_AGAIN), "") == ""


def test_empty_choice_is_not_judged_here():
    """Пустой выбор — сбой гейта, его разбирает конвейер, а не эта проверка."""
    assert tg.repeat_problem("ИСЧЕРПАНО: да", DIGEST) == ""


# ── контракт: поля обязаны быть в промпте и разбираться ─────────────────────────────────────────

def test_contract_asks_for_the_two_fields():
    assert "ПОВТОР:" in tg._SYSTEM and "ЧТО НОВОГО:" in tg._SYSTEM


def test_contract_has_three_outcomes():
    assert "🔼" in tg._SYSTEM, "исход «значительное улучшение» из контракта пропал"
    for must in ("1-в-1", "ЗНАЧИТЕЛЬНОЕ УЛУЧШЕНИЕ"):
        assert must in tg._SYSTEM, must


def test_benchmarks_are_marked_as_form_not_topic():
    """#472 стоит в блоке «тип и бренд» эталоном — рядом обязана быть оговорка, иначе гейт снова
    выберет то, за что его хвалят (половина причины дубля 16.09)."""
    assert "ЭТАЛОНЫ ПОКАЗЫВАЮТ ФОРМУ ПОВОДА, А НЕ ТЕМУ" in tg._SYSTEM


def test_parse_repeat_reads_the_fields():
    pid, new = tg.parse_repeat(_v(ARC_AGAIN, "#472 05.08.2026", "сеть из обещания стала живой"))
    assert pid == "472" and new.startswith("сеть из обещания")
    assert tg.parse_repeat(_v(ARC_AGAIN)) == ("", "")


def test_markdown_wrapped_fields_still_read():
    """Модель любит обернуть поле в **болд** — контракт от этого ломаться не должен."""
    v = _v(ARC_AGAIN).replace("ПОВТОР: нет", "**ПОВТОР: #472 05.08.2026**")
    assert tg.parse_repeat(v)[0] == "472"


# ── проводка в конвейер ─────────────────────────────────────────────────────────────────────────

def test_pipeline_has_the_third_safeguard():
    """Предохранитель обязан стоять в выборе темы и давать ОДИН пере-выбор под запретом."""
    src = inspect.getsource(rp._choose_scope_topic)
    assert "repeat_problem" in src and "forbid" in src


def test_second_scouting_round_on_unfixed_repeat():
    """Пере-выбор не помог — Скаут идёт на второй круг, а не публикуем дубль."""
    assert "repeat_problem" in inspect.getsource(rp._topic_shortfall)


def test_writer_gets_the_prior_post_on_upgrade():
    """Условие «в»: 🔼 обязан ОПИРАТЬСЯ на старый пост — значит писатель должен его видеть."""
    assert "prior" in inspect.signature(scope_writer.write).parameters
    src = inspect.getsource(rp._prior_post_note)
    assert "read_post" in src and "ПОВТОРНО НЕ РАЗЖЁВЫВАЙ" in src


def test_prior_note_silent_without_declared_upgrade():
    """Нет заявленного 🔼 — никакой точки отсчёта писателю не идёт (лишний контекст = лишние деньги)."""
    assert rp._prior_post_note(_v(ARC_AGAIN)) == ""


# ── сверка ГОТОВОГО ТЕЛА (16.09): дыра, которую тема не закрывает ───────────────────────────────
# Прогон 16.09 поставил в отложку пост, по сути повторяющий #501 от 11.09: та же средняя цена входа
# 83 000$ от того же Glassnode, та же механика «уровень работает крышей». repeat_problem пропустил
# закономерно — он судит ТЕМУ, а она была абстрактной («слои себестоимости») и дала с #501 одно общее
# имя при пороге два. Совпала не формулировка, а ОПОРНАЯ ЦИФРА.

_D501 = "#501 [{d}] Рынок | Институции поставили крышу — средняя цена входа фондов около 83 000$\n"


def _digest_days_ago(days: int) -> str:
    import datetime
    return _D501.format(d=(datetime.date.today() - datetime.timedelta(days=days)).isoformat())


def test_shared_anchor_number_is_caught():
    body = ("**Биткоин дешевле, чем его покупали крупные держатели**\n\n"
            "Плотный кластер себестоимости сидит в 83 000-86 000$, там же выходят в плюс фонды")
    why = tg.body_repeat_problem(body, _digest_days_ago(5))
    assert "#501" in why and "83000" in why


def test_old_match_is_allowed():
    """Перекличка со старым постом законна — режем только вторую серию подряд."""
    body = "Кластер себестоимости в 83 000$"
    assert tg.body_repeat_problem(body, _digest_days_ago(tg.COOLDOWN_DAYS + 5)) == ""


def test_unrelated_body_passes():
    body = "Логистика слила 67 000 адресов покупателей Trezor — ключи целы, а дверь известна"
    assert tg.body_repeat_problem(body, _digest_days_ago(3)) == ""


def test_small_numbers_are_not_anchors():
    """3%, 11 валидаторов, 2 дня — такие числа есть в каждом посте, дублем они не свидетельствуют."""
    assert tg._big_numbers("минус 3.8% за неделю, 11 институтов, 2 дня") == set()
    assert 83000 in tg._big_numbers("средняя цена 83 000$")


def test_meta_is_not_judged():
    """Мета после [[SPLIT]] не публикуется — судить её нечего."""
    assert tg.body_repeat_problem("[[SPLIT]]\n[[УЗЕЛ]] что-то про 83 000$", _digest_days_ago(2)) == ""


def test_channel_history_has_almost_no_false_hits():
    """Замер: 424 реальных поста против вышедших за 7 дней до них — 1 срабатывание, и то живая пара."""
    import json, datetime
    from core import config
    posts = json.load(open(config.ROOT / "data" / "channel_posts.json", encoding="utf-8"))
    topics = json.load(open(config.ROOT / "data" / "post_topics.json", encoding="utf-8"))
    rows = sorted((p for p in posts if str(p["id"]) in topics), key=lambda p: p["date"])
    hits = 0
    for i, p in enumerate(rows):
        d = datetime.date.fromisoformat(p["date"][:10])
        prev = [q for q in rows[:i]
                if 0 <= (d - datetime.date.fromisoformat(q["date"][:10])).days <= tg.COOLDOWN_DAYS]
        if not prev:
            continue
        lines = []
        for q in prev:
            t = topics[str(q["id"])]
            lines.append(f"#{q['id']} [{q['date'][:10]}] {t.get('theme','—')} | "
                         f"{t.get('title','')} — {t.get('summary','')}")
        real = tg.datetime.date
        tg.datetime.date = type("F", (real,), {"today": classmethod(lambda cls: d)})
        try:
            if tg.body_repeat_problem(p.get("text") or "", "\n".join(lines)):
                hits += 1
        finally:
            tg.datetime.date = real
    assert hits <= 3, f"шумит: {hits} срабатываний на {len(rows)} постах"


# ── ПОВТОР ПОНЯТИЯ, А НЕ СОБЫТИЯ (16.09) ────────────────────────────────────────────────────────
# Владелец: «антиповтор не поймал, что относительно недавно флагман или скоуп ровно про это же писал».
# Третий пост об одном механизме: #482 (флагман 18.08, реализованная цена), #501 (скоуп 11.09, средняя
# цена входа фондов), драфт 16.09 (кластеры себестоимости). Имён собственных они не делят ВООБЩЕ, цифр
# тоже (83 000 против 80 000-88 000) — обе прошлые сетки ищут именно их, поэтому класс был невидим.

def _corpus(*pairs):
    """Мини-канал: (id, дата, текст). Нужен объём, иначе редкость слова не посчитать."""
    filler = [{"id": 900 + i, "date": "2026-07-01",
               "text": f"Обычный пост номер {i} про биржи, комиссии, кошельки и заявки клиентов"}
              for i in range(35)]
    return filler + [{"id": i, "date": d, "text": t} for i, d, t in pairs]


_MEAN_PRICE = ("Реализованная цена показывает себестоимость рынка: средняя цена, по которой "
               "держатели покупали монеты. Средний участник сидит около неё, продавцы выходят в ноль")


def test_same_concept_is_caught_without_names_or_numbers():
    import datetime
    posts = _corpus((482, "2026-08-18", _MEAN_PRICE))
    new = ("Кластеры себестоимости разъехались: средняя цена держателей выше сегодняшней, "
           "средний участник в нуле, продавцы выходят по своей себестоимости")
    why = tg.concept_echo(new, posts, today=datetime.date(2026, 9, 16))
    assert "#482" in why, "повтор понятия снова невидим"
    assert tg._entities(new) & tg._entities(_MEAN_PRICE) == set(), "тест обязан идти БЕЗ общих имён"


def test_other_concept_stays_silent():
    import datetime
    posts = _corpus((482, "2026-08-18", _MEAN_PRICE))
    other = ("Логистический подрядчик слил домашние адреса покупателей аппаратных кошельков, "
             "ключи целы, а физическая безопасность держателя оказалась отдельным риском")
    assert tg.concept_echo(other, posts, today=datetime.date(2026, 9, 16)) == ""


def test_old_concept_is_allowed_back():
    """Окно 8 недель: понятия возвращаются законно, режем только близкий повтор."""
    import datetime
    posts = _corpus((482, "2026-01-10", _MEAN_PRICE))
    assert tg.concept_echo(_MEAN_PRICE, posts, today=datetime.date(2026, 9, 16)) == ""


def test_empty_and_tiny_corpus_fail_open():
    assert tg.concept_echo("", []) == ""
    assert tg.concept_echo(_MEAN_PRICE, [{"id": 1, "date": "2026-09-01", "text": _MEAN_PRICE}]) == ""


def test_real_case_is_caught_on_live_channel():
    """Регресс на живых данных: драфт 16.09 обязан указать на флагман #482."""
    from core import analytics, config
    draft = config.ROOT / "memory" / "drafts" / "2026-09-16-btc-cost-basis-clusters-scope.md"
    if not draft.exists():
        return                                  # драфт мог быть убран владельцем — тест не падает
    import datetime
    why = tg.concept_echo(draft.read_text(encoding="utf-8"), analytics._load_posts(),
                          today=datetime.date(2026, 9, 16))
    assert "#482" in why


def test_wired_into_the_panel_as_a_warning_not_a_gate():
    src = open(rp.__file__, encoding="utf-8").read()
    assert "concept_echo" in src and 'panel["🧠 то же понятие"]' in src
    assert "не блокирую пост" in src, "сверка понятий не должна блокировать: понятия возвращаются"


# ── СУДЬЯ ПОНЯТИЯ ДО ПИСЬМА (16.09) ─────────────────────────────────────────────────────────────
# Гейт ВИДЕЛ в своей сводке обе строки — «#482 Дно рынка определяется средней ценой покупки» и
# «#501 Уровень безубытка ETF работает как сопротивление» — и написал «ПОВТОР: нет». Данные были,
# правило было, последствия не было. Статистикой не добивается: у таких тем нет ни общих имён, ни
# общих цифр. Поэтому узкий судья с машинным ответом + обязательный пере-выбор.

def test_judge_asks_exactly_one_question_with_a_machine_answer():
    assert "ПОВТОР ПОНЯТИЯ:" in tg._CONCEPT_JUDGE
    assert "РЕЧЬ НЕ О СОБЫТИИ" in tg._CONCEPT_JUDGE, "судья обязан отличать механизм от повода"
    assert "Сомневаешься" in tg._CONCEPT_JUDGE, "при сомнении — «нет», ложная тревога стоит круга"


def test_verdict_is_parsed_with_and_without_reason():
    assert tg._CONCEPT_VERDICT_RE.search("ПОВТОР ПОНЯТИЯ: #482 — средняя цена покупки как уровень")
    assert tg._CONCEPT_VERDICT_RE.search("ПОВТОР ПОНЯТИЯ: #482")
    assert not tg._CONCEPT_VERDICT_RE.search("ПОВТОР ПОНЯТИЯ: нет")


def test_judge_fails_open(monkeypatch):
    """Судья — предохранитель, а не единственная опора: сбой не роняет прогон и не блокирует тему."""
    monkeypatch.setattr(tg.llm, "reply", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("сеть")))
    assert tg.concept_repeat("любая тема", digest="#1 [2026-09-01] X | Y — Z") == ""
    assert tg.concept_repeat("", digest="#1 [2026-09-01] X | Y — Z") == ""
    assert tg.concept_repeat("тема", digest="") == ""


def test_judge_reads_the_id_from_a_real_answer(monkeypatch):
    monkeypatch.setattr(tg.llm, "reply",
                        lambda *a, **k: ("ПОВТОР ПОНЯТИЯ: #482 — средняя цена покупки как уровень", []))
    why = tg.concept_repeat("кластеры себестоимости", digest="#482 [2026-08-18] Рынок | дно — средняя цена")
    assert "#482" in why and "средняя цена покупки" in why


def test_no_repeat_answer_passes(monkeypatch):
    monkeypatch.setattr(tg.llm, "reply", lambda *a, **k: ("ПОВТОР ПОНЯТИЯ: нет", []))
    assert tg.concept_repeat("свежая тема", digest="#482 [2026-08-18] Рынок | дно — средняя цена") == ""


def test_pipeline_repicks_instead_of_advising():
    """Совет тут не годится: этот проект игнорирует советы с 31.07. Нужен пере-выбор с запретом."""
    src = inspect.getsource(rp._choose_scope_topic)
    assert "concept_repeat" in src
    assert "forbid_why=concept" in src, "вердикт судьи обязан стать ЗАПРЕТОМ на пере-выборе"
    assert 'panel["🧠 понятие"]' in src


def test_concept_judge_never_costs_a_whole_day():
    """ОТКАТ, ЕСЛИ ЗАМЕНА ХУЖЕ ОТСУТСТВИЯ (16.09).

    Первый живой прогон с судьёй понятия кончился НИЧЕМ: судья снял годную тему, пере-выбор упёрся
    в исчерпанный бриф, конвейер ушёл на второй круг разведки — и поста в этот день не было вовсе.
    $0.44 и ноль постов. Повтор понятия — дефект, но «поста нет» дороже: третий заход на механизм
    читатель хотя бы прочтёт, пустой день не читает никто."""
    src = inspect.getsource(rp._choose_scope_topic)
    assert "_rec0" in src, "исходная тема не запоминается — откатывать будет нечего"
    assert "is_exhausted(verdict) or topic_gate.is_offbrand(verdict)" in src
    assert "возвращаю исходную тему" in src
    i_save = src.index("_rec0, _weak0, _verdict0 = rec, weak, verdict")
    i_back = src.index("rec, weak, verdict = _rec0")
    assert i_save < i_back, "откат обязан идти ПОСЛЕ запоминания"


# ── УЖЕ НАПИСАНО, НО ЕЩЁ НЕ ВЫШЛО (16.09) ───────────────────────────────────────────────────────
# Прогон 16.09 ВТОРОЙ РАЗ ПОДРЯД взял Venice. Гейту показали список «недавно написано», и там прямым
# текстом стоял «⚡️ Токен Venice не нужен, чтобы платить Venice». Он всё равно выбрал Venice.
# Почему не поймал код: repeat_problem и concept_repeat сверяют тему с ВЫШЕДШИМИ постами канала, а
# этот пост в канал не выходил — он в отложке. Список жил просьбой в промпте, как до сегодня жили
# правило «Вы» и повтор понятия. Владелец: «снова про ту же монету».

_RECENT = ["⚡️ Токен Venice не нужен, чтобы платить Venice — Venice, приватный AI-сервис Вурхиса",
           "📊 Главный покупатель биткоина выкупает свои бумаги — Strategy отчиталась в SEC"]


def test_second_post_about_the_same_project_is_caught():
    why = tg.already_written("Инсайдеры Venice взяли долю в бизнесе, рознице монета VVV", _RECENT)
    assert "venice" in why and "не вышедшим" in why


def test_one_shared_name_is_enough_here_unlike_the_channel():
    """Порог здесь ОДНО имя: окно — восемь свежих драфтов, а не 427 постов за год. У канала одно
    общее имя ничего не значит (BlackRock в 21 посте), здесь — почти наверняка та же тема."""
    assert tg.already_written("Strategy купила биткоин на открытом рынке", _RECENT)
    assert tg._REPEAT_MIN_SHARED == 2, "порог сверки С КАНАЛОМ трогать нельзя — там он оправдан"


def test_unrelated_theme_passes():
    assert tg.already_written("Утечка адресов покупателей Trezor у подрядчика", _RECENT) == ""


def test_theme_without_names_passes():
    """У тем-механизмов имён нет вовсе — их ловит concept_repeat, а не эта проверка."""
    assert tg.already_written("Средняя цена покупки работает как уровень", _RECENT) == ""


def test_empty_inputs_fail_open():
    assert tg.already_written("", _RECENT) == ""
    assert tg.already_written("Venice снова", []) == ""


def test_pipeline_repicks_on_already_written():
    src = inspect.getsource(rp._choose_scope_topic)
    assert "already_written" in src and "forbid_why=written" in src
    assert 'panel["📝 уже написано"]' in src
