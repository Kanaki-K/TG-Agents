"""Бэкстоп длины scope (scope_writer._enforce_scope_len) — последний рубеж, не основной резчик.

Переработка 31.07: длину знали СЕМЬ мест (линтер, этот бэкстоп, промпты TASK/FIX/POLISH, envelope судьи
мыслей, резчик судьи финала) — число стояло в девяти строках, и правка в одном месте не доезжала до
остальных; так 29.07 и получился обрубок. Теперь числа живут ОДНИМ блоком в creator_tools, все читают
оттуда. Основной резчик — сам автор по замечанию линтера; этот проход срабатывает, только если он
проигнорил.

Правка 10.08 — ДВА РАЗНЫХ ЧИСЛА вместо одного: цель формата (SCOPE_TOTAL_CAP, совет линтера) и
раздувание (SCOPE_BLOAT_CAP, триггер резчика). Раньше это было одно число, и «на 100 знаков длиннее
цели» лечилось ампутацией — из-за чего писатель заранее выбрасывал объяснение предмета, чтобы влезть.
Плюс: резчик сносил абзац прямо перед футером, то есть ФИНАЛ-кикер — самую защищаемую строку формата.
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


def test_single_source_of_length():
    # числа живут в ОДНОМ месте; бэкстоп берёт своё оттуда, копии здесь не держит
    assert sw._enforce_scope_len.__defaults__ == (0,)      # 0 = «взять из creator_tools»
    assert CAP == creator_tools.SCOPE_BODY_MAX + creator_tools.SCOPE_FOOTER_LEN + 20
    # цель и раздувание — РАЗНЫЕ пороги, иначе «длинновато» снова лечится ампутацией
    assert BLOAT > CAP


def test_noop_under_cap():
    t = "**Заголовок**\n\nкороткое тело\n\n" + FOOTER
    assert sw._enforce_scope_len(t) == t


def test_target_length_survives():
    # пост в целевом коридоре (тело ~950 — ориентир владельца) НЕ режется, иначе это баг «обрубка»
    t = _post(5, 190)
    assert creator_tools.SCOPE_BODY_MIN < _n(t.partition("[[SPLIT]]")[0]) <= CAP
    assert sw._enforce_scope_len(t) == t


def test_over_target_but_not_bloated_is_untouched():
    """Случай 10.08: владелец принял пост на 1599 знаков — длиннее цели, но это не флагман, а
    объяснение предмета спора, без которого пост читался как «интересно, но не понял, в чём проблема».
    Старый порог разрезал бы его. Между целью и раздуванием решает автор, не резчик."""
    t = _post(7, 180)
    assert CAP < _n(t) <= BLOAT
    assert sw._enforce_scope_len(t) == t


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
