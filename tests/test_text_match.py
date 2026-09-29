"""Тесты сопоставления текстов (core/text_match): токены + асимметричное покрытие."""
from core import text_match as tm


def test_tokens_filters_short_and_punctuation():
    toks = tm.tokens("Иксы врут: 3x за 5 лет, ну и?")
    assert "иксы" in toks and "врут" in toks
    assert "3" in toks and "5" in toks          # числа
    assert "за" not in toks and "ну" not in toks  # <4 букв — отброшены


def test_coverage_identical_and_disjoint():
    assert tm.coverage("иксы врут годовых", "иксы врут годовых доходность") == 1.0
    assert tm.coverage("совсем другое слово", "иксы врут годовых") == 0.0
    assert tm.coverage("", "что угодно") == 0.0


def test_coverage_partial():
    # 2 из 3 токенов короткого покрыты длинным
    assert tm.coverage("иксы врут случайность", "иксы врут доходность") == 2 / 3


# --- обрезка для ИТОГ-панели: обрыв посреди слова врал владельцу (05.08) ------------------------

def test_clip_cuts_on_word_boundary():
    # было: «Circle объявила валидаторов Arc — BlackRock, Visa, D» — обрыв посреди имени
    s = "Circle объявила валидаторов Arc - BlackRock, Visa, DTCC становятся узлами"
    out = tm.clip(s, 52)
    assert out.endswith("…")
    assert len(out) <= 53
    assert not out.rstrip("…").endswith(("D", ","))     # ни обрубка слова, ни висячей запятой


def test_clip_keeps_short_text_untouched():
    assert tm.clip("короткая тема", 52) == "короткая тема"
    assert tm.clip("", 10) == ""
    assert tm.clip(None, 10) == ""


def test_clip_normalizes_whitespace():
    assert tm.clip("две   строки\nв одной", 40) == "две строки в одной"


def test_clip_handles_single_long_word():
    # одно слово длиннее лимита — режем жёстко, но обрыв всё равно помечаем
    out = tm.clip("A" * 80, 10)
    assert out == "A" * 10 + "…"


# --- суть поста для анти-повтора: заголовок это КРЮЧОК, тему называет ЛИД (дубль в канале 05.08) ---
# Анти-повтор отдавал гейту только заголовок. «BlackRock и Visa будут охранять чужую монету» не содержит
# ни «Circle», ни «Arc», ни «операторы» — гейт попытался опознать тему по нему и ошибся вслух
# («формулировка ближе к кастоди, чем к валидации блокчейна»), а через прогон выбрал ту же новость.

_REAL_POST = """**🌐 Сеть Circle обслуживают те же, кто в неё вложил деньги**

5 августа Circle раскрыла первых операторов сети Arc - блокчейна для расчётов в долларовом стейблкоине USDC. Среди них BlackRock, Visa, Mastercard, ICE, DTCC, Galaxy, MoneyGram

Но есть деталь, которую анонс обходит стороной

🖥 [Канал](https://t.me/x) | ▶️ [Медиа](https://linktr.ee/x)
"""


def test_gist_carries_the_event_not_just_the_hook():
    g = tm.post_gist(_REAL_POST)
    assert "Circle" in g and "Arc" in g          # событие опознаваемо — по нему гейт и сверяет
    assert "операторов" in g
    assert g.startswith("🌐 Сеть Circle")         # заголовок сохранён, он тоже полезен


def test_gist_skips_meta_and_footer():
    text = "[[MEDIA_SRC]] https://x.com/a\n\n**⚡️ Заголовок**\n\nЛид с фактом и датой\n\nхвост"
    g = tm.post_gist(text)
    assert g.startswith("⚡️ Заголовок")
    assert "MEDIA_SRC" not in g
    assert "Лид с фактом" in g


def test_gist_falls_back_to_title_when_body_is_footer_only():
    text = "**📊 Только заголовок**\n\n🖥 [Канал](https://t.me/x) | 🥸 [Мемы](https://t.me/y)"
    assert tm.post_gist(text) == "📊 Только заголовок"


def test_gist_is_capped_and_safe_on_junk():
    assert tm.post_gist("") == ""
    assert tm.post_gist(None) == ""
    assert len(tm.post_gist("**Заголовок**\n\n" + "слово " * 200)) <= 260


def test_two_headlines_about_one_event_share_the_lead():
    # заголовки одного события выглядят непохоже — совпадают ДАТА и ДЕЙСТВИЕ в лиде. Это и надо увидеть.
    a = tm.post_gist(_REAL_POST)
    b = tm.post_gist("**📊 DTCC и Visa стали операторами чужой сети**\n\n"
                     "5 августа Circle объявила 11 операторов своего блокчейна Arc: BlackRock, DTCC")
    assert "5 августа" in a and "5 августа" in b
    assert "Arc" in a and "Arc" in b
