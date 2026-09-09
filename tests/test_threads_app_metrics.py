"""Приём ручных цифр из приложения Threads (подписки/заходы в профиль — их нет в API).

Блок ниже — настоящая вставка владельца от 09.09.2026, украинский интерфейс. Тесты держат то,
на чём разбор реально ломается: шапка приложения не должна попасть в текст поста (иначе пост не
опознается), число стоит СТРОКОЙ НИЖЕ названия метрики, а «Відвідування профілю» не должно быть
съедено более коротким «Перегляди»."""
import json

import pytest

from core import threads_app_metrics as A

BLOCK = """kanaki.crypto
22 год
Биткоин чувствует деньги раньше почти всех активов

Когда в системе больше свободных денег, они текут туда, где доходность выше - на самый край риска

Направление денег показывает, куда дует ветер. Но не когда поднимется волна
Зведення
Перегляди
309
Як зазвичай
Відвідування профілю
4
Вище
Глядачі
276
Як зазвичай
Нові читачі
1
Вище"""


@pytest.fixture
def store(tmp_path, monkeypatch):
    posts = [{"id": "777", "date": "2026-09-08T16:00:00+0000",
              "text": "Биткоин чувствует деньги раньше почти всех активов\n\nКогда в системе больше "
                      "свободных денег, они текут туда, где доходность выше - на самый край риска\n\n"
                      "Направление денег показывает, куда дует ветер. Но не когда поднимется волна"},
             {"id": "888", "date": "2026-09-07T16:00:00+0000", "text": "Защита сработала идеально"}]
    (tmp_path / "posts.json").write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(A, "THREADS_POSTS", tmp_path / "posts.json")
    monkeypatch.setattr(A, "STORE", tmp_path / "app.json")
    return tmp_path


def test_parses_all_four_numbers():
    b = A.parse_block(BLOCK)
    assert b["views"] == 309 and b["viewers"] == 276
    assert b["profile_visits"] == 4 and b["new_followers"] == 1


def test_app_header_is_not_part_of_the_post_text():
    """Ник и «22 год» в тексте сломали бы опознание поста — сходство считается по словам."""
    text = A.parse_block(BLOCK)["text"]
    assert text.startswith("Биткоин чувствует")
    assert "kanaki" not in text and "22 год" not in text


def test_ingest_binds_numbers_to_the_right_post(store):
    report = A.ingest(BLOCK)
    assert "2026-09-08" in report
    saved = json.loads((store / "app.json").read_text(encoding="utf-8"))
    assert saved["777"]["new_followers"] == 1
    assert saved["777"]["source"].startswith("приложение")
    assert saved["777"]["age_days_at_snap"] >= 0        # цифры растут — возраст на момент снятия важен


def test_unknown_post_is_reported_not_guessed(store):
    out = A.ingest("Пост, которого у нас нет\nЗведення\nПерегляди\n10\nЯк зазвичай")
    assert out.startswith("❓")
    assert not (store / "app.json").exists()


def test_two_blocks_at_once(store):
    second = BLOCK.replace("Биткоин чувствует деньги раньше почти всех активов",
                           "Защита сработала идеально").replace("309", "100")
    out = A.ingest(BLOCK + "\n" + second)
    assert out.count("✅") == 2


def test_funnel_report_computes_both_conversions(store):
    A.ingest(BLOCK)
    text = A.funnel_report()
    assert "1.4%" in text          # 4 захода в профиль из 276 зрителей
    assert "25%" in text           # 1 подписка из 4 заходов


def test_empty_store_asks_for_data(store):
    assert "пока нет" in A.funnel_report()
