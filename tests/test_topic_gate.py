"""ВЫБОР ТЕМЫ scope (core/topic_gate) — единственный орган, решающий, о чём будет пост.

Переработка 31.07: сюда слиты анти-повтор, гейт свежести, суд пользы и бренд-фит. Судейское суждение
модели тут не проверяем (это живой прогон) — проверяем ПЛУМБИНГ контракта: парсинг всех полей, отказы
для панели владельца, фейл-открыто на сбое, отсутствие лишних вызовов. Запуск:
python -m pytest tests/test_topic_gate.py"""
from core import topic_gate

# Полный вердикт по контракту — как его отдаёт модель (с markdown-шумом, который она любит добавлять).
FULL = (
    "🆕 «Chainlink+Pangea» — действие от 30.07, возраст 1д; 💎; польза: как LINK зарабатывает комиссию\n"
    "🔁 «Strategy продала BTC» — действие от 12.06, возраст 49д; 🚫; польза: нет; #454 [2026-07-20]\n"
    "**ВЫБРАН: «Chainlink подключился к Pangea — как протокол зарабатывает на чужих расчётах»**\n"
    "ДАТА ДЕЙСТВИЯ: 30.07.2026\n"
    "ПОЛЬЗА: инвестор видит, откуда у LINK берётся выручка, а не только цена\n"
    "СЛАБО: нет\n"
    "ОТКЛОНЕНО: «Strategy продала BTC» — отчёт о июньском действии, 49д; «ETF-приток» — дневной поток\n"
    "ИСЧЕРПАНО: нет\n"
    "ОФФ-БРЕНД: нет"
)


# --- парсинг контракта ------------------------------------------------------------------------

def test_parses_choice_and_no_weakness():
    theme, weak = topic_gate.parse_choice(FULL)
    assert theme.startswith("Chainlink подключился к Pangea")
    assert weak == ""            # «СЛАБО: нет» — это НЕ слабость, а её отсутствие


def test_parses_weakness_when_present():
    v = "СЛАБО: повод старше 3 дней - подать через механизм\nВЫБРАН: «Индекс принятия банков»"
    theme, weak = topic_gate.parse_choice(v)
    assert theme == "Индекс принятия банков"
    assert "старше 3 дней" in weak


def test_takes_last_choice_line():
    v = "ВЫБРАН: «черновик»\nещё думаю...\nВЫБРАН: «финальный повод»"
    assert topic_gate.parse_choice(v)[0] == "финальный повод"


def test_no_contract_returns_empty():
    # сбой/непарсибельно → ('', '') → конвейер пишет по брифу сам (пост обязан быть)
    assert topic_gate.parse_choice("бла-бла без вердикта") == ("", "")
    assert topic_gate.parse_choice("") == ("", "")
    assert topic_gate.parse_choice(None) == ("", "")


def test_parses_action_date_not_publication_date():
    # ГЛАВНОЕ правило после провала 31.07: возраст повода = возраст ДЕЙСТВИЯ, не отчёта о нём
    assert topic_gate.parse_action_date(FULL) == "30.07.2026"
    assert topic_gate.parse_action_date("ДАТА ДЕЙСТВИЯ: не определена") == ""
    assert topic_gate.parse_action_date("") == ""


def test_parses_usefulness_line():
    assert "откуда у LINK" in topic_gate.parse_usefulness(FULL)


def test_parses_rejected_for_owner_panel():
    # предохранитель владельца: отклонённые поводы видны строкой, а не только в полном логе
    rej = topic_gate.parse_rejected(FULL)
    assert len(rej) == 2
    assert "отчёт о июньском действии" in rej[0]
    assert "дневной поток" in rej[1]


def test_rejected_empty_when_none():
    assert topic_gate.parse_rejected("ОТКЛОНЕНО: нет") == []
    assert topic_gate.parse_rejected("ВЫБРАН: «x»") == []


def test_flags_exhausted_and_offbrand_with_markdown():
    assert topic_gate.is_exhausted(FULL) is False
    assert topic_gate.is_offbrand(FULL) is False
    assert topic_gate.is_exhausted("**ИСЧЕРПАНО: да**") is True      # markdown-обёртку терпим
    assert topic_gate.is_offbrand("ОФФ-БРЕНД: да") is True
    assert topic_gate.is_exhausted("") is False                       # строки нет → не форсим разведку


# --- вызов ------------------------------------------------------------------------------------

def test_empty_brief_no_model_call(monkeypatch):
    calls = []
    monkeypatch.setattr(topic_gate.llm, "reply", lambda *a, **k: calls.append(1))
    theme, weak, verdict = topic_gate.select("")
    assert (theme, weak) == ("", "")
    assert calls == []
    assert "выбирать не из чего" in verdict


def test_select_parses_model_verdict(monkeypatch):
    monkeypatch.setattr(topic_gate.llm, "reply", lambda *a, **k: (FULL, None))
    theme, _weak, verdict = topic_gate.select("повод один", today="2026-07-31", digest="")
    assert theme.startswith("Chainlink")
    assert verdict == FULL


def test_select_failopen_on_model_error(monkeypatch):
    # сбой модели → ('', '', причина): конвейер НЕ падает, писатель берёт повод из брифа сам
    def boom(*a, **k):
        raise RuntimeError("api down")
    monkeypatch.setattr(topic_gate.llm, "reply", boom)
    theme, weak, verdict = topic_gate.select("повод", today="2026-07-31", digest="")
    assert (theme, weak) == ("", "")
    assert "не удался" in verdict


def test_select_failopen_when_channel_digest_unreadable(monkeypatch):
    # сводка канала не прочиталась → выбираем БЕЗ неё, но прогон не роняем
    seen = {}

    def boom_digest(**k):
        raise RuntimeError("нет выгрузки")

    def cap(model, system, hist, user, tools, disp, key, thinking, **k):
        seen["user"] = user
        return (FULL, None)
    monkeypatch.setattr(topic_gate.analytics, "topics_digest", boom_digest)
    monkeypatch.setattr(topic_gate.llm, "reply", cap)
    theme, _w, _v = topic_gate.select("повод", today="2026-07-31")
    assert theme.startswith("Chainlink")
    assert "сводка канала недоступна" in seen["user"]


def test_select_feeds_raw_brief_digest_recent_and_brand(monkeypatch):
    """Орган обязан видеть ВСЁ сразу — в этом вся переработка.

    Раньше гейт получал пересказ дедупа вместо сырого брифа, не видел сводку канала и судил пользу
    вслепую; три органа знали разные куски и приходили к разным ответам. Тест сторожит вход.
    """
    seen = {}

    def cap(model, system, hist, user, tools, disp, key, thinking, **k):
        seen["user"] = user
        return (FULL, None)
    monkeypatch.setattr(topic_gate, "_off_brand_block", lambda: "- Шиткоин-памп, мемкоины ради иксов")
    monkeypatch.setattr(topic_gate.llm, "reply", cap)
    topic_gate.select("СЫРОЙ повод от разведки", today="2026-07-31",
                      digest="#454 [2026-07-20] Orange Juice - BTC-казна",
                      recent=["Gram-кошелёк"])
    u = seen["user"]
    assert "СЫРОЙ повод от разведки" in u          # бриф, а не чужой пересказ
    assert "#454" in u                              # сводка канала (анти-повтор)
    assert "Gram-кошелёк" in u                      # недавно написанное
    assert "мемкоин" in u                           # бренд-фит
    assert "2026-07-31" in u                        # дата — без неё не посчитать возраст действия


# --- бренд-секция -----------------------------------------------------------------------------

def test_off_brand_block_parses_only_that_section(monkeypatch, tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "brand.md").write_text(
        "# Бренд\n\n## Голос\nживой голос\n\n## Что НЕ наше (Скаут понижает)\n"
        "- Шиткоин-памп, мемкоины ради иксов; сигналы/скальпинг.\n- Дневной шум без структуры.\n\n"
        "## Аудитория\nDCA-долгосрочник\n", encoding="utf-8")
    monkeypatch.setattr(topic_gate.config, "ROOT", tmp_path)
    block = topic_gate._off_brand_block()
    assert "мемкоин" in block.lower() and "шум" in block.lower()
    assert "живой голос" not in block and "DCA" not in block


def test_off_brand_block_missing_file_failopen(monkeypatch, tmp_path):
    monkeypatch.setattr(topic_gate.config, "ROOT", tmp_path)
    assert topic_gate._off_brand_block() == ""


# --- «как БУДЕТ» — не повод (владелец 03.08) ---------------------------------------------------

def test_contract_bans_future_action():
    # 03.08 гейт взял BIP-110 («окно откроется 7-15 августа»), сам же назвав это будущим событием,
    # и отложил в резерв повод с действием «сегодня». Правило должно стоять в контракте явно.
    s = topic_gate._SYSTEM
    assert "ЕЩЁ НЕ ПРОИЗОШЛО" in s
    assert "BIP-110" in s                                   # разобранный случай, а не абстракция
    assert "самый низ" in s                                 # ранг: ниже старья
    assert "ИСЧЕРПАНО: да" in s.split("ГРАНИЦА")[1][:600]   # только будущее → идём за свежей разведкой


def test_contract_keeps_done_action_with_later_effect():
    # закон подписан вчера, вступает в силу в январе — это СЛУЧИВШЕЕСЯ действие, повод годен
    assert "ГРАНИЦА" in topic_gate._SYSTEM
    assert "вступает в силу" in topic_gate._SYSTEM
