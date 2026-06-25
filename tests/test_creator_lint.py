"""Код-линтер Криейтора (creator_tools._lint) — детерминированные авто-правки и предупреждения."""
from core import creator_tools


# --- авто-болд титульной строки (§5: заголовок всегда жирный) ---

def test_autobolds_plain_title():
    clean, warns = creator_tools._lint("🔔 Заголовок поста\n\nТело поста.", "flagship")
    assert clean.splitlines()[0] == "**🔔 Заголовок поста**"
    assert not any("НЕ жирный" in w for w in warns)   # предупреждение больше не нужно — починили


def test_keeps_existing_bold_title():
    clean, _ = creator_tools._lint("**🔔 Уже жирный**\n\nТело.", "flagship")
    assert clean.splitlines()[0] == "**🔔 Уже жирный**"   # не задваиваем **


def test_skips_long_first_line():
    para = "Длинный первый абзац-хук сцена который точно не заголовок а вступление к посту целиком тут"
    clean, _ = creator_tools._lint(para + "\n\nещё текст", "flagship")
    assert not clean.startswith("**")   # >80 знаков = не заголовок, не трогаем


def test_light_kind_title_untouched():
    clean, _ = creator_tools._lint("Короткая мысль на сегодня\n\nещё", "light")
    assert not clean.startswith("**")   # Ф3 «чистый текст» — заголовка-строки может не быть


# --- типографика (авто-чинится) + предупреждения (не вслепую) ---

def test_normalizes_dashes_and_quotes():
    clean, _ = creator_tools._lint("**Тест**\n\nтире — и «ёлочки»", "flagship")
    assert "—" not in clean and "«" not in clean and "»" not in clean


def test_warns_currency_before_number():
    _, warns = creator_tools._lint("**Тест**\n\nцена $73 млн тут", "flagship")
    assert any("валюта" in w.lower() for w in warns)
