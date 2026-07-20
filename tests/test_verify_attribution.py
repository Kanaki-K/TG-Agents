"""Контракт гейта АТРИБУЦИЙ (баг 15.07 «по словам сенатора Ламмис»), без LLM/сети.

Что защищаем: пост приписал реальному сенатору прогноз, которого она не давала (в брифе Ламмис не было
вообще). 2FA пропустил — имя под цитатой в его чек-лист не входило. Код обязан НАЙТИ атрибуцию и навести
на неё фактчек; сверку «прослеживается ли» делает модель (транслитерация Lummis=Ламмис регуляркой не
берётся — см. комментарий в verify.py).
"""
from core import verify

# Реальный текст машины 15.07 (memory/drafts/2026-07-15-clarity-act-fixer.md) — выдуманная атрибуция
MACHINE_POST = (
    "**⚠️ CLARITY Act: кому выгоден провал**\n\n"
    "Сенат вернулся 13 июля. До рецесса - около 3 недель. Провалят - следующий шанс, "
    "по словам сенатора Ламмис, где-то в 2030-м\n\n"
    "Почему тупик? Trump задекларировал 1.4 млрд$ крипто-дохода за 2025 год"
)

# Реальный текст владельца 15.07 (опубликован) — атрибуций НЕТ, гейт обязан молчать
OWNER_POST = (
    "**⚠️ CLARITY Act: кому выгоден провал**\n\n"
    "Сенат вернулся 13 июля, до перерыва 3 недели. Не примут - следующий реальный шанс 2027\n\n"
    "Закон проводит черту: товар под CFTC или ценная бумага под SEC\n\n"
    "Нужно 7 демократов для 60 голосов, а они требуют этический пункт против чиновников на крипте\n\n"
    "И тут наш \"любимый\" Трамп сам стал стеной к этому закону. 1 июля вышла его декларация - "
    "1.4 млрд$ крипто-дохода за 2025, из них 635 млн$ с личного мемкоина\n\n"
    "Провал выгоден Трампу и большим банкам\n\n"
    "Деньги меняют убеждения очень быстро"
)


def test_finds_invented_attribution():
    """Главный кейс: «по словам сенатора Ламмис» обязан быть найден."""
    found = verify.find_attributions(MACHINE_POST)
    assert any("Ламмис" in f for f in found), f"выдуманная атрибуция не найдена: {found}"


def test_owner_post_has_no_false_alarm():
    """Опубликованный пост владельца атрибуций не содержит — ложных тревог быть не должно."""
    assert verify.find_attributions(OWNER_POST) == []


def test_named_subject_with_speech_verb():
    assert verify.find_attributions("Ламмис заявила, что закон пройдёт")
    assert verify.find_attributions("Saylor прогнозирует 1 млн$ за BTC")


def test_pronoun_subject_is_not_attribution():
    """Ветка (б) держится на ЗАГЛАВНОЙ букве субъекта — «он заявил» это не атрибуция к имени.

    Если сюда просочится re.IGNORECASE, тест упадёт (класс [A-ZА-ЯЁ] обессмыслится).
    """
    assert verify.find_attributions("а он заявил обратное на той же неделе") == []


def test_attribution_note_is_wired_into_prompt():
    """Подсказка кода реально доезжает до фактчека и требует ⚠️, а не ❓."""
    note = verify.ATTRIBUTION_NOTE.format(items="  • «по словам сенатора Ламмис»")
    assert "Ламмис" in note
    assert "НЕ ❓" in note


def test_verifier_prompt_has_attribution_and_subject_rules():
    assert "ШАГ 0.5" in verify.VERIFIER_SYSTEM          # правило атрибуции
    assert "ПРО ТОТ ЖЕ ПРЕДМЕТ" in verify.VERIFIER_SYSTEM  # число из чужого раздела брифа = конфликт


def test_conflict_line_outranks_clean_status():
    """⚠️-строка блокирует, даже если модель рассогласовалась и написала «СТАТУС: ЧИСТО»."""
    v = ("⚠️ АТРИБУЦИЯ «по словам сенатора Ламмис» — Ламмис в брифе нет\n"
         "ИТОГ: 0✅ / 1⚠️ / 0❓\nСТАТУС: ЧИСТО")
    assert verify.has_issues(v) is True


def test_question_marks_still_do_not_block():
    """❓ по-прежнему НЕ стоп (иначе авто-правка начнёт вырезать валидные числа — баг 30.06)."""
    v = ("❓ «оборот 150 млрд$» — в брифе нет, проверь вручную\n"
         "ИТОГ: 0✅ / 0⚠️ / 1❓\nСТАТУС: ЧИСТО")
    assert verify.has_issues(v) is False


# --- расширение охвата атрибуций (аудит 20.07: частые пропуски исходного регекса) ---

def test_finds_colon_quote_attribution():
    # «Имя: «цитата»» — атрибуция БЕЗ глагола, самый частый пропуск
    assert verify.find_attributions('Ламмис: «закон пройдёт в 2027»')
    assert verify.find_attributions('Джером Пауэлл: "ставки останутся высокими"')


def test_finds_po_dannym_and_soglasno():
    assert verify.find_attributions("по данным Glassnode, отток с бирж продолжается")
    assert verify.find_attributions("согласно отчёту JPMorgan, спрос институтов вырос")


def test_finds_added_speech_verbs():
    assert verify.find_attributions("Пауэлл предупредил о рисках рецессии")
    assert verify.find_attributions("Saylor настаивает на 1 млн$ за биткоин")


def test_colon_without_quote_is_not_attribution():
    # тег-заголовок «Act: кому выгоден» — двоеточие БЕЗ кавычки-цитаты → НЕ атрибуция (ложняк отсечён)
    assert verify.find_attributions("CLARITY Act: кому выгоден провал закона") == []
