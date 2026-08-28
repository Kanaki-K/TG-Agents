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
    # медиана 17 принятых постов с 01.07 — 1286 знаков с футером; такой пост длинным звать нельзя
    post = HEAD + "\n\n" + ("Механика повода объясняется здесь по-человечески. " * 20)
    clean, warns = ct._lint(post, "scope")
    assert 1200 < _n(clean) < ct.SCOPE_TOTAL_CAP, f"тест построен неверно: {_n(clean)}"
    assert not _len_warn(warns)


def test_real_bloat_still_flagged():
    post = HEAD + "\n\n" + ("Механика повода объясняется здесь по-человечески. " * 24)
    clean, warns = ct._lint(post, "scope")
    assert ct.SCOPE_TOTAL_CAP < _n(clean) < ct.SCOPE_BLOAT_CAP, f"тест построен неверно: {_n(clean)}"
    assert _len_warn(warns), "совет по длине выше цели остаётся — он просто перестал быть вечным"


def test_bloat_cap_keeps_gap_above_target():
    # 10.08: между «длинновато» и АМПУТАЦИЕЙ должен быть зазор, иначе резчик идёт сразу за советом.
    # И случай-эталон раздувания (1770, урок 24.07) обязан по-прежнему попадать под ⛔.
    assert ct.SCOPE_BLOAT_CAP - ct.SCOPE_TOTAL_CAP >= 200
    assert ct.SCOPE_BLOAT_CAP < 1770


# --- «это не главное» = лишний блок (второй заход 19.08: «скоуп раздулся») ---

def test_self_dismissal_flagged():
    # ровно случай поста про SEC: целый абзац про два коридора привлечения, закрытый признанием,
    # что деньги тут не главное. 160 знаков второй темы в мини-формате
    post = (HEAD + "\n\n"
            "Теперь два коридора привлечь без полной регистрации: до 5 млн$ за 4 года для стартапа "
            "и до 75 млн$ в год для проекта покрупнее. Но деньги тут не главное\n\n"
            "Главное - защищённая гавань\n")
    _, warns = ct._lint(post, "scope")
    assert any("объявил предыдущий блок неглавным" in w for w in warns)


def test_midline_transition_not_flagged():
    # «Но важнее другое: …» ПОСРЕДИ абзаца — обычный переход, а не отмена блока (пост #125)
    post = (HEAD + "\n\n"
            "Кошельки, лендинги, мосты живут на L1-сетях. Но важнее другое: большинство сделок "
            "уходит на второй слой, и комиссия там в сто раз меньше\n")
    _, warns = ct._lint(post, "scope")
    assert not any("объявил предыдущий блок неглавным" in w for w in warns)


def test_aim_is_below_ceiling():
    # ориентир ≠ потолок: писателю показываем медиану принятых постов, а не границу спора
    assert ct.SCOPE_BODY_AIM < ct.SCOPE_BODY_MAX
    assert ct.SCOPE_PARA_AIM < ct._PARA_MEDIAN_MAX


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


# --- КРУГ ПРАВКИ 2FA РАСТИТ ПОСТ (баг 28.08) ---------------------------------------------------
# Прогон 28.08 (Solana): автор отдал чистый драфт на 1356, затем два круга правки фактов дали 1375 и
# 1382 — каждый выше потолка 1350, и ни один об этом не услышал: счётчик кругов к тому моменту молчал
# навсегда (правило 19.08 «с круга 3 не повторяем»). Правка не знает, что удлиняет, — про длину в
# вердикте 2FA нет ни слова. Тишина теперь обусловлена: пост похудел или стоит — молчим; пост ВЫРОС
# и висит выше потолка — говорим ровно про прирост, не требуя «сократить пост».

def _grow_to_rounds_3plus():
    """Три круга автора со снижением — совет к этому моменту снят (состояние из прогона 28.08)."""
    ct._LEN_ROUNDS.clear()
    for ln in (1573, 1500, 1356):
        ct._len_advice_rounds("scope", "я" * ln, [ct._LEN_ADVICE_TAG + f": {ln} знаков"])


def test_fix_round_that_grows_post_above_cap_speaks_up():
    _grow_to_rounds_3plus()
    warns = ct._len_advice_rounds("scope", "я" * 1382, [ct._LEN_ADVICE_TAG + ": 1382 знака"])
    assert any(w.startswith("ПРАВКА РАСТИТ ПОСТ") for w in warns), "рост выше потолка обязан быть назван"
    assert not _len_warn(warns), "это ДРУГАЯ претензия, старый совет по длине не возвращаем"


def test_growth_warning_names_both_numbers():
    _grow_to_rounds_3plus()
    warns = ct._len_advice_rounds("scope", "я" * 1382, [ct._LEN_ADVICE_TAG + ": 1382 знака"])
    w = next(w for w in warns if w.startswith("ПРАВКА РАСТИТ ПОСТ"))
    assert "1356" in w and "1382" in w, "правка должна видеть, ОТ ЧЕГО и ДО ЧЕГО выросла"
    assert "вето" in w, "потолок остаётся советом (10.08) — не влезло, выдавай как есть"


def test_shrinking_fix_round_stays_silent():
    """Правило 19.08 в силе: пост не растёт — про длину молчим, иначе автор режет служебные слова."""
    _grow_to_rounds_3plus()
    warns = ct._len_advice_rounds("scope", "я" * 1340, [ct._LEN_ADVICE_TAG + ": 1340 знаков"])
    assert warns == []


def test_growth_below_cap_stays_silent():
    """Вырос, но в пределах формата — не повод дёргать автора: потолок и есть граница разговора."""
    ct._LEN_ROUNDS.clear()
    for ln in (1573, 1400, 1200):
        ct._len_advice_rounds("scope", "я" * ln, [ct._LEN_ADVICE_TAG + f": {ln} знаков"])
    warns = ct._len_advice_rounds("scope", "я" * 1260, [ct._LEN_ADVICE_TAG + ": 1260 знаков"])
    assert warns == []


def test_growth_check_does_not_touch_other_warns():
    _grow_to_rounds_3plus()
    other = "scope: ФИЛЛЕР-ПОДВОДКА (нашёл «стоит отметить»)"
    warns = ct._len_advice_rounds("scope", "я" * 1382, [ct._LEN_ADVICE_TAG + ": длинно", other])
    assert other in warns and len(warns) == 2
