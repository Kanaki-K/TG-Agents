"""Бэкстоп длины scope (scope_writer._enforce_scope_len) — последний рубеж, не основной резчик.

Переработка 31.07: длину знали СЕМЬ мест (линтер, этот бэкстоп, промпты TASK/FIX/POLISH, envelope судьи
мыслей, резчик судьи финала) — число стояло в девяти строках, и правка в одном месте не доезжала до
остальных; так 29.07 и получился обрубок. Теперь числа живут ОДНИМ блоком в creator_tools, все читают
оттуда. Основной резчик — сам автор по замечанию линтера; этот проход срабатывает, только если он
проигнорил.

Правка 10.08 развела ДВА ЧИСЛА: цель формата (SCOPE_TOTAL_CAP) и раздувание (SCOPE_BLOAT_CAP) —
между ними жил зазор «купленной длины» для постов-инструкций и предысторий.

Правка 10.09.2026 (v2.1) зазор УБРАЛА по решению владельца: «для скоупа 1500 максимально». Теперь
CAP == BLOAT == 1500, и потолок стал настоящим пределом, а не советом. Купить длину смыслом
по-прежнему можно — но не за счёт времени читателя. Нижняя граница 1000 (тело 770): ниже это
телеграмма, а не разбор.
Плюс: резчик сносит абзац НЕ перед футером — финал-кикер самая защищаемая строка формата.
Запуск: python -m pytest tests/test_scope_length.py"""
from __future__ import annotations

from core import creator_tools
from core import scope_writer as sw

CAP = creator_tools.SCOPE_TOTAL_CAP
BLOAT = creator_tools.SCOPE_BLOAT_CAP
FOOTER = "🖥 Канал | ▶️ Медиа | 🥸 Мемы | 📱 Notion"


def _n(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _post(n_mids: int, para_len: int = 180) -> str:
    head = "**Заголовок поста один**"
    mids = ["M" * para_len for _ in range(n_mids)]
    return "\n\n".join([head] + mids + [FOOTER])


def _post_between(lo: int, hi: int, n_mids: int = 7) -> str:
    """Пост, попадающий в коридор (lo, hi) — размер абзаца считаем ОТ ПОРОГОВ, а не магическим числом.
    Пороги за август менялись трижды (1250 → 1500 → 1350), и фикстура `_post(7, 180)` при каждой
    правке падала, хотя резчик работал верно (падение 20.08)."""
    para = max(1, ((lo + hi) // 2 - _n(_post(n_mids, 0))) // n_mids)
    return _post(n_mids, para)


def test_single_source_of_length():
    # числа живут в ОДНОМ месте; бэкстоп берёт своё оттуда, копии здесь не держит
    assert sw._enforce_scope_len.__defaults__ == (0,)      # 0 = «взять из creator_tools»
    assert CAP == creator_tools.SCOPE_BODY_MAX + creator_tools.SCOPE_FOOTER_LEN + 20
    # v2.1: цель и раздувание СОВПАЛИ (решение владельца — 1500 предел). Раньше требовался зазор,
    # чтобы «длинновато» не лечилось ампутацией; теперь от ампутации защищает не зазор, а правило
    # «режем структурно» — лишний пример и повтор, а не абзац под нож.
    assert BLOAT == CAP


def test_noop_under_cap():
    t = "**Заголовок**\n\nкороткое тело\n\n" + FOOTER
    assert sw._enforce_scope_len(t) == t


def test_target_length_survives():
    # пост в целевом коридоре (тело ~950 — ориентир владельца) НЕ режется, иначе это баг «обрубка»
    t = _post(5, 190)
    assert creator_tools.SCOPE_BODY_MIN < _n(t.partition("[[SPLIT]]")[0]) <= CAP
    assert sw._enforce_scope_len(t) == t


def test_cap_and_bloat_are_one_number_now():
    """v2.1: зазор «купленной длины» убран решением владельца — 1500 это предел, а не ориентир.
    Тест держит именно это: если кто-то вернёт зазор, тесты скажут раньше, чем канал получит
    полуторатысячные посты обратно."""
    assert CAP == BLOAT == 1500
    # 16.09 (владелец): формат 800-1500. Ниже 800 — телеграмма, а не разбор; выше 1500 — недофлагман
    assert creator_tools.SCOPE_TOTAL_MIN == 800


def test_trims_over_bloat_keeps_head_and_footer():
    t = _post(9, 180)
    assert _n(t.partition("[[SPLIT]]")[0]) > BLOAT
    out = sw._enforce_scope_len(t)
    assert _n(out.partition("[[SPLIT]]")[0]) <= BLOAT      # влезли
    assert out.split("\n\n")[0] == "**Заголовок поста один**"   # заголовок цел
    assert out.rstrip().endswith(FOOTER)                   # футер (ссылки) цел


def test_kicker_and_lead_survive_the_trim():
    """Резчик сносил «абзац прямо перед футером» — а это ФИНАЛ-кикер (§4.5), строка, ради которой
    держат отдельного судью формы и которую владелец правит руками 10+ сессий. То есть предохранитель
    длины первым делом убивал то, что защищают все остальные механизмы. Режем НАД финалом."""
    head = "**Заголовок поста один**"
    lead = "ЛИД " + "L" * 200
    mids = ["СЕРЕДИНА%d " % i + "M" * 200 for i in range(7)]
    kicker = "ФИНАЛ, который стоит сам"
    t = "\n\n".join([head, lead] + mids + [kicker, FOOTER])
    assert _n(t) > BLOAT
    out = sw._enforce_scope_len(t)
    assert _n(out) <= BLOAT
    assert out.split("\n\n")[0] == head                    # заголовок цел
    assert lead in out                                     # лид оплачивает заголовок — цел
    assert kicker in out                                   # ФИНАЛ цел
    assert out.rstrip().endswith(FOOTER)
    assert sum(1 for p in out.split("\n\n") if p.startswith("СЕРЕДИНА")) < len(mids)  # резали середину


def test_keeps_split_and_media_tail():
    # медиа-мету после [[SPLIT]] не трогаем — её парсит пайплайн для обложки
    t = _post(9, 180) + "\n[[SPLIT]]\n[[MEDIA_SRC]] https://a.com/x"
    out = sw._enforce_scope_len(t)
    assert "[[SPLIT]]" in out and "https://a.com/x" in out
    assert _n(out.partition("[[SPLIT]]")[0]) <= BLOAT


def test_does_not_empty_minimal_post():
    # заголовок + 1 абзац + футер, но тело больше порога — НЕ опустошаем («пост обязан быть»):
    # режем ЦЕЛЫМИ абзацами, а резать тут нечего — длинный пост лучше пустого
    t = "**Заголовок**\n\n" + ("M" * (BLOAT + 200)) + "\n\n" + FOOTER
    assert sw._enforce_scope_len(t) == t


def test_advice_post_is_never_blindly_trimmed():
    """Резчик выкидывает целые абзацы — а в посте-инструкции хвост это «кого касается» и
    «что не спасает». Срезать их ради полусотни знаков = отправить человека делать бесполезное
    действие. Случай Coldcard 31.07: неполный список устройств стоил бы читателю ключей."""
    tail = "Кого касается: Mk3, Mk4, Mk5 и Q\n\nмигрируйте на новый seed - обновление его не спасает"
    t = "\n\n".join(["**Заголовок поста один**"] + ["M" * 200 for _ in range(9)] + [tail, FOOTER])
    assert _n(t.partition("[[SPLIT]]")[0]) > BLOAT
    out = sw._enforce_scope_len(t)
    assert out == t                                   # не тронут
    assert "Кого касается" in out and "не спасает" in out


# ── ПЕРЕРАБОТКА 12.09.2026: допуск + запрет резать несущее ───────────────────────────────────────
# Живой провал: пост вышел на 1501 знак при потолке 1500, и резчик за ОДИН лишний знак снёс абзац на
# 187 знаков — единственный, который связывал повод с читателем и подводил к кикеру. Владелец
# забраковал пост целиком («финал дерьмище, пользы 0, не ясно про что пересказать»). Ниже — тесты на
# оба класса: арифметику допуска и неприкосновенность несущих костей.
TOL = creator_tools.SCOPE_LEN_TOLERANCE


def _post_over(over: int) -> str:
    """Пост ровно на `over` знаков выше потолка — размер добора считаем от порогов, не магией."""
    base = ["**Заголовок поста один**", "ЛИД " + "L" * 200]
    mids = ["СЕРЕДИНА%d " % i + "M" * 200 for i in range(4)]
    kicker = "ФИНАЛ, который стоит сам"
    t = "\n\n".join(base + mids + [kicker, FOOTER])
    pad = BLOAT + over - _n(t)
    assert pad > 0, "фикстура: добор должен быть положительным"
    mids[-1] += "X" * pad
    return "\n\n".join(base + mids + [kicker, FOOTER])


def test_one_char_over_is_not_amputated():
    """Случай 12.09 дословно: 1 знак перебора не стоит абзаца. Абзац канала — 80-270 знаков, то есть
    ампутация платит смыслом в сотню знаков за недобор в один."""
    t = _post_over(1)
    assert _n(t) == BLOAT + 1
    assert sw._enforce_scope_len(t) == t
    assert "не резал" in sw.LAST_LEN_ACTION


def test_tolerance_edge_is_exact():
    assert sw._enforce_scope_len(_post_over(TOL)) == _post_over(TOL)     # в допуске — не трогаем
    over = _post_over(TOL + 1)
    assert sw._enforce_scope_len(over) != over                            # за допуском — режем
    assert "срезал" in sw.LAST_LEN_ACTION                                 # и говорим об этом в панель


def test_payoff_paragraph_is_never_cut():
    """Кость 6 «что это значит для читателя» — то, ради чего пост существует (§1, §7.45). Резчик
    12.09 снёс именно её, потому что она стоит перед финалом."""
    head, lead = "**Заголовок поста один**", "ЛИД " + "L" * 200
    mids = ["СЕРЕДИНА%d " % i + "M" * 220 for i in range(5)]
    payoff = "И вот что это значит для холдера: " + "P" * 200
    kicker = "ФИНАЛ, который стоит сам"
    t = "\n\n".join([head, lead] + mids + [payoff, kicker, FOOTER])
    assert _n(t) > BLOAT + TOL
    out = sw._enforce_scope_len(t)
    assert payoff in out                                  # пейофф цел
    assert kicker in out and lead in out and out.split("\n\n")[0] == head
    assert sum(1 for x in out.split("\n\n") if x.startswith("СЕРЕДИНА")) < len(mids)


def test_finale_setup_survives():
    """Абзац ПРЯМО над кикером — его подводка. Снеси её, и финал повиснет: ровно этим и развалился
    пост 12.09 («одолженное лицо» без предыдущего абзаца читается как обрубок)."""
    head, lead = "**Заголовок поста один**", "ЛИД " + "L" * 200
    mids = ["СЕРЕДИНА%d " % i + "M" * 220 for i in range(5)]
    setup = "ПОДВОДКА к финалу, на ней он и держится " + "S" * 180
    kicker = "ФИНАЛ, который стоит сам"
    t = "\n\n".join([head, lead] + mids + [setup, kicker, FOOTER])
    assert _n(t) > BLOAT + TOL
    out = sw._enforce_scope_len(t)
    assert setup in out and kicker in out


def test_nothing_safe_to_cut_keeps_post_long():
    """Резать нечего без потери несущего → пост остаётся длинным, а не калечится. «Пост обязан быть»
    сильнее потолка, но владелец об этом узнаёт из панели."""
    head, lead = "**Заголовок поста один**", "ЛИД " + "L" * 300
    kicker = "ФИНАЛ сам по себе"
    # размер добираем ОТ ПОРОГА, а не магическим числом (те же грабли, что у _post_between 20.08)
    pad = (BLOAT + TOL + 60 - _n("\n\n".join([head, lead, "", "", kicker, FOOTER]))) // 2
    payoff = "Что это значит для держателя: " + "P" * pad
    setup = "ПОДВОДКА " + "S" * pad
    t = "\n\n".join([head, lead, payoff, setup, kicker, FOOTER])
    assert _n(t) > BLOAT + TOL
    out = sw._enforce_scope_len(t)
    assert out == t
    assert "резать нечего" in sw.LAST_LEN_ACTION
