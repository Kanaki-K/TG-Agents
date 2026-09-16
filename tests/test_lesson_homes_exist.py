"""ДОМ ПРАВИЛА ОБЯЗАН СУЩЕСТВОВАТЬ (16.09.2026) — страж против тихой потери механизмов.

ЗАЧЕМ. Владелец 16.09: «почему блять потерялся антиповтор дедуп, правила на Вы, стиль писания? Должен
был меняться только файл правил написания!» Аудит показал, что правила и правда терялись — и всегда
одинаково: текст правила переезжал при рефакторинге, а исполнительное звено оставалось позади.

ТРИ ДОКАЗАННЫХ СЛУЧАЯ:
1. 31.07 (f8e279c) четыре судьи темы слиты в один орган. Машинный вердикт «СТАТУС: ПОВТОР», который
   останавливал конвейер, исчез; значки 🔁 модель ставила ещё полтора месяца, а код их не читал вообще.
   Итог — дубль про сеть Arc 16.09.
2. 12.09 (75bc59b) дистилляция уроков 56→30. Правило отбора было честным: выпускается только урок,
   «чьё правило доказуемо живёт в другом доме». Но существование дома никто не ПРОВЕРЯЛ — и один урок
   уехал в дом «core/dedup, окно 4 недели», которого не было с 31.07.
3. Правило «Вы» (v2, 10.09) кодом не подкреплялось НИ ДНЯ — проверено по всей истории репозитория.

ЧТО ДЕЛАЕТ ЭТОТ ТЕСТ. Каждая строка уроков, объявившая «⟶ дом: …», проверяется на то, что дом
существует: §-раздел — в своде, имя кода — в коде. Не найден — тест падает и называет строку. Это
дешёвая страховка ровно от того класса, который стоил трёх пробоин.
Запуск: python -m pytest tests/test_lesson_homes_exist.py"""
from __future__ import annotations

import re

from core import config

LESSONS = config.ROOT / "memory" / "scope_lessons.md"
MANUAL = config.ROOT / "memory" / "scope_manual.md"
CODE_DIRS = ("core", "connectors", "tools")

# «⟶ _дом: линтер _CLIPPED_ANTI_» / «⟶ _дом: §1.5 тест образа №1_» — хвост урока после дистилляции 12.09.
_HOME_RE = re.compile(r"дом:\s*([^_\n]+)", re.IGNORECASE)
# Имя кода в доме: идентификатор с подчёркиванием/точкой (_CLIPPED_ANTI, core/dedup, scope_meta_defects).
_CODE_NAME_RE = re.compile(r"\b([a-z_][a-z0-9_]{4,}(?:\.[a-z_][a-z0-9_]+)?|_[A-Z][A-Z0-9_]{3,})\b")
_SECTION_RE = re.compile(r"§\s*(\d+(?:\.\d+)?)")


def _read(p) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _all_code() -> str:
    out = []
    for d in CODE_DIRS:
        root = config.ROOT / d
        if root.exists():
            out.extend(_read(f) for f in root.rglob("*.py"))
    return "\n".join(out)


def _homes() -> list[str]:
    return [m.group(1).strip() for m in _HOME_RE.finditer(_read(LESSONS))]


def test_lessons_file_declares_homes():
    """Сам формат «⟶ дом: …» должен быть жив — иначе тест молча проверяет пустоту."""
    assert _homes(), "в scope_lessons.md не осталось ни одной пометки «дом:» — страж ослеп"


def test_every_declared_section_home_exists():
    """Дом вида «§1.5» обязан быть разделом свода."""
    manual = _read(MANUAL)
    assert manual, "свод scope_manual.md не прочитался"
    missing = []
    for home in _homes():
        for sec in _SECTION_RE.findall(home):
            # В своде разделы пишутся как «## 1.5 …» / «## 4.5 …»; ищем начало строки-заголовка.
            if not re.search(rf"^#+\s*{re.escape(sec)}[\s.]", manual, re.M):
                missing.append(f"§{sec} (из «{home}»)")
    assert not missing, "уроки ссылаются на разделы свода, которых нет: " + "; ".join(missing)


def test_every_declared_code_home_exists():
    """Дом вида «линтер _CLIPPED_ANTI» / «core/dedup» обязан найтись в коде.

    Именно эта проверка поймала бы потерю анти-повтора: урок уехал в «core/dedup, окно 4 недели»,
    когда окна там уже не было."""
    code = _all_code()
    assert code, "исходники не прочитались"
    missing = []
    for home in _homes():
        if "линтер" not in home.lower() and "код" not in home.lower() and "/" not in home:
            continue                      # дом не кодовый (свод/мануал) — проверяется тестом выше
        for name in _CODE_NAME_RE.findall(home):
            probe = name.split("/")[-1].split(".")[-1]
            if len(probe) < 5:
                continue
            if probe not in code:
                missing.append(f"«{probe}» (из «{home}»)")
    assert not missing, ("уроки ссылаются на код, которого нет — правило осиротело: "
                         + "; ".join(missing))


def test_dedup_window_home_is_honest():
    """Регресс ровно того случая: если окно анти-повтора снова назовут домом в core/dedup, тест упадёт.

    Окно живёт в topic_gate (WINDOW_WEEKS / REPEAT_SCAN_WEEKS), и в core/dedup стоит явная отсылка
    туда. Урок, указывающий домом core/dedup, теперь обязан быть переписан на topic_gate."""
    dedup = _read(config.ROOT / "core" / "dedup.py")
    assert "topic_gate" in dedup, "core/dedup потерял отсылку к настоящему дому окна анти-повтора"
    for home in _homes():
        if "dedup" in home.lower() and "окно" in home.lower():
            raise AssertionError(f"урок всё ещё называет домом окна core/dedup: «{home}» — "
                                 "окно переехало в topic_gate 31.07.2026")
