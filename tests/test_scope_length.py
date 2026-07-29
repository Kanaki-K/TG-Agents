"""Код-гейт длины scope (scope_writer._enforce_scope_len) — детерминированный предохранитель.

Урок 24.07: длину не резал НИКТО (writer «тема глубокая», 2FA «только факты», редактор «только
стиль») → посты раздувались до 1300–1770 при формате 800–1000. Основной резчик теперь polish;
это — БЭКСТОП на случай, если модель проигнорит промпт. Запуск: python -m pytest tests/test_scope_length.py"""
from __future__ import annotations

from core import scope_writer as sw

FOOTER = "🖥 Канал | ▶️ Медиа | 🥸 Мемы | 📱 Notion"


def _n(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _post(n_mids: int, para_len: int = 180) -> str:
    head = "**Заголовок поста один**"
    mids = ["M" * para_len for _ in range(n_mids)]
    return "\n\n".join([head] + mids + [FOOTER])


def test_noop_under_cap():
    # тело ≤1000 — не трогаем вовсе
    t = "**Заголовок**\n\nкороткое тело\n\n" + FOOTER
    assert sw._enforce_scope_len(t) == t


def test_trims_over_cap_keeps_head_and_footer():
    t = _post(8, 180)                                   # тело сильно >1150
    assert _n(t.partition("[[SPLIT]]")[0]) > 1150
    out = sw._enforce_scope_len(t)
    assert _n(out.partition("[[SPLIT]]")[0]) <= 1150     # влезли
    assert out.split("\n\n")[0] == "**Заголовок поста один**"  # заголовок цел
    assert out.rstrip().endswith(FOOTER)                 # футер (ссылки) цел


def test_keeps_split_and_media_tail():
    # медиа-мету после [[SPLIT]] не трогаем (её парсит пайплайн для обложки)
    t = _post(8, 180) + "\n[[SPLIT]]\n[[MEDIA_SRC]] https://a.com/x"
    out = sw._enforce_scope_len(t)
    assert "[[SPLIT]]" in out and "https://a.com/x" in out
    assert _n(out.partition("[[SPLIT]]")[0]) <= 1150


def test_does_not_empty_minimal_post():
    # заголовок + 1 абзац + футер, но тело >1000 — НЕ опустошаем (страховка «пост обязан быть»):
    # режем ЦЕЛЫМИ абзацами, а последний содержательный абзац не трогаем — лучше длинный пост, чем пустой
    t = "**Заголовок**\n\n" + ("M" * 1200) + "\n\n" + FOOTER
    assert sw._enforce_scope_len(t) == t
