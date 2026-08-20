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
    # заголовок одним вопросом (колон-тег) — без глагола-метафоры (форма «факт. вопрос?» снята 20.07)
    _, warns = creator_tools._lint(
        "💸 20% майнеров в убытке: поломка или уборка?\n\nтело", "flagship")
    assert not any("глагол-метафора" in w for w in warns)


# --- заголовок ФЛАГМАНА: эмодзи-якорь обязателен + РОВНО одно предложение (владелец 20.07) ---

def test_flagship_headline_without_emoji_warns():
    # флагман вышел без эмодзи-якоря (баг «Охота за стопами» 20.07)
    _, warns = creator_tools._lint(
        "Рынок вытряхивает трейдеров\n\n" + "тело поста " * 400, "флагман")
    assert any("БЕЗ эмодзи" in w for w in warns)


def test_flagship_headline_with_emoji_single_question_ok():
    _, warns = creator_tools._lint(
        "📊 Кто охотится за Вашим стоп-лоссом?\n\n" + "тело поста " * 400, "флагман")
    assert not any("БЕЗ эмодзи" in w for w in warns)
    assert not any("ДВУХ предложени" in w for w in warns)


def test_flagship_headline_two_sentences_warns():
    # «утверждение. утверждение» — ровно то, что владелец забраковал 20.07
    _, warns = creator_tools._lint(
        "📊 Рынок вытряхивает трейдеров. Долгосрочника - нечем\n\n" + "тело " * 400, "флагман")
    assert any("ДВУХ предложени" in w for w in warns)


def test_flagship_headline_fact_question_now_warns():
    # «факт. вопрос?» БОЛЬШЕ не формула — теперь тоже два предложения (владелец 20.07)
    _, warns = creator_tools._lint(
        "💸 20% майнеров в убытке. Это поломка или уборка?\n\n" + "тело " * 400, "флагман")
    assert any("ДВУХ предложени" in w for w in warns)


def test_flagship_headline_colon_tag_ok():
    # тег-тема через ДВОЕТОЧИЕ = одно предложение → ок
    _, warns = creator_tools._lint(
        "📉 DXY в 2026: главный фильтр для крипто-риска\n\n" + "тело " * 400, "флагман")
    assert not any("ДВУХ предложени" in w for w in warns)


# --- scope: заголовок = ОДИН крючок (манифест §1) ---

def test_scope_headline_two_sentences_statement_tail_warns():
    # утверждение + приколка = ДВА предложения → ДЕТЕРМИНИРОВАННО режем до первого (не просто warn):
    # прогоны 24.07 показали, что на warn модель отвечала «авторское решение, не режу».
    clean, warns = creator_tools._lint(
        "📈 Robinhood запустил блокчейн для акций. Пришли мемы\n\nтело поста", "scope")
    assert any("ДВОЙНЫМ" in w for w in warns)
    # заголовок к моменту среза уже авто-обёрнут в **…** (§5), срез сохраняет жирность
    assert clean.split("\n")[0] == "**📈 Robinhood запустил блокчейн для акций**"


def test_scope_headline_statement_plus_question_trimmed_to_statement():
    # «утверждение. вопрос?» → оставляем ПЕРВОЕ (утверждение), вопрос-хвост срезаем (владелец 20.07)
    clean, warns = creator_tools._lint(
        "💸 700 млрд$ домой каждый год. Банк или крипта?\n\nтело поста", "scope")
    assert any("ДВОЙНЫМ" in w for w in warns)
    assert clean.split("\n")[0] == "**💸 700 млрд$ домой каждый год**"


def test_scope_headline_bold_two_sentences_trimmed_keeps_bold():
    # реальный кейс 24.07 (квантовый пост): жирную обёртку сохраняем, точку в конце убираем
    clean, _ = creator_tools._lint(
        "**⚠️ 15 млн$ на квантовую защиту BTC. Страховка или пиар?**\n\nтело поста", "scope")
    assert clean.split("\n")[0] == "**⚠️ 15 млн$ на квантовую защиту BTC**"


def test_scope_headline_tag_prefix_two_sentences_trimmed():
    # тег-рубрику «LINK | …» сохраняем целиком, режем только заголовок после разделителя
    clean, _ = creator_tools._lint(
        "🌐 LINK | Факт один. Вопрос два?\n\nтело поста", "scope")
    assert clean.split("\n")[0] == "**🌐 LINK | Факт один**"


def test_scope_headline_single_sentence_ok():
    # одно утверждение — ок; и одиночный вопрос — ок; тег-рубрика «🌐 LINK | …» не считается
    for good in ("📈 Robinhood построил блокчейн для акций\n\nтело",
                 "❓ Кто пришёл на блокчейн первым?\n\nтело",
                 "🌐 LINK | Chainlink в банках Европы и Кореи\n\nтело"):
        _, warns = creator_tools._lint(good, "scope")
        assert not any("ДВОЙНЫМ" in w for w in warns), good


def test_scope_headline_initials_not_two_sentences():
    # точка после ИНИЦИАЛА/сокращения из одной буквы — не конец предложения (ложняк 17.07: T. Rowe Price)
    for good in ("📊 T. Rowe Price открыл крипту для пенсионных денег\n\nтело",
                 "📊 U.S. Bank запустил кастоди для крипты\n\nтело"):
        _, warns = creator_tools._lint(good, "scope")
        assert not any("ДВОЙНЫМ" in w for w in warns), good


# --- утечка англоязычного источника в русский текст (сессия 15.07, CLARITY) ---

def test_latin_person_name_warns():
    # «Trump задекларировал 1.4 млрд$» — владелец правил на «Трамп» (баг 15.07)
    _, warns = creator_tools._lint("⚠️ Заголовок\n\nTrump задекларировал 1.4 млрд$ за 2025", "scope")
    assert any("ЛАТИНИЦЕЙ" in w and "Трамп" in w for w in warns)


def test_latin_brand_name_is_fine():
    # бренды латиницей — норма канала (эталоны §8.1: Chainlink, SpaceX, Visa, BlackRock)
    _, warns = creator_tools._lint(
        "🌐 Заголовок\n\nChainlink подключился к Pangea. SpaceX держит 18 тысяч BTC", "scope")
    assert not any("ЛАТИНИЦЕЙ" in w for w in warns)


def test_recess_calque_warns():
    # «до рецесса» — калька с recess прямо из источника; владелец правил на «до перерыва»
    _, warns = creator_tools._lint("⚠️ Заголовок\n\nСенат вернулся, до рецесса 3 недели", "scope")
    assert any("рецесс" in w for w in warns)


# --- заголовок ОБЛОЖКИ: без эмодзи и без кавычек (правило владельца 16.07) ---

def test_cover_title_strips_quotes():
    # в теле поста «лапки» законны (в банке 6 из 291 заголовков с кавычками) — режем ТОЛЬКО для баннера
    assert creator_tools._clean_title('📊 "Я сделал 5 иксов". А сколько это в год?') \
        == "Я сделал 5 иксов. А сколько это в год?"


def test_cover_title_strips_guillemets_and_curly():
    assert creator_tools._clean_title("💎 Что значит «сильный актив» в портфеле?") \
        == "Что значит сильный актив в портфеле?"
    assert creator_tools._clean_title("💥 Миф: “Я живу на крипту”") == "Миф: Я живу на крипту"


def test_cover_title_keeps_plain_text_intact():
    assert creator_tools._clean_title("📉 DXY в 2026: главный фильтр для крипто-риска") \
        == "DXY в 2026: главный фильтр для крипто-риска"


# --- AI-ритм детекторы (нечёткие) — покрытие + фикс антитезы (аудит линтера 20.07) ---

def test_antithesis_forward_overuse_warns():
    # 3+ ПРЯМЫХ «не X, а Y» = ИИ-ритм → предупреждение
    post = ("**Тест**\n\nБиткоин не казино, а инструмент. Крипта не ставка, а позиция. "
            "Холд не спекуляция, а стратегия")
    _, warns = creator_tools._lint(post, "flagship")
    assert any("антитез" in w for w in warns)


def test_antithesis_simple_contrast_not_flagged():
    # ФИКС 20.07: обратная «X, а не Y» = ПРОСТОЙ контраст, не риторика — НЕ считаем (иначе модель
    # клипала «а не»→«не» ради ухода из-под порога → телеграфный тон хуже исходного, урок :33)
    post = ("**Тест**\n\nЭто исключение, а не правило. Читаем вероятности, а не станок. "
            "Держим позицию, а не торгуем")
    _, warns = creator_tools._lint(post, "flagship")
    assert not any("антитез" in w for w in warns)


def test_staccato_triads_warn():
    _, warns = creator_tools._lint("**Тест**\n\nBTC вырос. Рынок ожил. Все рады. Паника ушла", "flagship")
    assert any("стаккато" in w for w in warns)


def test_triplet_double_negation_warns():
    _, warns = creator_tools._lint("**Тест**\n\nОн не торговал, не спекулировал - просто держал", "flagship")
    assert any("триплет" in w for w in warns)


def test_superlative_warns():
    _, warns = creator_tools._lint("**Тест**\n\nЭто крупнейший фонд на рынке сегодня", "flagship")
    assert any("суперлатив" in w for w in warns)


def test_hedge_anglicism_warns_but_hedgefund_ok():
    _, warns = creator_tools._lint("**Тест**\n\nБиткоин как хедж от инфляции", "flagship")
    assert any("хедж" in w for w in warns)
    _, warns2 = creator_tools._lint("**Тест**\n\nХедж-фонд купил биткоин на просадке", "flagship")
    assert not any("хедж" in w for w in warns2)   # «хедж-фонд» как организация — не трогаем


def test_importance_announcer_warns():
    _, warns = creator_tools._lint("**Тест**\n\nВот это и есть новость недели для рынка", "flagship")
    assert any("анонс важности" in w for w in warns)


def test_eto_ne_x_eto_y_warns():
    _, warns = creator_tools._lint("**Тест**\n\nЭто не риск. Это возможность для терпеливых", "flagship")
    assert any("Это не X" in w for w in warns)


def test_headline_personification_warns():
    _, warns = creator_tools._lint("🔔 Что увидела пенсия в биткоине\n\nтело поста", "flagship")
    assert any("олицетворение" in w for w in warns)


def test_http_link_in_body_warns():
    _, warns = creator_tools._lint("**Тест**\n\nПодробности тут https://example.com в статье", "flagship")
    assert any("ссылка" in w.lower() for w in warns)


# --- дословный ПОВТОР абзаца (баг Strategy 31.07: дубль ушёл в отложку) ---

def test_cuts_duplicate_paragraph():
    # судья финала продублировал абзац при сплайсе → линтер режет дубль на общем пути сохранения
    post = ("**⚠️ Заголовок**\n\nТезис на BTC не сломался\n\nТезис на BTC не сломался\n\n"
            "Но покупателя последней инстанции больше нет")
    clean, warns = creator_tools._lint(post, "scope")
    assert clean.count("Тезис на BTC не сломался") == 1        # осталось ПЕРВОЕ вхождение
    assert "Но покупателя последней инстанции больше нет" in clean   # остальное цело
    assert any("ПОВТОР абзаца" in w for w in warns)            # владелец видит, что резали


def test_keeps_distinct_paragraphs():
    post = "**⚠️ Заголовок**\n\nПервый абзац про механику\n\nВторой абзац про последствие"
    clean, warns = creator_tools._lint(post, "scope")
    # ⚠️ 14.08 счёт абзацев тут больше НЕ показатель: у scope линтер сам дописывает потерянный футер
    # (баг «пост уехал в канал голым»), поэтому «\n\n» стало на один больше. Проверяем то, ради чего
    # тест и писался: дедуп не тронул РАЗНЫЕ абзацы.
    assert "Первый абзац про механику" in clean and "Второй абзац про последствие" in clean
    assert not any("ПОВТОР абзаца" in w for w in warns)


def test_short_repeat_line_kept():
    # короткий рефрен (<15 знаков) — намеренный приём, не режем
    post = "**⚠️ Заголовок**\n\nИ всё\n\nтело поста тут\n\nИ всё"
    clean, warns = creator_tools._lint(post, "scope")
    assert clean.count("И всё") == 2
    assert not any("ПОВТОР абзаца" in w for w in warns)


# --- шаблонные ИИ-связки (разбор 31.07: «подача как всегда ИИшная») ---

def test_flags_template_connector():
    post = "**⚠️ Заголовок**\n\nМеханика проста: обязательства тикают каждый квартал\n\n" + "х" * 400
    _, warns = creator_tools._lint(post, "scope")
    assert any("ШАБЛОННАЯ ИИ-СВЯЗКА" in w for w in warns)


def test_clean_scope_has_no_connector_warn():
    post = "**⚠️ Заголовок**\n\nОбязательства тикают каждый квартал, а продавать приходится на падении\n\n" + "х" * 400
    _, warns = creator_tools._lint(post, "scope")
    assert not any("ШАБЛОННАЯ ИИ-СВЯЗКА" in w for w in warns)


# --- ФОРМА ФИНАЛА кодом (заменила снятого судью-модель, переработка 31.07) ---
# Судья-модель переписывала концовку САМА — она же 31.07 продублировала абзац и вместе с двумя
# другими судьями стачивала голос. Теперь форму меряет код и возвращает претензию АВТОРУ.

_FOOT = "🖥 [Канал](https://t.me/x) | ▶️ [Медиа](https://linktr.ee/y)"


def _n(s: str) -> int:
    """Счёт Telegram (UTF-16 units) — как в линтере."""
    return len(s.encode("utf-16-le")) // 2


def _filled_to(head: str, tail: str, target: int, filler: str = "детали механики ") -> str:
    """Пост чуть ДЛИННЕЕ target — наполнитель считаем ОТ КОНСТАНТЫ, а не зашитым числом повторов.
    Потолок scope за август менялся трижды (1250 → 1500 → 1350), и фикстура с магическим «×70»
    падала при каждой правке, хотя поведение линтера было верным (падение 20.08)."""
    need = max(target + 40 - _n(head + tail), len(filler))
    return head + filler * (need // len(filler) + 1) + tail


def _post_with_finale(fin: str) -> str:
    return ("**⚠️ Заголовок поста**\n\nПервый абзац тела с фактом и цифрой\n\n"
            "Второй абзац - механизм и вывод\n\n" + fin + "\n\n" + _FOOT)


def test_finale_question_flagged():
    _, warns = creator_tools._lint(_post_with_finale("А кто заплатит за это в итоге?"), "scope")
    assert any("финал-ВОПРОС" in w for w in warns)


def test_finale_hedge_flagged():
    _, warns = creator_tools._lint(_post_with_finale("Посмотрим, что будет дальше"), "scope")
    assert any("финал-ХЕДЖ" in w for w in warns)


def test_finale_fused_with_caveat_flagged():
    # реальный класс бага bStocks: вывод спрятан внутри абзаца после разворота
    fin = "Честно, у медали две стороны. Но кто построил вход без порога, забирает клиента раньше"
    _, warns = creator_tools._lint(_post_with_finale(fin), "scope")
    assert any("СЛИПСЯ С ОГОВОРКОЙ" in w for w in warns)


def test_finale_long_flagged():
    fin = "Первое предложение тут. Второе предложение тут. Третье предложение тоже тут"
    _, warns = creator_tools._lint(_post_with_finale(fin), "scope")
    assert any("предложений" in w for w in warns)


def test_good_kicker_clean():
    # самостоятельный кикер: одно утверждение, стоит отдельно — претензий быть не должно
    _, warns = creator_tools._lint(_post_with_finale("Годами строили под Биткоин, а первым выкупил AI"), "scope")
    assert not any(w.startswith("scope: финал") for w in warns)


def test_kicker_starting_with_turn_is_ok():
    # кикер, НАЧИНАЮЩИЙСЯ с «Но» — это сам кикер, а не слипание: не трогаем
    _, warns = creator_tools._lint(
        _post_with_finale('Но покупателя последней инстанции больше нет'), "scope")
    assert not any("СЛИПСЯ" in w for w in warns)


def test_word_ending_in_no_is_not_a_turn():
    # КОРЕНЬ провала 07.08: «но » ловилось внутри слов («имен-но », «нуж-но ») → ложная претензия
    # «финал слипся с оговоркой» → автор перестал верить линтеру и отмахнулся заодно от ВЕРНОЙ.
    fin = "Архитектура закладывается именно сейчас. Правила задаёт тот, кто держит ключи"
    _, warns = creator_tools._lint(_post_with_finale(fin), "scope")
    assert not any("СЛИПСЯ" in w for w in warns)


def test_finale_checked_even_if_writer_lost_footer():
    """ПЕРЕСМОТРЕНО 14.08. Раньше без футера судья финала МОЛЧАЛ («структуру не угадать») — и ровно
    это случилось в бою: писатель потерял футер, а вместе с ним тихо отключилась проверка САМОЙ
    дорогой строки формата. Один пропущенный служебный блок гасил механизм, который владелец правит
    руками 10+ сессий. Теперь футер возвращает код, а финал считается по последнему абзацу — то есть
    финал-вопрос ловится в любом случае."""
    _, warns = creator_tools._lint("**Заголовок**\n\nтело поста\n\nчто-то ещё?", "scope")
    assert any("финал-" in w for w in warns)


# --- ПОСТ-ИНСТРУКЦИЯ: формат уступает безопасности (случай Coldcard 31.07) ---
# Завод выпустил пост об утечке 594 BTC с инструкцией по миграции: неверный номер исправленной
# прошивки и НЕПОЛНЫЙ список затронутых устройств. Читатель с неназванной моделью решил бы, что
# это не про него. Поймал владелец руками — 2FA сверил цифры поштучно и не спросил про полноту.

def test_detects_advice_post():
    assert creator_tools.is_advice_post("мигрируйте на новый seed") is True
    assert creator_tools.is_advice_post("обновитесь на исправленную прошивку") is True
    assert creator_tools.is_advice_post("считайте скомпрометированным") is True


def test_plain_analysis_is_not_advice():
    assert creator_tools.is_advice_post("фонд купил пакет, механика такая") is False
    assert creator_tools.is_advice_post("") is False


def test_long_advice_post_gets_soft_length_note():
    post = _filled_to("**⚠️ Заголовок**\n\nКого касается: Mk3, Mk4, Mk5 и Q. ",
                      "\n\nмигрируйте на новый seed, обновление уже созданный seed не спасает\n\n" + _FOOT,
                      creator_tools.SCOPE_TOTAL_CAP)
    assert _n(post) > creator_tools.SCOPE_TOTAL_CAP        # фикстура реально выше потолка
    _, warns = creator_tools._lint(post, "scope")
    assert not any("длинноват" in w or "РАЗДУЛСЯ" in w for w in warns)   # общего «режь» тут быть не должно
    assert any("пост-ИНСТРУКЦИЯ" in w for w in warns)           # вместо него — «режь только воду»


def test_long_plain_post_gets_length_note_not_hard_stop():
    """Правка 10.08: между целью формата и раздуванием — СОВЕТ, а не ⛔. Жёсткий запрет тут заставлял
    писателя выбрасывать объяснение предмета, чтобы влезть (случай BIP-110). ⛔ живёт выше, с
    SCOPE_BLOAT_CAP — это проверяет test_bloat_is_hard_stop."""
    post = "**⚠️ Заголовок**\n\n" + ("разбор механики " * 90) + "\n\n" + _FOOT
    _, warns = creator_tools._lint(post, "scope")
    assert creator_tools.SCOPE_TOTAL_CAP < len(post.encode("utf-16-le")) // 2 <= creator_tools.SCOPE_BLOAT_CAP
    assert any("длинноват" in w for w in warns)
    assert not any("РАЗДУЛСЯ" in w for w in warns)


# --- ЭТАЛОН = ПРИЁМ, А НЕ СТРОКА: копия из мануала/банка/своего поста (владелец 03.08) ---

def test_flags_finale_copied_from_manual_bank():
    # «Деньги меняют убеждения очень быстро» лежит в scope_manual §4.5 как ПРИМЕР приёма «афоризм»
    # (и была финалом поста про CLARITY 15.07). 03.08 машина взяла её дословно — линтер обязан вернуть.
    post = ("**⚡️ Заголовок теста**\n\n3 августа банк открыл счёт бирже - деньги клиентов отдельно\n\n"
            "Деньги меняют убеждения очень быстро\n\n" + _FOOT)
    _, warns = creator_tools._lint(post, "scope")
    assert any("СПИСАН" in w for w in warns)
    assert any("мануал" in w for w in warns)          # сказано, ОТКУДА списано


def test_original_lines_are_not_flagged_as_copy():
    post = ("**⚡️ Свой заголовок**\n\nЛицензированная площадка получила расчётный счёт под клиентские "
            "средства\n\nСлова главы банка не поменялись - поменялось поведение банка\n\n" + _FOOT)
    _, warns = creator_tools._lint(post, "scope")
    assert not any("СПИСАН" in w for w in warns)


def test_short_line_never_counts_as_copy():
    # короткая общая фраза совпадает с эталонами по словам, но приёмом не является — ложняк дороже
    assert creator_tools._reused_lines("**Заголовок**\n\nЦифры говорят обратное\n\n" + _FOOT) == []


def test_reuse_check_survives_missing_sources(monkeypatch, tmp_path):
    # выгрузки канала/мануала нет (чистая машина, первый запуск) — линтер не падает, просто не сверяет
    monkeypatch.setattr(creator_tools.config, "ROOT", tmp_path)
    creator_tools._REUSE_CACHE.clear()
    out = creator_tools._reused_lines("**Заголовок**\n\nЛюбая строка поста про повод дня\n\n" + _FOOT)
    assert isinstance(out, list)          # источников нет → сверять не с чем, но линтер живой
    creator_tools._REUSE_CACHE.clear()


# --- дыры в детекторах, найденные редактурой владельца 05.08 (пост про Cloudflare Wallets) ---
# Ни одной фактической ошибки в посте не было (2FA дал 7✅/0⚠), но три правки владельца попадали в
# классы, которые линтер УЖЕ умеет ловить и пропустил из-за узких мест — регистра и словарей.

def test_eto_ne_x_eto_y_caught_after_dash():
    # штамп сидел не в начале предложения, а в хвосте через тире — детектор требовал заглавной «Это»
    # в ОБЕИХ половинах и такую форму пропускал: «...для агентного интернета - это не пилот. Это фундамент»
    body = ("**⚡️ Заголовок поста тут**\n\nКогда такая компания выбирает платёжную архитектуру для "
            "агентного интернета - это не пилот. Это фундамент\n\nхвост поста")
    _, warns = creator_tools._lint(body, "scope")
    assert any("Это не X. Это Y" in w for w in warns)


def test_eto_ne_x_eto_y_still_caught_at_sentence_start():
    body = "**⚡️ Заголовок**\n\nЭто не эксперимент. Это архитектура расчётов\n\nхвост"
    _, warns = creator_tools._lint(body, "scope")
    assert any("Это не X. Это Y" in w for w in warns)


def test_plain_negation_inside_one_sentence_not_flagged():
    # обычное «это не так, это иначе» внутри фразы штампом не считаем (вторая часть без заглавной)
    body = "**⚡️ Заголовок**\n\nДля инвестора это не мелочь, это меняет расклад\n\nхвост"
    _, warns = creator_tools._lint(body, "scope")
    assert not any("Это не X. Это Y" in w for w in warns)


def test_solo_label_lead_in_warns_for_scope():
    # «Честно:» — тот же ярлык-раздел, только в одно слово; список ловил лишь составные («риск честно»)
    body = ("**⚡️ Заголовок поста тут**\n\nтело поста\n\nЧестно: пока открылось только резервирование, "
            "реальные платежи обещают позже\n\nфинал")
    _, warns = creator_tools._lint(body, "scope")
    assert any("подводку-ярлык" in w for w in warns)


def test_honest_inside_line_is_not_a_label():
    # «честно» живой строкой — норма (мануал прямо велит вплетать оговорку в фразу)
    body = ("**⚡️ Заголовок поста тут**\n\nповод честно позитивный, и оптика тут честно в плюс\n\nфинал")
    _, warns = creator_tools._lint(body, "scope")
    assert not any("подводку-ярлык" in w for w in warns)


def test_handle_anglicism_warns():
    body = "**⚡️ Заголовок**\n\nПока открылось только резервирование handle\n\nфинал"
    _, warns = creator_tools._lint(body, "scope")
    assert any("англицизмы" in w and "handle" in w for w in warns)


# --- ПОДАЧА: структура абзацев и скрытый вопрос в финале (правки владельца 07.08, MetaMask) ---
# Пост уехал в отложку с абзацем на 415 знаков (четыре мысли через «;») и финалом-вопросом без «?».
# Владелец разнёс абзацы и переписал финал руками — оба класса теперь меряет код.

def test_finale_question_without_mark_flagged():
    fin = "Архитектура закладывается именно сейчас. Чьи правила окажутся у AI в кармане - банка или Ваши"
    _, warns = creator_tools._lint(_post_with_finale(fin), "scope")
    assert any("БЕЗ знака вопроса" in w for w in warns)


def test_finale_alternative_tail_flagged():
    # хвост-выбор «- А или Б» — тот же вопрос, даже без вопросительного слова в начале
    _, warns = creator_tools._lint(
        _post_with_finale("Платит за это в итоге кто-то один - держатель токена или сама сеть"), "scope")
    assert any("БЕЗ знака вопроса" in w for w in warns)


def test_statement_kicker_with_ili_not_flagged():
    # «или» внутри утверждения — норма, претензии быть не должно (0 ложных на 277 финалах канала)
    _, warns = creator_tools._lint(
        _post_with_finale("Такие сделки закрывают банки или биржи, а платит всегда клиент"), "scope")
    assert not any("БЕЗ знака вопроса" in w for w in warns)


def test_owner_rewritten_finale_is_clean():
    # финал, который владелец написал взамен: утверждение, стоит само → линтер молчит
    fin = ("Человеку в системе можно доверять или нет. Коду доверять не нужно - он либо пропускает "
           "операцию, либо нет")
    _, warns = creator_tools._lint(_post_with_finale(fin), "scope")
    assert not any(w.startswith("scope: финал") for w in warns)


def test_wall_paragraph_flagged():
    wall = ("Два режима: Guard Mode - агент работает по одобренному списку протоколов и лимитам, выход "
            "за правила - двухфакторка владельцу; Beast Mode - минимум прерываний, но принудительная 2FA "
            "на транзакциях, помеченных как вредоносные, сохраняется. Каждая транзакция проходит "
            "симуляцию и проверку угроз до исполнения. Убыток, если защита не сработала - покрывается "
            "до 10 000$ в месяц. За кошельком - 100 млн пользователей MetaMask")
    _, warns = creator_tools._lint(_post_with_finale(wall + "\n\nфинал строкой"), "scope")
    assert any("ПРОСТЫНЯ" in w for w in warns)


def test_semicolon_enumeration_flagged():
    body = ("**⚡️ Заголовок**\n\nДва режима: Guard Mode - по списку протоколов; Beast Mode - без "
            "остановок\n\nфинал")
    _, warns = creator_tools._lint(body, "scope")
    assert any("СЛЕПЛЕНО В СТРОКУ" in w for w in warns)


def test_normal_paragraphs_not_flagged_as_wall():
    # разнесённая владельцем версия тех же фактов — претензий к структуре нет
    body = ("**⚡️ AI получил кошелёк**\n\nДва режима:\n\nGuard Mode - агент работает по одобренному "
            "списку протоколов и лимитам, выход за правила - 2FA владельцу\n\nBeast Mode - минимум "
            "прерываний, но принудительная 2FA на вредоносных транзакциях\n\nКстати, у МетаМаск более "
            "100 млн пользователей\n\nфинал строкой")
    _, warns = creator_tools._lint(body, "scope")
    assert not any("ПРОСТЫНЯ" in w or "СЛЕПЛЕНО" in w for w in warns)


def test_list_block_not_counted_as_wall():
    # маркированный список-блок (3+ строки в абзаце) длинный ПО ПРИРОДЕ — не простыня
    lst = "\n".join("🔸 " + "пункт списка канала про архитектуру сети и экономику токена" for _ in range(4))
    _, warns = creator_tools._lint("**⚡️ Заголовок**\n\n" + lst + "\n\nфинал", "scope")
    assert not any("ПРОСТЫНЯ" in w for w in warns)


def test_term_jitter_flagged():
    body = ("**⚡️ Заголовок**\n\nВыход за правила - двухфакторка владельцу, а на вредоносных "
            "транзакциях 2FA принудительная\n\nфинал")
    _, warns = creator_tools._lint(body, "scope")
    assert any("ДВУМЯ ИМЕНАМИ" in w for w in warns)


def test_single_term_is_clean():
    body = "**⚡️ Заголовок**\n\nВыход за правила - 2FA владельцу, на вредоносных 2FA принудительная\n\nфинал"
    _, warns = creator_tools._lint(body, "scope")
    assert not any("ДВУМЯ ИМЕНАМИ" in w for w in warns)


# --- код-жаргон без расшифровки (владелец 10.08: «не понятна сама проблема») ---

def test_protocol_code_flagged():
    """Пост 10.08 назвал BIP-110 четырежды и ни разу не сказал, что тот предлагал. Имя стандарта
    читателю канала не говорит ничего — линтер возвращает автору вопрос, а не правит текст."""
    body = ("**🌐 Заголовок поста**\n\n8 августа сеть раскололась. Правило BIP-110 включилось и "
            "потребовало, чтобы майнеры под него подписались\n\nфинал стоит сам")
    _, warns = creator_tools._lint(body, "scope")
    assert any("КОД-ЖАРГОН" in w and "BIP-110" in w for w in warns)


def test_known_code_not_flagged():
    # GPT-5 аудитория знает без расшифровки — на таком не дёргаем (замер: шаблон и так <1% постов)
    body = "**⚡️ Заголовок**\n\nGPT-5 вышел вчера и стоит денег\n\nфинал стоит сам"
    _, warns = creator_tools._lint(body, "scope")
    assert not any("КОД-ЖАРГОН" in w for w in warns)


def test_no_code_no_warning():
    body = "**⚡️ Заголовок**\n\nБиржа купила блокчейн-компанию за 400 млн usd\n\nфинал стоит сам"
    _, warns = creator_tools._lint(body, "scope")
    assert not any("КОД-ЖАРГОН" in w for w in warns)


# --- длина scope: цель ≠ раздувание (правка 10.08) ---

def test_over_target_is_advice_not_hard_stop():
    """Между целью формата и раздуванием линтер СОВЕТУЕТ резать воду, но не запрещает: жёсткий ⛔
    здесь заставлял писателя выбрасывать объяснение предмета, чтобы влезть (случай BIP-110)."""
    body = "**⚡️ Заголовок**\n\n" + ("тело " * 260) + "\n\nфинал стоит сам\n\n🖥 Канал | ▶️ Медиа"
    _, warns = creator_tools._lint(body, "scope")
    long_w = [w for w in warns if "длинноват" in w or "РАЗДУЛСЯ" in w]
    assert long_w and "РАЗДУЛСЯ" not in long_w[0]
    assert "ОСТАВЬ" in long_w[0]        # объяснение предмета длину оправдывает


def test_bloat_is_hard_stop():
    body = "**⚡️ Заголовок**\n\n" + ("тело " * 400) + "\n\nфинал стоит сам\n\n🖥 Канал | ▶️ Медиа"
    _, warns = creator_tools._lint(body, "scope")
    assert any("РАЗДУЛСЯ" in w for w in warns)


# --- выдуманная сцена-свидетель (урок 16.07 → повтор 20.08, теперь в коде) ---

def test_flags_invented_chat_quote():
    """«Чат ожил: "развернулись, погнали"» — реплика, приписанная безымянной толпе (флагман SOPR 20.08)."""
    body = '**📊 Заголовок**\n\nЧат ожил: "развернулись, погнали"\n\nдальше текст'
    _, warns = creator_tools._lint(body, "флагман")
    assert any("ВЫДУМАННАЯ СЦЕНА" in w for w in warns)


def test_flags_invented_witness_action():
    body = "**📊 Заголовок**\n\nЕщё неделю назад было скучно, знакомые уходили из чата\n\nдальше"
    _, warns = creator_tools._lint(body, "флагман")
    assert any("ВЫДУМАННАЯ СЦЕНА" in w for w in warns)


def test_generalized_observation_not_flagged():
    """Форма, на которую владелец САМ переписал сцену 16.07, — законная, её не трогаем."""
    body = "**📊 Заголовок**\n\nРаньше присылали в чаты скрины с иксами\n\nдальше текст"
    _, warns = creator_tools._lint(body, "флагман")
    assert not any("ВЫДУМАННАЯ СЦЕНА" in w for w in warns)


def test_share_with_friend_not_flagged():
    body = "**📊 Заголовок**\n\nПост, которым хочется поделиться с другом и обсудить\n\nдальше"
    _, warns = creator_tools._lint(body, "флагман")
    assert not any("ВЫДУМАННАЯ СЦЕНА" in w for w in warns)


# --- флагман про метрику: где стрелка СЕГОДНЯ (правка владельца 20.08) ---

def test_metric_post_without_today_reading():
    body = ("**📊 SOPR - рынок в боли или в жадности?**\n\nSOPR сравнивает цену продажи с ценой покупки\n\n"
            "Выше 1 - продают с прибылью, ниже 1 - в убыток\n\nВ медвежьем рынке SOPR упирается в 1")
    _, warns = creator_tools._lint(body, "флагман")
    assert any("БЕЗ ПОКАЗАНИЯ НА СЕГОДНЯ" in w for w in warns)


def test_metric_post_with_today_reading_ok():
    body = ("**📊 SOPR - рынок в боли или в жадности?**\n\nSOPR сравнивает цену продажи с ценой покупки\n\n"
            "Сейчас SOPR у 1.007 - рынок продаёт в ноль\n\nВ медвежьем рынке SOPR упирается в 1")
    _, warns = creator_tools._lint(body, "флагман")
    assert not any("БЕЗ ПОКАЗАНИЯ НА СЕГОДНЯ" in w for w in warns)


def test_metric_mentioned_in_passing_not_flagged():
    """Упоминание вскользь (<3 раз) — пост не ПРО метрику, показания не требуем."""
    body = "**📊 Заголовок**\n\nЕсть ещё MVRV, но это тема другого поста\n\nдальше текст про другое"
    _, warns = creator_tools._lint(body, "флагман")
    assert not any("БЕЗ ПОКАЗАНИЯ НА СЕГОДНЯ" in w for w in warns)


def test_generalization_frame_not_flagged():
    """Живой оборот канала: персонаж внутри рамки обобщения («Вы наверняка ловили себя…») — законен.
    Замер по 323 постам: это единственное срабатывание детектора на утверждённых текстах."""
    body = ('**📊 Заголовок**\n\nВы наверняка ловили себя на этом: друг скинул "перспективный альт" - '
            'неудобно отказать\n\nдальше текст')
    _, warns = creator_tools._lint(body, "флагман")
    assert not any("ВЫДУМАННАЯ СЦЕНА" in w for w in warns)


def test_market_generalization_not_flagged():
    """«Толпа продаёт» / «кто-то покупает» — обобщение РЫНКА, а не персонаж-свидетель."""
    body = "**📊 Заголовок**\n\nТолпа продаёт на дне, а кто-то по другую сторону молча покупал\n\nдальше"
    _, warns = creator_tools._lint(body, "флагман")
    assert not any("ВЫДУМАННАЯ СЦЕНА" in w for w in warns)
