"""ОБРАЩЕНИЕ, ЛОЖНАЯ ОТСЫЛКА И ПОВТОР ВЫВОДА (16.09.2026) — правки владельца по посту про отток ETF.

ЗАЧЕМ. Пост 16.09 владелец забраковал четырьмя претензиями, и каждая — дыра в проверках:
  1. «пост почему-то написан на ТЫ, когда всё пишется на вы» — правило «Вы» стоит в своде с v2
     (10.09), а кода под ним не было НИКОГДА (проверено по всей истории репозитория);
  2. «"Вот тебе и ответ" — а какой вопрос нахуй был» — отсылка к вопросу, которого в посте нет;
  3. «"Про сам биткоин - тишина" — притянуто за уши, биткоин не относится к теме»;
  4. «"приток в ETF - плохая опора" — миллион раз повторялось на канале».
1 и 2 ловятся детерминированно (здесь), 3 и 4 — редактором канала (echo_flags), он же ловит пятую:
«буквально вчера был флагман про кларити тоже… я блять как новостник уже».

Запуск: python -m pytest tests/test_scope_address_and_echo.py"""
from __future__ import annotations

import inspect

import run_pipeline as rp
from core import creator_tools as ct, scope_writer

BAD = """**📉 Спрос, который развернулся за сутки на одном заголовке**

За тот же день из биткоин-ETF вышло **450 млн$** - самый тяжёлый отток с июня

Вот тебе и ответ. Спрос через ETF привыкли считать фундаментом

Для того, кто берёт биткоин вдолгую, это ориентир

🖥 [Канал](https://t.me/x) | ▶️ [Медиа](https://linktr.ee/x)
"""


def _warns(text: str) -> list:
    return ct._lint(text, kind="scope")[1]


# ── обращение на «ты» ───────────────────────────────────────────────────────────────────────────

def test_real_defect_16_09_is_caught():
    assert any("ТЫ" in w for w in _warns(BAD)), "«Вот тебе и ответ» снова уехало бы в канал"


def test_all_pronoun_forms():
    for form in ("тебе", "тебя", "твой", "твоя", "твои", "тобой", "твоего", "твою"):
        assert ct._TY_ADDRESS.search(f"это {form} дело"), form


def test_no_false_hits_inside_words():
    """«ты» внутри слова — не обращение: статьи, открытый, тысяча, быты."""
    for word in ("статьи", "открытый", "тысяча", "закрытый", "тыл"):
        assert not ct._TY_ADDRESS.search(word), word


def test_quoted_speech_is_allowed():
    """Цитата с «ты» законна и встречалась у автора (#483: «докажи, что ты не ценная бумага»)."""
    quoted = BAD.replace("Вот тебе и ответ.", 'Пять лет говорили "докажи, что ты не бумага".')
    assert not any("ТЫ" in w for w in _warns(quoted))


def test_channel_history_after_the_rule_is_clean():
    """Замер: на постах, вышедших ПОСЛЕ принятия правила 10.09, чек не срабатывает ни разу."""
    import json
    from core import config
    posts = json.load(open(config.ROOT / "data" / "channel_posts.json", encoding="utf-8"))
    fresh = [p for p in posts if p.get("date", "") >= "2026-09-10"]
    assert fresh, "нет постов после 10.09 — замер не на чем сделать"
    for p in fresh:
        t = p.get("text") or ""
        hit = next((m for m in ct._TY_ADDRESS.finditer(t) if t[: m.start()].count('"') % 2 == 0), None)
        assert not hit, f"ложное срабатывание на принятом посте #{p['id']}: «{hit.group(0)}»"


# ── ответ без вопроса ───────────────────────────────────────────────────────────────────────────

def test_false_answer_caught():
    assert any("вопрос" in w.lower() for w in _warns(BAD))


def test_answer_after_a_real_question_is_fine():
    """Вопрос выше есть — отсылка честная, не трогаем."""
    ok = BAD.replace("самый тяжёлый отток с июня", "а что это было?")
    assert not any("вопрос" in w.lower() and "не было" in w for w in _warns(ok))


def test_answer_variants():
    for v in ("Вот тебе и ответ", "Вот и ответ", "Вот вам и ответ", "Вот ответ"):
        assert ct._FALSE_ANSWER.search(v), v


# ── редактор канала: повтор вывода, абзац не по теме, сюжет встык ───────────────────────────────

def test_echo_judge_asks_about_all_three():
    for must in ("ВЫВОД, КОТОРЫЙ УЖЕ ДЕЛАЛИ", "АБЗАЦ НЕ ПРО ТЕМУ", "СЮЖЕТ, КОТОРЫЙ РАЗБИРАЛИ НА ДНЯХ"):
        assert must in scope_writer.ECHO_READ, must


def test_echo_judge_points_but_never_rewrites():
    """Урок 31.07: судью-переписывателя не воскрешаем — редактор только показывает строки."""
    src = inspect.getsource(scope_writer.echo_flags)
    assert "save_draft" not in src, "редактор начал править текст сам — это сняли 31.07"


def test_echo_fix_is_one_round_by_the_author():
    assert "save_draft" in scope_writer.ECHO_FIX
    assert "Мету после" in scope_writer.ECHO_FIX, "мета обязана переписываться под новый вывод"


def test_echo_fails_open_without_digest():
    assert scope_writer.echo_flags(BAD, digest="") == []


def test_echo_wired_into_pipeline():
    src = inspect.getsource(rp._run_pipeline) if hasattr(rp, "_run_pipeline") else ""
    if not src:                                  # имя пайплайна может отличаться — ищем по файлу
        src = open(rp.__file__, encoding="utf-8").read()
    assert "echo_flags" in src and "fix_echo" in src


# ── встык: продолжение сюжета на следующий день ─────────────────────────────────────────────────

def test_continuation_next_day_is_blocked_even_when_declared():
    """«Вчера был флагман про кларити тоже» — честное 🔼 в окне остывания не спасает."""
    from core import topic_gate as tg
    import datetime
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    digest = f"#504 [{yesterday}] Регулирование | CLARITY Act провалился — голосование в Сенате\n"
    v = ("ВЫБРАН: «Сенат завалил CLARITY Act — что это значит для холдера»\n"
         "ПОВТОР: #504\nЧТО НОВОГО: теперь понятно, что закона не будет до конца года\n")
    assert "отлежится" in tg.repeat_problem(v, digest)


def test_continuation_after_cooldown_passes():
    from core import topic_gate as tg
    import datetime
    old = (datetime.date.today() - datetime.timedelta(days=tg.COOLDOWN_DAYS + 3)).isoformat()
    digest = f"#504 [{old}] Регулирование | CLARITY Act провалился — голосование в Сенате\n"
    v = ("ВЫБРАН: «Сенат завалил CLARITY Act — что это значит для холдера»\n"
         "ПОВТОР: #504\nЧТО НОВОГО: теперь понятно, что закона не будет до конца года\n")
    assert tg.repeat_problem(v, digest) == ""


# ── ОБЗОР ТОКЕНА (16.09) ────────────────────────────────────────────────────────────────────────
# Владелец про пост о Venice/VVV: «выглядит, будто я шиллю токен этот, как обзор и его преимущества.
# Пост хороший, но вот контекст не нравится». Вывод у поста был СКЕПТИЧЕСКИЙ — и это не спасло:
# рекламой читается не вердикт, а УСТРОЙСТВО поста, то есть разбор механики одного токена.
# ЗАМЕР 427 постов канала: маркеров токеномики 0 у 359, 1 у 54, 2 у 8. Три и больше — у шести, и все
# шесть ОБУЧАЮЩИЕ («Словарь криптана», «Что такое токеномика»), то есть другой формат. Скоупа с
# разбором токеномики канал не публиковал НИКОГДА; забракованный пост дал 6 маркеров сразу.

_SHILL = """**⚡️ Токен Venice не нужен, чтобы платить Venice**

У платформы есть свой токен VVV. Застейкал - получаешь право чеканить DIEM

Против этого стоит эмиссия около 3 млн в год, а компания направляет часть выручки на выкуп и
сжигание токена. Утилита предложена остальным

🖥 [Канал](https://t.me/x)
"""


def test_token_review_is_caught():
    assert any("ОБЗОР ТОКЕНА" in w for w in _warns(_SHILL)), "шилл-оптика снова уехала бы в канал"


def test_one_or_two_mechanics_are_fine():
    """Это НЕ запрет упоминать токен: одна-две механики по делу канал публиковал 62 раза."""
    ok = _SHILL.replace("Застейкал - получаешь право чеканить DIEM", "Токен нужен только для оплаты")
    ok = ok.replace("выкуп и\nсжигание токена", "обратный поток")
    ok = ok.replace("Утилита предложена остальным", "Остальное решает компания")
    assert not any("ОБЗОР ТОКЕНА" in w for w in _warns(ok))


def test_advice_points_at_the_fix_not_just_the_defect():
    """Замечание обязано говорить, ЧТО делать: перевернуть несущую конструкцию."""
    w = next(x for x in _warns(_SHILL) if "ОБЗОР ТОКЕНА" in x)
    assert "МЕХАНИЗМ" in w and "ПРИМЕР" in w and "заголовка" in w


def test_no_false_hits_on_accepted_scopes():
    """Замер-регресс: ни один принятый скоуп канала не должен получить это замечание."""
    import json
    from core import config
    posts = json.load(open(config.ROOT / "data" / "channel_posts.json", encoding="utf-8"))
    scopes = [p for p in posts
              if p.get("date", "") >= "2026-06-24" and 700 <= len(p.get("text") or "") < 1700]
    assert scopes, "нечего мерить"
    for p in scopes:
        assert not any("ОБЗОР ТОКЕНА" in w for w in _warns(p["text"])), \
            f"ложное срабатывание на принятом посте #{p['id']}"


def test_rule_lives_in_brand_and_manual_too():
    """Линтер ловит после письма; гейт должен отсекать ДО — значит правило нужно и в сводах."""
    from core import config
    brand = (config.ROOT / "memory" / "brand.md").read_text(encoding="utf-8")
    manual = (config.ROOT / "memory" / "scope_manual.md").read_text(encoding="utf-8")
    assert "ОБЗОР ТОКЕНА/ПРОЕКТА" in brand
    assert "обзор токена" in manual, "мёртвый жанр не попал в таблицу свода"


# ── ГЕЙТ ПЕРЕД ОТЛОЖКОЙ (16.09) ─────────────────────────────────────────────────────────────────
# Владелец за день не получил НИ ОДНОГО поста: три прогона уехали в отложку с браком, и каждый раз
# дефект БЫЛ НАЙДЕН линтером. Замечания возвращаются автору, автор их заболтал (класс с 07.08), пост
# всё равно поставился. Совет, который ничего не останавливает, работает до первого спора с моделью.

def test_clean_post_passes_the_gate():
    clean = """**⚡️ Рост сервиса не доходит до тех, кто купил его токен**

Есть короткая проверка для проекта, где рядом с продуктом живёт своя монета: **обязательна ли она**

Venice пишет прямо: платить её монетой **не обязательно**, можно картой. Спроса это не создаёт

Люди с доступом купили долю в бизнесе. Остальным предложили монету

Посмотрите, можно ли пользоваться сервисом, **не покупая его монету**. Можно - выручка к ней не идёт

🖥 [Канал](https://t.me/x) | ▶️ [Медиа](https://linktr.ee/x)
"""
    assert ct.publish_blockers(clean, "scope") == []


def test_token_review_is_blocked_from_scheduling():
    assert ct.publish_blockers(_SHILL, "scope"), "обзор токена снова уехал бы в отложку"


def test_ty_address_is_blocked_from_scheduling():
    assert any("ТЫ" in b for b in ct.publish_blockers(BAD, "scope"))


def test_taste_warnings_do_not_block():
    """Жирный, воздух, ритм — это спор и вкус: там совет уместен, запрет нет."""
    for w in ("якорного жирного МАЛО", "МАЛО ВОЗДУХА", "вывод БЕЗ акцента", "scope длинноват"):
        assert not any(mark in w for mark in ct._PUBLISH_BLOCKERS), w


def test_pipeline_refuses_to_schedule_on_blockers():
    src = open(rp.__file__, encoding="utf-8").read()
    assert "publish_blockers" in src
    assert "В ОТЛОЖКУ НЕ СТАВЛЮ" in src
    i, j = src.index("publish_blockers"), src.index("[3/3] Ставлю в отложенные")
    assert i < j, "гейт обязан стоять ДО постановки в отложку, иначе он бесполезен"
