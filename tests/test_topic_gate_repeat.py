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
