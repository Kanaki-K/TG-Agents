"""Бэкстоп длины scope (scope_writer._enforce_scope_len) — последний рубеж, не основной резчик.

Переработка 31.07: длину знали СЕМЬ мест (линтер, этот бэкстоп, промпты TASK/FIX/POLISH, envelope судьи
мыслей, резчик судьи финала) — число стояло в девяти строках, и правка в одном месте не доезжала до
остальных; так 29.07 и получился обрубок. Теперь число ОДНО: creator_tools.SCOPE_TOTAL_CAP, все читают
оттуда. Основной резчик — сам автор по замечанию линтера; этот проход срабатывает, только если он
проигнорил. Запуск: python -m pytest tests/test_scope_length.py"""
from __future__ import annotations

from core import creator_tools
from core import scope_writer as sw

CAP = creator_tools.SCOPE_TOTAL_CAP
FOOTER = "🖥 Канал | ▶️ Медиа | 🥸 Мемы | 📱 Notion"


def _n(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _post(n_mids: int, para_len: int = 180) -> str:
    head = "**Заголовок поста один**"
    mids = ["M" * para_len for _ in range(n_mids)]
    return "\n\n".join([head] + mids + [FOOTER])


def test_single_source_of_length():
    # число живёт в ОДНОМ месте; бэкстоп берёт его оттуда, своей копии не держит
    assert sw._enforce_scope_len.__defaults__ == (0,)      # 0 = «взять из creator_tools»
    assert CAP == creator_tools.SCOPE_BODY_MAX + creator_tools.SCOPE_FOOTER_LEN + 20


def test_noop_under_cap():
    t = "**Заголовок**\n\nкороткое тело\n\n" + FOOTER
    assert sw._enforce_scope_len(t) == t


def test_target_length_survives():
    # пост в целевом коридоре (тело ~950 — ориентир владельца) НЕ режется, иначе это баг «обрубка»
    t = _post(5, 190)
    assert creator_tools.SCOPE_BODY_MIN < _n(t.partition("[[SPLIT]]")[0]) <= CAP
    assert sw._enforce_scope_len(t) == t


def test_trims_over_cap_keeps_head_and_footer():
    t = _post(9, 180)
    assert _n(t.partition("[[SPLIT]]")[0]) > CAP
    out = sw._enforce_scope_len(t)
    assert _n(out.partition("[[SPLIT]]")[0]) <= CAP        # влезли
    assert out.split("\n\n")[0] == "**Заголовок поста один**"   # заголовок цел
    assert out.rstrip().endswith(FOOTER)                   # футер (ссылки) цел


def test_keeps_split_and_media_tail():
    # медиа-мету после [[SPLIT]] не трогаем — её парсит пайплайн для обложки
    t = _post(9, 180) + "\n[[SPLIT]]\n[[MEDIA_SRC]] https://a.com/x"
    out = sw._enforce_scope_len(t)
    assert "[[SPLIT]]" in out and "https://a.com/x" in out
    assert _n(out.partition("[[SPLIT]]")[0]) <= CAP


def test_does_not_empty_minimal_post():
    # заголовок + 1 абзац + футер, но тело больше потолка — НЕ опустошаем («пост обязан быть»):
    # режем ЦЕЛЫМИ абзацами, последний содержательный не трогаем — длинный пост лучше пустого
    t = "**Заголовок**\n\n" + ("M" * (CAP + 200)) + "\n\n" + FOOTER
    assert sw._enforce_scope_len(t) == t
