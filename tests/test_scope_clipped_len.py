"""Обрубленная подача короткого поста — разбор правки владельца 19.08 (пост про SEC / Regulation
Crypto Assets).

Владелец вернул руками ТРИ проглоченных слова: «предложение, не закон» → «а не закон»;
«Споткнулся об условие» → «Если споткнулся»; «докажи, что ты не бумага» → «не ценная бумага».
Причина одна: пост шёл на 1545 при тогдашней цели 1250, линтер повторил «длинноват» на всех трёх
кругах сохранения, резать было нечего (длину держало объяснение предмета — случай 10.08), и автор
ужимал единственное оставшееся — служебные слова. Экономия ~15 знаков из 295, цена — тон.

Здесь закрыты три дырки: цель длины перекалибрована по ЗАМЕРУ принятых постов, повторный совет по
длине гаснет, а клип союза «а» ловится отдельно.
Запуск: python -m pytest tests/test_scope_clipped_len.py"""
from core import creator_tools as ct

HEAD = "**📊 SEC впервые показала токенам выход из-под статуса ценной бумаги**"


def _n(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _len_warn(warns):
    return [w for w in warns if w.startswith(ct._LEN_ADVICE_TAG)]


def _clip_warn(warns):
    return [w for w in warns if "союз «а» выпал" in w]


# --- клипнутая антитеза «X, не Y» посреди фразы ---

def test_clipped_antithesis_detected():
    post = (HEAD + "\n\n"
            "И это пока предложение, не закон: впереди 60 дней комментариев и месяцы правок\n")
    _, warns = ct._lint(post, "scope")
    assert _clip_warn(warns), "проглоченный союз «а» должен быть помечен"


def test_owner_punch_form_not_flagged():
    # ЖИВОЙ оборот владельца: бессоюзная антитеза ЗАКРЫВАЕТ строку — это панч, а не клип.
    # Замер по 323 постам канала: у него она всегда стоит в конце («Это норма, не исключение»).
    post = (HEAD + "\n\n"
            "Биткоин может падать на 50-80% внутри цикла. Это норма, не исключение\n\n"
            "Реальная выручка идёт на выкуп токенов, дефляция. Рынок покупает истории, не код\n")
    _, warns = ct._lint(post, "scope")
    assert not _clip_warn(warns), "панч в конце строки — приём владельца, претензий быть не должно"


def test_plain_negation_with_verb_not_flagged():
    # «…, не договорились - …» — обычное отрицание с глаголом, а не половина антитезы (пост #460):
    # тире дальше по строке есть, но пропущенного союза нет, и претензии быть не должно
    post = (HEAD + "\n\n"
            "Те, кто платит за защиту, не договорились - и это главный риск для держателя\n")
    _, warns = ct._lint(post, "scope")
    assert not _clip_warn(warns)


def test_clip_detector_is_scope_only():
    # у флагмана свой регистр и своя длина — детектор мини-формата туда не лезет
    post = (HEAD + "\n\n"
            "И это пока предложение, не закон: впереди 60 дней комментариев\n")
    _, warns = ct._lint(post, "флагман")
    assert not _clip_warn(warns)


# --- «N из N» ---

def test_equal_count_flagged():
    post = HEAD + "\n\nSEC предложила новые правила. Проголосовали **3 из 3** комиссаров\n"
    _, warns = ct._lint(post, "scope")
    assert any("не несёт информации" in w for w in warns)


def test_real_ratio_not_flagged():
    # реальные пропорции из постов канала: 9 из 18 участников, 8 из 9 заседаний
    post = HEAD + "\n\nТеперь 9 из 18 участников закладывают снижение, а BTC падал после 8 из 9 заседаний\n"
    _, warns = ct._lint(post, "scope")
    assert not any("не несёт информации" in w for w in warns)


# --- перекалибровка длины по замеру принятых постов ---

def test_accepted_length_no_longer_flagged():
    # медиана принятых постов АВГУСТА — 1421 знак с футером; такой пост линтер звать длинным не должен
    post = HEAD + "\n\n" + ("Механика повода объясняется здесь по-человечески. " * 23)
    clean, warns = ct._lint(post, "scope")
    assert 1300 < _n(clean) < ct.SCOPE_TOTAL_CAP, f"тест построен неверно: {_n(clean)}"
    assert not _len_warn(warns)


def test_real_bloat_still_flagged():
    post = HEAD + "\n\n" + ("Механика повода объясняется здесь по-человечески. " * 26)
    clean, warns = ct._lint(post, "scope")
    assert ct.SCOPE_TOTAL_CAP < _n(clean) < ct.SCOPE_BLOAT_CAP, f"тест построен неверно: {_n(clean)}"
    assert _len_warn(warns), "совет по длине выше цели остаётся — он просто перестал быть вечным"


def test_bloat_cap_keeps_gap_above_target():
    # 10.08: между «длинновато» и АМПУТАЦИЕЙ должен быть зазор, иначе резчик идёт сразу за советом.
    # И случай-эталон раздувания (1770, урок 24.07) обязан по-прежнему попадать под ⛔.
    assert ct.SCOPE_BLOAT_CAP - ct.SCOPE_TOTAL_CAP >= 200
    assert ct.SCOPE_BLOAT_CAP < 1770


# --- совет по длине не повторяется третий раз ---

def test_first_round_keeps_advice():
    ct._LEN_ROUNDS.clear()
    warns = ct._len_advice_rounds("scope", "я" * 1600, [ct._LEN_ADVICE_TAG + ": 1600 знаков"])
    assert _len_warn(warns), "первый круг — обычный совет"


def test_second_round_without_real_cut_says_stop():
    ct._LEN_ROUNDS.clear()
    ct._len_advice_rounds("scope", "я" * 1600, [ct._LEN_ADVICE_TAG + ": 1600 знаков"])
    warns = ct._len_advice_rounds("scope", "я" * 1590, [ct._LEN_ADVICE_TAG + ": 1590 знаков"])
    assert any(w.startswith("СТОП по длине") for w in warns), "10 знаков за круг = шлифовка слов"
    assert not _len_warn(warns), "прежний совет должен быть ЗАМЕНЁН, а не продублирован"


def test_second_round_with_real_cut_keeps_advice():
    ct._LEN_ROUNDS.clear()
    ct._len_advice_rounds("scope", "я" * 1900, [ct._LEN_ADVICE_TAG + ": 1900 знаков"])
    warns = ct._len_advice_rounds("scope", "я" * 1700, [ct._LEN_ADVICE_TAG + ": 1700 знаков"])
    assert _len_warn(warns), "снял 200 знаков — режет блоками, не мешаем"


def test_third_round_drops_advice():
    ct._LEN_ROUNDS.clear()
    for ln in (1600, 1590, 1585):
        warns = ct._len_advice_rounds("scope", "я" * ln, [ct._LEN_ADVICE_TAG + f": {ln} знаков"])
    assert warns == [], "третий круг: претензия только портит подачу — снимаем совсем"


def test_rounds_do_not_touch_other_warns():
    ct._LEN_ROUNDS.clear()
    other = "scope: ФИЛЛЕР-ПОДВОДКА (нашёл «стоит отметить»)"
    for ln in (1600, 1590, 1585):
        warns = ct._len_advice_rounds("scope", "я" * ln, [ct._LEN_ADVICE_TAG + ": длинно", other])
    assert warns == [other], "гасим только совет по длине, остальные замечания живут"
