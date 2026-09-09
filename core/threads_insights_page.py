"""Приём страницы Insights, снятой браузером владельца (tools/threads_insights.ps1).

ЗАЧЕМ ЭТОТ ПУТЬ СУЩЕСТВУЕТ. Подписки и заходы в профиль НА ПОСТ есть в интерфейсе Threads и
отсутствуют в API — проверено перебором допустимых метрик 09.09.2026 (Meta отвечает списком, их
там нет). Владелец: «мне нужно решение на дистанцию» — то есть без ручного прокликивания. Решение:
его же Chrome раз в сутки открывает свою страницу Insights и сохраняет ОТРИСОВАННУЮ страницу в
data/incoming/. Завод забирает файл с диска. Сети со стороны завода тут нет вообще: мы читаем
файл, а не ходим в Meta.

ЧТО ЗДЕСЬ ВАЖНО. Разбор идёт не по вёрстке (она меняется каждый месяц и ломала бы всё), а по
СЛОВАМ интерфейса: «Перегляди», «Відвідування профілю», «Глядачі», «Нові читачі» и их русские и
английские варианты. Разметку мы просто срезаем, оставляя текст в том же порядке, в каком его
видит человек, — а дальше работает тот же разбор, что и для вставки из приложения
(core/threads_app_metrics). Один разборщик на два источника: меньше мест, где врать.

ОБРАБОТАННЫЕ ФАЙЛЫ УЕЗЖАЮТ в data/incoming/processed/ — иначе каждый прогон перечитывал бы всю
папку и записывал бы старые цифры поверх свежих (метрики растут со временем, это была бы порча).
"""
from __future__ import annotations

import html
import logging
import re
import shutil
from pathlib import Path

from core import config, threads_app_metrics

INCOMING = config.ROOT / "data" / "incoming"
DONE = INCOMING / "processed"
PATTERN = "insights-*.html"

_SCRIPTS = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n{3,}")


def to_text(raw_html: str) -> str:
    """Отрисованная страница → текст в том же порядке, в каком его видит человек.

    Блочные теги превращаем в перенос строки: приложение и веб выводят метрику тремя строками
    (название, число, сравнение), и именно этот порядок читает разборщик."""
    s = _SCRIPTS.sub(" ", raw_html or "")
    s = re.sub(r"</(div|p|li|section|article|h[1-6]|span|td|tr)>", "\n", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = _TAGS.sub("\n", s)
    s = html.unescape(s)
    s = "\n".join(ln.strip() for ln in s.splitlines())
    return _BLANKS.sub("\n\n", s).strip()


def ingest_file(path: Path) -> str:
    """Разобрать один снимок страницы и записать метрики. Возвращает отчёт."""
    text = to_text(Path(path).read_text(encoding="utf-8", errors="replace"))
    report = threads_app_metrics.ingest(text)
    return f"📄 {Path(path).name}\n{report}"


def intake(move: bool = True) -> str:
    """Забрать все новые снимки из data/incoming. Пусто — молчим (это штатный день без файла)."""
    files = sorted(INCOMING.glob(PATTERN))
    if not files:
        return ""
    out = []
    for f in files:
        try:
            out.append(ingest_file(f))
            if move:
                DONE.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(DONE / f.name))
        except Exception:  # noqa: BLE001 — один битый файл не отменяет остальные
            logging.getLogger(__name__).warning("снимок %s не разобрался", f.name, exc_info=True)
            out.append(f"📄 {f.name}: разобрать не смог (файл оставлен на месте)")
    return "\n".join(out)


if __name__ == "__main__":
    print(intake() or f"Новых снимков в {INCOMING} нет. Их кладёт tools/threads_insights.ps1.")
