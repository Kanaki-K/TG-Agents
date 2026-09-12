"""АВТОРСКИЙ МОСТ = СТОП (topic_gate.is_forced_bridge).

ЗАЧЕМ. Прогон 12.09.2026 выбрал отчёт Anthropic про кражу API-ключей и САМ написал в поле СЛАБО:
«крипто-мост в отчёте прямо не прописан — это авторский вывод». Пост вышел, владелец забраковал его
целиком: «пользы 0, вообще не ясно про что пересказать» — связь повода с читателем канала была
придумана писателем. Урок 29.07 «НЕ ПРИШИВАЙ BTC-СВЯЗКУ НАСИЛЬНО» лежал в контексте прогона активным
и был проигнорирован: правило в промпте не проверяется кодом → модель проговаривает его и идёт мимо.
Запуск: python -m pytest tests/test_topic_gate_bridge.py"""
from __future__ import annotations

from core import topic_gate as tg

VERDICT = ("ВХОД: сдвиг\n"
           "ВЫБРАН: «Anthropic раскрыла: атакующие крадут доступ к Claude»\n"
           "ДАТА ДЕЙСТВИЯ: 10.09.2026\n"
           "ПОЛЬЗА: инвестор поймёт механизм нового класса угроз\n"
           "СЛАБО: {weak}\n"
           "ОТКЛОНЕНО: FOMC — действие в будущем\n"
           "ИСЧЕРПАНО: нет\nОФФ-БРЕНД: нет")


def test_real_verdict_12_09_is_caught():
    v = VERDICT.format(weak="крипто-мост в отчёте прямо не прописан — это авторский вывод; "
                            "вытянуть через честную оговорку")
    assert "авторский" in tg.is_forced_bridge(v)


def test_other_forms_of_the_same_confession():
    for weak in ("связка с криптой притянута — в источнике её нет",
                 "привязка к биткоину натянута, автор её достроил",
                 "это авторский домысел, в отчёте про блокчейн не пишут",
                 "в отчёте прямо не прописан крипто-угол"):
        assert tg.is_forced_bridge(VERDICT.format(weak=weak)), weak


def test_strong_topic_is_not_touched():
    assert tg.is_forced_bridge(VERDICT.format(weak="нет")) == ""
    assert tg.is_forced_bridge(VERDICT.format(weak="цифра одна, надо заострить финал")) == ""


def test_only_the_weak_field_is_read():
    """Те же слова живут в разборе ОТКЛОНЁННЫХ кандидатов — ловить их там значит отклонять выбранный
    повод за чужие грехи."""
    v = ("ВХОД: сдвиг\nВЫБРАН: «Сильный повод со своей крипто-механикой»\nСЛАБО: нет\n"
         "ОТКЛОНЕНО: «RWA-отчёт» — связка с каналом авторская, в источнике не прописана\n"
         "ИСЧЕРПАНО: нет\nОФФ-БРЕНД: нет")
    assert tg.is_forced_bridge(v) == ""


def test_select_accepts_the_ban_and_says_what_to_do_instead():
    import inspect
    assert "forbid" in inspect.signature(tg.select).parameters
    src = inspect.getsource(tg.select)
    assert "ВХОД: ловушка" in src          # запрет обязан предлагать вход 2, а не тупик
    assert "НЕ бери его" in src
