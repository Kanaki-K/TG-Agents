"""Проверки постов Threads по замеру виральности 09.09.2026.

Тесты держат ровно то, ради чего линтер написан: он ловит дно корпуса и МОЛЧИТ на лидерах.
Тексты ниже — настоящие посты из выгрузки, не выдуманные: правило, проверенное на придуманном
примере, ничего не гарантирует на живом."""
from core import threads_lint as L

# Лидеры корпуса (15 159 и 3128 показов) — линтер обязан молчать.
MANGO = ("Биржу ограбили на 110 млн$, не взломав ни строчки кода\n\n"
         "11 октября 2022. Трейдер заходит на криптобиржу Mango, кладёт 5 млн$ и открывает "
         "встречные позиции по её токену\n\nВзломали не биржу. Взломали то, что ей сказали")
MINERS = ("20% майнеров в убытке\n\nJPMorgan выкатил жёсткую записку. Себестоимость одного "
          "биткоина около 78 000$. Рыночная цена сегодня 58 355$")
# Дно корпуса (50 и 32 показа).
ADVICE = ("Перед любым доходом есть один вопрос - кто платит?\n\n"
          "Протокол просто печатает новые токены и раздаёт их тебе. Ты держишь больше монет")
SOPR = ("Цена говорит сколько монета стоит. Но не что чувствует продавец\n\n"
        "Есть метрика, которая смотрит не на график, а в карман каждого, кто продаёт")


def test_leaders_pass_clean():
    assert L.check(MANGO) == []


def test_short_headline_with_a_stake_is_not_a_complaint():
    """«20% майнеров в убытке» — 21 знак и втрое выше типичного охвата. Линтер не спорит с лидером:
    короткий заголовок плох тем, что в него не влезает ставка, а здесь она влезла."""
    assert L.check(MINERS) == []


def test_missing_stake_is_caught():
    problems = L.check(SOPR)
    assert any("НЕТ ставки" in p for p in problems)


def test_ty_is_caught_and_named_by_price():
    problems = L.check(ADVICE)
    assert any("«ты» в тексте" in p and "÷2.8" in p for p in problems)


def test_address_in_headline_is_caught():
    problems = L.check("Как ты можешь доказать, что автор твоего аккаунта - человек, а не бот?")
    assert any("в ЗАГОЛОВКЕ" in p for p in problems)


def test_emoji_first_is_caught():
    problems = L.check("📊 Хейтили биткоин, а теперь зарабатывают на крипте\n\nДжеймс Даймон годами "
                       "звал биткоин мошенничеством")
    assert any("НАЧАЛЕ заголовка" in p for p in problems)


def test_link_and_hashtag_are_hard_stops():
    assert any("⛔" in p for p in L.check("Заголовок про потерю 10 млн$\n\nhttps://t.me/канал"))
    assert any("⛔" in p for p in L.check("Заголовок про потерю 10 млн$\n\nтекст #крипта"))


def test_series_report_counts_posts_without_a_stake():
    report = L.check_series([MANGO, SOPR, ADVICE])
    assert "Постов без своей ставки: 2 из 3" in report
    assert "[1/3]" not in report          # к чистому посту претензий нет


def test_clean_series_says_nothing():
    assert L.check_series([MANGO, MINERS]) == ""
