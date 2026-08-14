"""Футер короткого поста — ВОЗВРАЩАЕТСЯ КОДОМ, а не просьбой в мануале (баг 14.08).

14.08 пост уехал в отложку канала вообще без футера: проверка футера жила ТОЛЬКО в флагман-ветке
линтера, у короткого её не было НИКОГДА. Заметил это владелец, а не завод. Второй, невидимый ущерб:
`_finale_para` ищет финал ПЕРЕД футером — без футера судья формы финала (§4.5) молча выключался.
Сторожим оба места + «воздух» абзацев (владелец 14.08 переразбил плотный пост руками).
Запуск: python -m pytest tests/test_scope_footer.py
"""
from __future__ import annotations

from core import creator_tools as ct

FOOTER = ("🖥 [Канал](https://t.me/+AAA) | ▶️ [Медиа](https://linktr.ee/x) | "
          "🥸 [Мемы](https://t.me/+BBB) | 📱 [Notion](https://www.notion.so/x)")

POST_NO_FOOTER = """**🌐 Мост в крипту для азиатских капиталов**

13 августа **B2C2** взял старшим советником **Джейсона Лая**

Само по себе назначение советника - мелочь. Важно, откуда и куда идёт человек

Активы под управлением в Азии дойдут до **99 трлн$** к 2029 году

Умные деньги не заходят на хаях под фанфары. Они строят инфраструктуру, когда всем скучно"""


def _mock_footer(monkeypatch, tmp_path, text=FOOTER):
    p = tmp_path / "footer.md"
    p.write_text("# Канон-футер\n\n" + text + "\n", encoding="utf-8")
    monkeypatch.setattr(ct, "FOOTER_FILE", p)
    return p


def test_canon_footer_reads_memory(monkeypatch, tmp_path):
    _mock_footer(monkeypatch, tmp_path)
    assert ct.canon_footer() == FOOTER


def test_canon_footer_missing_file_is_soft(monkeypatch, tmp_path):
    monkeypatch.setattr(ct, "FOOTER_FILE", tmp_path / "нет-такого.md")
    assert ct.canon_footer() == ""       # мягко: линтер тогда просто ругнётся текстом


def test_lint_restores_lost_footer(monkeypatch, tmp_path):
    _mock_footer(monkeypatch, tmp_path)
    clean, warns = ct._lint(POST_NO_FOOTER, "scope")
    assert clean.rstrip().endswith(FOOTER), "футер обязан вернуться ПОСЛЕДНИМ блоком"
    assert any("ФУТЕРА НЕ БЫЛО" in w for w in warns)


def test_lint_keeps_existing_footer_once(monkeypatch, tmp_path):
    _mock_footer(monkeypatch, tmp_path)
    clean, warns = ct._lint(POST_NO_FOOTER + "\n\n" + FOOTER, "scope")
    assert clean.count("linktr") == 1, "второй футер дописывать нельзя"
    assert not any("ФУТЕРА НЕ БЫЛО" in w for w in warns)


def test_lint_footer_goes_before_meta(monkeypatch, tmp_path):
    """Мету обложки ([[SPLIT]] …) футер не перепрыгивает — иначе она уедет в канал как текст."""
    _mock_footer(monkeypatch, tmp_path)
    clean, _ = ct._lint(POST_NO_FOOTER + "\n\n[[SPLIT]]\n[[MEDIA_SRC]] https://example.com", "scope")
    assert clean.index(FOOTER) < clean.index("[[SPLIT]]")


def test_finale_para_falls_back_without_footer():
    """Без футера финал = последний абзац: одна потеря не должна гасить судью САМОЙ дорогой строки."""
    assert ct._finale_para(POST_NO_FOOTER).startswith("Умные деньги")


def test_finale_para_prefers_para_before_footer():
    assert ct._finale_para(POST_NO_FOOTER + "\n\n" + FOOTER).startswith("Умные деньги")


# ── ВОЗДУХ: пост-кирпич ловим по МЕДИАНЕ абзаца (замер принятых: 90-175) ─────────────────────────

def _post(paras):
    return "**🌐 Заголовок поста про рынок**\n\n" + "\n\n".join(paras) + "\n\n" + FOOTER


def test_dense_post_warns_about_air():
    dense = ["Слово " * 40] * 5            # ~240 знаков каждый абзац, ни один не выше порога 280
    warns = ct._lint(_post(dense), "scope")[1]
    assert any("МАЛО ВОЗДУХА" in w for w in warns)


def test_airy_post_is_silent():
    airy = ["Короткая мысль про рынок и деньги"] * 6
    warns = ct._lint(_post(airy), "scope")[1]
    assert not any("МАЛО ВОЗДУХА" in w for w in warns)


def test_pipe_metaphor_banned():
    """«труба/трубы» — тот же костыль, что «рельсы» (в канале за 319 постов встретилось 1 раз)."""
    warns = ct._lint(_post(["Таким семьям нужна не консультация, а труба под крупные заявки"]), "scope")[1]
    assert any("БАН-метафора" in w and "труб" in w for w in warns)
