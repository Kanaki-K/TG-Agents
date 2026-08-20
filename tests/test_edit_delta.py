"""Замер правок владельца (core/edit_delta) — драфт завода против того, что вышло в канал.

Примеры взяты из РЕАЛЬНОГО замера 20.08 по постам августа, а не выдуманы: так тест заодно
фиксирует, что классификатор понимает настоящие правки владельца, а не лабораторные.
Запуск: python -m pytest tests/test_edit_delta.py
"""
from __future__ import annotations

from core import edit_delta

_FOOT = "🖥 Канал | ▶️ Медиа | 🥸 Мемы | 📱 Notion"


def _post(*paras: str) -> str:
    return "\n\n".join([*paras, _FOOT])


def test_identical_is_clean():
    t = _post("**📊 Заголовок поста**", "Первый абзац с фактом и цифрой 2.4 млн", "Финал стоит сам")
    r = edit_delta.compare(t, t)
    assert r["coverage"] == 1.0 and r["clean"] is True and r["tags"] == []


def test_footer_difference_is_not_an_edit():
    """Футер режется и возвращается КОДОМ (линтер 14.08) — правкой владельца он не является."""
    d = "**📊 Заголовок**\n\nТело поста\n\n🖥 [Канал](https://t.me/x) | 📱 [Notion](https://n.so/x)"
    p = "**📊 Заголовок**\n\nТело поста\n\n" + _FOOT
    assert edit_delta.compare(d, p)["clean"] is True


def test_removed_block():
    d = _post("**📊 Заголовок**", "Первый абзац", "Два режима: Guard Mode и Beast Mode", "Финал")
    p = _post("**📊 Заголовок**", "Первый абзац", "Финал")
    r = edit_delta.compare(d, p)
    assert r["removed"] == 1 and any(t.startswith("снял блок") for t in r["tags"])


def test_added_block():
    """Владелец дописал фактуру — 07.08 добавил «у МетаМаск более 100 млн пользователей»."""
    d = _post("**📊 Заголовок**", "Первый абзац", "Финал")
    p = _post("**📊 Заголовок**", "Первый абзац", "Кстати, у МетаМаск более 100 млн пользователей", "Финал")
    r = edit_delta.compare(d, p)
    assert r["added"] == 1 and any(t.startswith("дописал") for t in r["tags"])


def test_title_edit_flagged():
    """14.08: «Пока биток в минусе, к нему строят мост» → «Мост в крипту для азиатских капиталов»."""
    d = _post("**🌐 Пока биток в минусе, к нему строят мост для азиатских миллиардов**", "Тело", "Финал")
    p = _post("**📈 Мост в крипту для азиатских капиталов**", "Тело", "Финал")
    assert "заголовок" in edit_delta.compare(d, p)["tags"]


def test_finale_edit_flagged():
    d = _post("**📊 Заголовок**", "Тело поста про механику", "Первым до кассы дошёл не человек, а его агент")
    p = _post("**📊 Заголовок**", "Тело поста про механику", "В полном объёме начинают использовать агенты")
    assert "финал" in edit_delta.compare(d, p)["tags"]


def test_word_polish_is_not_rewrite():
    """19.08: «докажи в суде, что ты не бумага» → «не ценная бумага». Это шлифовка слова,
    и путать её с переписанной мыслью нельзя — иначе замер преувеличит беду."""
    d = _post("**⚠️ Заголовок**", "Тело поста",
              "Десять лет отрасли говорили докажи в суде, что ты не бумага")
    p = _post("**⚠️ Заголовок**", "Тело поста",
              "Десять лет отрасли говорили докажи в суде, что ты не ценная бумага")
    r = edit_delta.compare(d, p)
    assert r["wordy"] == 1 and r["rewritten"] == 0 and "шлифовка слов" in r["tags"]


def test_full_rewrite_flagged():
    """10.08 BIP-110: покрытие 53% — владелец переписал пост целиком после ошибки в ролях."""
    d = _post("**🌐 Майнеры хотели поменять правила Биткоина и не смогли**",
              "Правило продвигали майнеры со своими мощностями",
              "Последнее слово за тем, кто крутит железо")
    p = _post("**💸 Форк против Биткоина умер за одну ночь**",
              "Сначала о споре: с 2023 года в блоки зашивают картинки через Ordinals",
              "Оно за капиталом и пользователями, теми, кто держит монеты")
    assert "переписан целиком" in edit_delta.compare(d, p)["tags"]


def test_repeats_need_two_hits():
    """Одиночная правка — вкус дня, а не правило: в кандидаты уроков идёт только повтор."""
    reps = [{"tags": ["финал", "заголовок"]}, {"tags": ["финал"]}, {"tags": ["снял блок×2"]}]
    rep = edit_delta.repeats(reps)
    assert any(r.startswith("финал") for r in rep)
    assert not any(r.startswith("заголовок") for r in rep)


def test_repeat_ignores_counts():
    """«снял блок×1» и «снял блок×3» — один класс: важно ЧТО повторяется, а не сколько раз за пост."""
    reps = [{"tags": ["снял блок×1"]}, {"tags": ["снял блок×3"]}]
    assert any(r.startswith("снял блок") for r in edit_delta.repeats(reps))


def test_draft_kind_by_name_and_size():
    assert edit_delta._draft_kind("2026-08-19-sec-scope.md", "коротко") == "scope"
    assert edit_delta._draft_kind("2026-08-20-sopr.md", "т" * 3000) == "флагман"
    assert edit_delta._draft_kind("2026-08-20-note.md", "мелкий черновик") == ""


def test_empty_inputs_do_not_crash():
    assert edit_delta.compare("", "")["coverage"] == 0.0
    assert edit_delta.repeats([]) == []


def test_polish_is_not_clean():
    """19.08: покрытие 95%, но пять абзацев владелец всё же поправил. «Правок нет» — это ноль правок,
    иначе замер убаюкивает ровно там, где цель «не редактирую вообще» ещё не достигнута."""
    d = _post("**⚠️ Заголовок**", "Комиссия проголосовала 3 из 3", "Финал стоит сам")
    p = _post("**⚠️ Заголовок**", "Комиссия проголосовала единогласно 3 из 3", "Финал стоит сам")
    r = edit_delta.compare(d, p)
    assert r["clean"] is False and r["wordy"] == 1


def test_no_import_cycle():
    """core.edit_delta ↔ creator_tools/analytics_tools: импорт обоих в любом порядке не должен падать."""
    import importlib
    for mod in ("core.creator_tools", "core.analytics_tools", "core.edit_delta"):
        assert importlib.import_module(mod) is not None
