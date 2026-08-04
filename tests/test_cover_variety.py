"""Анти-повтор КАДРА обложки (core/cover_variety.py) — чистые функции, без сети и LLM.

Ловим главное: ротация не должна предлагать схемы, которые только что использовались, а залипшие
признаки («человек-со-спины», «город-скайлайн») обязаны попадать в запрет-блок промпта. Если это
молча сломается, обложки снова сползут в один кадр — и заметим мы это только глазами через месяц.
Запуск: python -m pytest tests/test_cover_variety.py
"""
from __future__ import annotations

import json

from core import cover_variety as cv
from core import creator_tools


BANK = """# Банк

## alpha — Первая схема
Описание первой схемы.

## beta — Вторая схема
Описание второй.

## gamma — Третья схема
Описание третьей.

## delta — Четвёртая схема
Описание четвёртой.

## epsilon — Пятая схема
Описание пятой.
"""


def _bank(tmp_path):
    p = tmp_path / "cover_shots.md"
    p.write_text(BANK, encoding="utf-8")
    return p


def _log(tmp_path, records):
    p = tmp_path / "cover_log.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    return p


# ---------- банк ----------

def test_load_shots_parses_bank(tmp_path):
    shots = cv.load_shots(_bank(tmp_path))
    assert [s["slug"] for s in shots] == ["alpha", "beta", "gamma", "delta", "epsilon"]
    assert shots[0]["title"] == "Первая схема" and "первой схемы" in shots[0]["body"]


def test_load_shots_missing_file_is_soft(tmp_path):
    assert cv.load_shots(tmp_path / "нет-такого.md") == []  # без банка обложка всё равно рисуется


def test_real_bank_is_big_enough_for_veto():
    """Боевой банк обязан быть ≥ OFFER*(SHOT_WINDOW+1): иначе вето нечем исполнять и схемы вернутся
    раньше окна. Сторож на случай, если банк проредят при правке."""
    shots = cv.load_shots()
    assert len(shots) >= cv.OFFER * (cv.SHOT_WINDOW + 1), "банк кадров мал — ротация начнёт повторяться"
    assert len({s["slug"] for s in shots}) == len(shots), "дубли slug — журнал перестанет различать схемы"


# ---------- журнал ----------

def test_log_and_read_roundtrip(tmp_path):
    p = tmp_path / "log.jsonl"
    cv.log_cover(["alpha", "beta"], ["человек-со-спины", "выдуманный-признак"], "Заголовок", path=p)
    got = cv.recent(path=p)
    assert len(got) == 1
    assert got[0]["shots"] == ["alpha", "beta"]
    assert got[0]["traits"] == ["человек-со-спины"]  # признак вне словаря отброшен


def test_recent_newest_first_and_broken_lines_skipped(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_text('{"shots": ["alpha"]}\nне json совсем\n{"shots": ["beta"]}\n', encoding="utf-8")
    assert [r["shots"][0] for r in cv.recent(path=p)] == ["beta", "alpha"]


def test_recent_missing_file(tmp_path):
    assert cv.recent(path=tmp_path / "нет.jsonl") == []


def test_log_is_trimmed(tmp_path):
    p = tmp_path / "log.jsonl"
    for i in range(cv.LOG_KEEP + 10):
        cv.log_cover([f"s{i}"], [], path=p)
    assert len(p.read_text(encoding="utf-8").strip().splitlines()) == cv.LOG_KEEP


# ---------- ротация ----------

def test_pick_vetoes_recent_shots(tmp_path):
    shots = cv.load_shots(_bank(tmp_path))
    history = [{"shots": ["alpha", "beta"]}, {"shots": ["gamma"]}]
    picked = [s["slug"] for s in cv.pick_shots(shots, history)]
    assert set(picked) == {"delta", "epsilon"}  # всё из окна отсечено жёстко


def test_veto_releases_shot_after_window(tmp_path):
    """Схема возвращается в оборот, только когда окно её отпустило."""
    shots = cv.load_shots(_bank(tmp_path))
    history = [{"shots": ["beta"]}, {"shots": ["gamma"]}, {"shots": ["delta"]}]  # alpha вне окна
    assert "alpha" in [s["slug"] for s in cv.pick_shots(shots, history)]


def test_pick_is_lru_when_bank_exhausted(tmp_path):
    """Банк меньше окна — повтор неизбежен, но берём самые ДАВНИЕ, а не первые попавшиеся."""
    shots = cv.load_shots(_bank(tmp_path))
    history = [{"shots": ["alpha"]}, {"shots": ["beta"]}, {"shots": ["gamma"]},
               {"shots": ["delta"]}, {"shots": ["epsilon"]}]
    picked = [s["slug"] for s in cv.pick_shots(shots, history, offer=3)]
    # вне окна (3) только epsilon и delta — сперва самая давняя; третьей добираем следующую по давности
    assert picked == ["epsilon", "delta", "gamma"]


def test_pick_reads_old_single_shot_format(tmp_path):
    shots = cv.load_shots(_bank(tmp_path))
    picked = [s["slug"] for s in cv.pick_shots(shots, [{"shot": "alpha"}])]
    assert "alpha" not in picked  # старый формат записи тоже учитывается


def test_pick_empty_bank():
    assert cv.pick_shots([], [{"shots": ["alpha"]}]) == []


# ---------- залипшие признаки ----------

def test_stamp_trait_forbidden_after_single_use():
    stuck = cv.stuck_traits([{"traits": ["человек-со-спины", "дневной-свет"]}])
    assert "человек-со-спины" in stuck and "дневной-свет" not in stuck  # штамп — с первого раза


def test_ordinary_trait_needs_two_hits():
    one = [{"traits": ["город-скайлайн"]}, {"traits": ["природа"]}]
    assert "город-скайлайн" not in cv.stuck_traits(one)
    two = [{"traits": ["город-скайлайн"]}, {"traits": ["город-скайлайн"]}]
    assert "город-скайлайн" in cv.stuck_traits(two)


def test_stuck_is_capped_and_stamps_first():
    """Запрет не должен разрастаться: берём не больше MAX_FORBID, штампы — в начало списка."""
    many = ["город-скайлайн", "монеты-крипта", "графики-стрелки", "золото-слитки",
            "золотой-час", "средний-план", "документы", "человек-со-спины"]
    stuck = cv.stuck_traits([{"traits": many}, {"traits": many}])
    assert len(stuck) == cv.MAX_FORBID
    assert stuck[0] == "человек-со-спины"  # главный штамп не вытесняется частотой прочих


def test_stuck_ignores_beyond_window():
    old = [{"traits": []}, {"traits": []}, {"traits": []}, {"traits": ["человек-со-спины"]}]
    assert cv.stuck_traits(old) == []  # четвёртая запись уже вне окна признаков


# ---------- блоки промпта ----------

def test_build_blocks_contains_picked_and_forbidden(tmp_path):
    shots = cv.load_shots(_bank(tmp_path))
    history = [{"shots": ["alpha"], "traits": ["человек-со-спины", "город-скайлайн"]},
               {"shots": ["beta"], "traits": ["город-скайлайн"]}]
    shot_block, forbid, offered = cv.build_blocks(shots, history)
    assert offered and "alpha" not in offered
    assert f"[{offered[0]}]" in shot_block
    assert cv.TRAITS["человек-со-спины"] in forbid and cv.TRAITS["город-скайлайн"] in forbid


def test_build_blocks_no_history_no_forbid(tmp_path):
    shot_block, forbid, offered = cv.build_blocks(cv.load_shots(_bank(tmp_path)), [])
    assert shot_block and forbid == "" and len(offered) == cv.OFFER


def test_build_blocks_empty_bank():
    assert cv.build_blocks([], []) == ("", "", [])


# ---------- сборка промпта картинки ----------

def test_prompt_carries_blocks():
    out = creator_tools._build_image_prompt("Заголовок", "тело поста", "", "КАДР-ТЕСТ", "ЗАПРЕТ-ТЕСТ")
    assert "КАДР-ТЕСТ" in out and "ЗАПРЕТ-ТЕСТ" in out
    assert "Заголовок" in out and "тело поста" in out


def test_prompt_drops_empty_markers():
    """Пустые блоки не должны оставить в промпте голые «[КАДР В ЭТОТ РАЗ]» — GPT примет их за текст."""
    out = creator_tools._build_image_prompt("Заголовок", "тело поста")
    assert "[КАДР В ЭТОТ РАЗ]" not in out and "[НЕ ПОВТОРЯТЬ]" not in out
    assert "\n\n\n" not in out


def test_prompt_appends_blocks_when_template_has_no_markers():
    text = creator_tools._put_block("шаблон без маркеров", "[КАДР В ЭТОТ РАЗ]", "БЛОК")
    assert text.endswith("БЛОК")  # анти-повтор не теряется, даже если владелец переписал шаблон


def test_real_template_has_markers():
    """Боевой memory/image_prompt.md должен иметь обе точки вставки — иначе блоки уедут в хвост."""
    tpl = creator_tools.IMAGE_PROMPT.read_text(encoding="utf-8")
    assert "[КАДР В ЭТОТ РАЗ]" in tpl and "[НЕ ПОВТОРЯТЬ]" in tpl


def test_real_template_has_no_baked_frame():
    """Из шаблона убран зашитый кадр (он и был корнем повтора) — сторож против отката правки."""
    tpl = creator_tools.IMAGE_PROMPT.read_text(encoding="utf-8")
    assert "человек в раздумьях" not in tpl
    assert "симметрия лево/право" not in tpl
