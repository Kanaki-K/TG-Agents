"""Флагман v3 (15.09.2026): нормы длины v1, вход без цены недели, запрет прогноза цены.

Владелец забраковал флагман 15.09 целиком: вступление «Пятница, вечер. Биткоин за неделю сполз почти на
3%», финал с «цена вернётся». Замер: у постов v2.1 (потолок 2500) разбор сжался вдвое, а посты v1
(3000-3700) уходили в канал без правок. Детекторы откалиброваны на 426 постах канала: цена недели во
вступлении — 3 срабатывания (#484, #500 и пост 2025 года), прогноз — 0.
"""
import pytest

from core import creator_tools

_FOOT = "🖥 [Канал](https://t.me/x) | ▶️ [Медиа](https://linktr.ee/y) | 📱 [Notion](https://notion.so/z)"


@pytest.fixture(autouse=True)
def _pin_canon_footer(monkeypatch, tmp_path):
    f = tmp_path / "footer.md"
    f.write_text("# Канон-футер\n\n" + _FOOT + "\n", encoding="utf-8")
    monkeypatch.setattr(creator_tools, "FOOTER_FILE", f)


def _post(lead: str, body_len: int) -> str:
    # абзацы РАЗНЫЕ: одинаковые линтер вырезает как дубль сплайса, и длина схлопывается
    paras, i = [], 0
    while sum(len(p) + 2 for p in paras) < body_len:
        i += 1
        paras.append(f"Исследование номер {i} разобрало {60000 + 137 * i} семей, и выборка {i} "
                     f"отстала от рынка на {i % 9}.{i % 7} пункта за {1990 + i % 30} год")
    return f"**💎 Заголовок поста**\n\n{lead}\n\n" + "\n\n".join(paras) + f"\n\n{_FOOT}"


def _len_warns(warns):
    return [w for w in warns if "флагман КОРОТКИЙ" in w or "у СТЕНЫ" in w or "НЕ ВЛЕЗАЕТ" in w
            or "ДЛИННЫЙ" in w]


def test_v21_length_is_short_again():
    # 2300 знаков при v2.1 было «в цели» — по v3 это недобор разбора
    _, warns = creator_tools._lint(_post("20 мая 2020 года ожил кошелёк 2009 года", 2100), "флагман")
    assert any("флагман КОРОТКИЙ" in w for w in warns)


def test_v1_length_is_clean():
    _, warns = creator_tools._lint(_post("20 мая 2020 года ожил кошелёк 2009 года", 3000), "флагман")
    assert not _len_warns(warns)


def test_near_wall_warns():
    _, warns = creator_tools._lint(_post("20 мая 2020 года ожил кошелёк 2009 года", 3800), "флагман")
    assert any("у СТЕНЫ" in w for w in warns)


def test_weekly_price_hook_warns():
    lead = "Пятница, вечер. Биткоин за неделю сполз почти на 3%, до **76 000$**. Ничего не рухнуло"
    _, warns = creator_tools._lint(_post(lead, 3000), "флагман")
    assert any("ВСТУПЛЕНИЕ НА ЦЕНЕ НЕДЕЛИ" in w for w in warns)


def test_dated_event_hook_is_legit():
    # #493: реальное событие с датой — законный вход, хотя в нём цена биткоина
    lead = "6 октября 2025 года. Биткоин печатает 126 198$ - новый исторический максимум"
    _, warns = creator_tools._lint(_post(lead, 3000), "флагман")
    assert not any("ЦЕНЕ НЕДЕЛИ" in w for w in warns)


def test_price_in_body_not_lead_is_fine():
    # #495: цена в прошлом времени без «сейчас»-маркера — не крючок на цене недели
    lead = "Прошлой весной средний публичный майнер тратил около 80 000$ на один биткоин"
    _, warns = creator_tools._lint(_post(lead, 3000), "флагман")
    assert not any("ЦЕНЕ НЕДЕЛИ" in w for w in warns)


def test_hook_check_is_flagship_only():
    lead = "Вчера биткоин потерял 3.3% за сутки"
    _, warns = creator_tools._lint(_post(lead, 900), "scope")
    assert not any("ЦЕНЕ НЕДЕЛИ" in w for w in warns)


@pytest.mark.parametrize("phrase", ["Цена вернётся - она всегда возвращалась",
                                    "рано или поздно отыграет любую просадку"])
def test_price_forecast_warns(phrase):
    _, warns = creator_tools._lint(_post("20 мая 2020 года ожил кошелёк 2009 года", 3000)
                                   .replace("Исследование", phrase + "\n\nИсследование", 1), "флагман")
    assert any("ПРОГНОЗ ЦЕНЫ" in w for w in warns)


def test_recovery_arithmetic_is_not_forecast():
    # #500: «чтобы отыграть −50%, нужно +100%» — арифметика, а не обещание
    text = _post("20 мая 2020 года ожил кошелёк 2009 года", 3000).replace(
        "Исследование", "Чтобы отыграть просадку в 50%, нужен рост на 100%\n\nИсследование", 1)
    _, warns = creator_tools._lint(text, "флагман")
    assert not any("ПРОГНОЗ ЦЕНЫ" in w for w in warns)
