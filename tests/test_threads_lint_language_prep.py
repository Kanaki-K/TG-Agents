"""Мини-флагман 24.09 (ETF): «Заголовок не про то, что банки купили биткоин. Про то, кто именно».

Две дыры сразу: антитеза с повтором ПРЕДЛОГА («не про… Про…») и заголовок, который говорит о самом себе.
Замер обеих форм: заголовки/финалы ТГ 0 из 346, Threads 0 из 447."""
from core import threads_lint as tl

BAD = ("Заголовок не про то, что банки купили биткоин. Про то, кто именно\n\n"
       "10 января 2024 SEC одобрила 11 спотовых биткоин-ETF за один день\n\n"
       "Управляющему чужими деньгами закон запрещает риск в серой зоне")


def test_prep_antithesis_in_headline_is_caught():
    head = "Одобрение ETF не про розницу. Про пенсионные фонды с триллионами\n\nтекст\n\nфинал простой"
    assert any("АНТИТЕЗА В ЗАГОЛОВКЕ" in w for w in tl.language(head))


def test_meta_headline_is_caught():
    assert any("ГОВОРИТ О САМОМ СЕБЕ" in w for w in tl.language(BAD))


def test_plain_headline_with_ne_passes():
    ok = ("Пенсионные фонды получили право держать биткоин через 11 ETF\n\n"
          "До 2024 закон не пускал их в актив без хранителя\n\nТеперь пускает")
    assert not any("ЗАГОЛОВК" in w for w in tl.language(ok))


def test_time_is_not_a_colon():
    """24.09: «с 9:30 до 16:00» считалось двумя двоеточиями — ложный остаток в отчёте."""
    t = ("Золотой ETF набрал металла больше целых государств\n\n"
         "Торговля идёт с 9:30 до 16:00 по будням\n\nФинал простой")
    assert not any("двоеточ" in w for w in tl.language(t))


# ── Валюта (01.10.2026): «250 млн австралийских долларов» → «250 млн$» ────────────────────────────

SRC_ASX = ("Семь лет. Списали около **250 млн австралийских долларов**. К 2026 фонд вырос до **~2.8 млрд$**")


def test_foreign_currency_turned_into_dollar_is_caught():
    got = tl.currency("Биржа сожгла 250 млн$ на блокчейне", SRC_ASX)
    assert got and "250 млн австралийских долларов" in got[0]


def test_real_dollars_and_kept_currency_pass():
    assert tl.currency("Фонд вырос до 2.8 млрд$", SRC_ASX) == []
    assert tl.currency("Биржа сожгла 250 млн австралийских долларов", SRC_ASX) == []


def test_currency_goes_into_the_language_round_and_the_report():
    from core import threads_creator as tc
    assert any("ВАЛЮТА" in m for m in tc._lang_marks("Биржа сожгла 250 млн$", SRC_ASX))
    assert "ВАЛЮТА" in tl.check_series(["Биржа сожгла 250 млн$ на блокчейне"], SRC_ASX)
