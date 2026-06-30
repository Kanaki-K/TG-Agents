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


# --- авто-болд ПОДЗАГОЛОВКОВ-разделов флагмана (§5: ВСЕ заголовки жирные); тело и футер — нет ---

def test_autobolds_section_headers_flagship():
    post = ("**🔔 Заголовок**\n\nОбычное тело без эмодзи\n\n"
            "📊 Что происходит\n\nЕщё тело\n\n"
            "🖥 Канал (https://t.me/x) | 🥸 Мемы")
    clean, _ = creator_tools._lint(post, "flagship")
    lines = clean.splitlines()
    assert "**📊 Что происходит**" in lines          # раздел-вывеска ожирнён
    assert "Обычное тело без эмодзи" in lines          # тело без эмодзи не трогаем
    assert any(l.startswith("🖥 Канал") for l in lines)  # футер (http/|) НЕ ожирняем


def test_scope_section_headers_not_bolded():
    post = "**🔭 Заголовок**\n\nтело\n\n📊 Раздел\n\nещё"
    clean, _ = creator_tools._lint(post, "scope")
    assert "**📊 Раздел**" not in clean.splitlines()   # у короткого разделов-вывесок нет


# --- срез точки в КОНЦЕ строки: на всех форматах, флагман тоже; продолжение/многоточие беречь ---

def test_strips_trailing_period_flagship():
    clean, _ = creator_tools._lint(
        "**Тест**\n\nСтрока с точкой.\n\nДва. предложения на строке.\n\nмноготочие...", "flagship")
    lines = clean.splitlines()
    assert "Строка с точкой" in lines                 # хвостовая точка срезана
    assert "Два. предложения на строке" in lines       # точка ВНУТРИ строки сохранена, хвостовая срезана
    assert "многоточие..." in lines                    # троеточие не трогаем


# --- заголовок: вымученный глагол-метафора («выпил ликвидность») ловится ДО make_image ---

def test_warns_headline_metaphor_verb():
    _, warns = creator_tools._lint("🌐 Кто выпил ликвидность?\n\nтело поста", "flagship")
    assert any("глагол-метафора" in w for w in warns)


def test_good_headline_no_metaphor_warn():
    _, warns = creator_tools._lint(
        "💸 20% майнеров в убытке. Это поломка или уборка?\n\nтело", "flagship")
    assert not any("глагол-метафора" in w for w in warns)
