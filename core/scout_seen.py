"""Watermark Скаута — память «что уже читал», чтобы не гонять одно и то же неделями.

ЗАЧЕМ. Коннекторы сбора (X/TG/RSS) всегда тянут последние N записей — без памяти.
Значит каждый прогон Скаут перечитывает те же твиты Hayes и те же посты @crypto_hd →
и повтор тем в брифах, и лишние токены дорогой модели. Этот модуль хранит, ЧТО уже
показывали Скауту, и отфильтровывает это из следующего скана. Побочный эффект — тот самый
«кулдаун»: заглохший источник сам собой перестаёт занимать контекст (нечего показать).

КАК (осознанно просто и безопасно):
  • Идентичность записи, НЕ дата. Ссылка (RSS), URL твита (X), channel#id (TG) — стабильны
    и не требуют парсинга разнобойных форматов дат. Меньше кода = меньше багов.
  • Читаем — НЕ мутируем. filter_new() только помечает новое в ПРОЦЕССНЫЙ буфер `_pending`,
    но на диск не пишет. Поэтому повторный вызов того же скана В ОДНОМ прогоне стабилен
    (сверяемся с зафиксированным watermark, а не с тем, что сами же сейчас прочитали).
  • Фиксируем — при save_brief. commit() сливает `_pending` в файл. Это точка «разведка
    собрана». Если прогон упал/без брифа — watermark НЕ двигается, запись всплывёт снова
    (безопасный отказ: лучше показать повторно, чем потерять).
  • Никогда не роняет скан: любая ошибка → пропускаем всё как есть.

Файл: data/scout_seen.json — {источник: [последние ~SEEN_CAP идентичностей]}.
"""
from __future__ import annotations

import json

from core import config

SEEN_FILE = config.ROOT / "data" / "scout_seen.json"
SEEN_CAP = 300  # сколько последних идентичностей помним на источник (кап размера файла)

# Процессный буфер: {ключ_источника: {идентичности, увиденные с последнего commit}}.
# Живёт в памяти процесса, на диск попадает только через commit().
_pending: dict[str, set] = {}


def _load() -> dict:
    try:
        return json.loads(SEEN_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        SEEN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8", newline="\n")
    except Exception:
        pass  # не роняем Скаута из-за проблемы записи watermark


def filter_new(items: list[dict], key_field: str, id_fn) -> list[dict]:
    """Оставить только записи, которых Скаут ещё НЕ видел (по идентичности).

    items    — список dict от коннектора (может содержать {'error': ...} — их пропускаем как есть).
    key_field — поле-ключ источника ('name' для RSS, 'channel' для TG, 'handle' для X).
    id_fn    — функция item→стабильная идентичность (ссылка/URL/channel#id).

    Идентичности новых записей копятся в `_pending` (на диск не пишем — это делает commit()).
    На любой сбой возвращаем items как есть — фильтр не должен ломать разведку.
    """
    try:
        seen = _load()
        out: list[dict] = []
        for it in items:
            if not isinstance(it, dict) or it.get("error"):
                out.append(it)  # ошибки/служебное — всегда показываем
                continue
            key = str(it.get(key_field, "?"))
            ident = id_fn(it)
            if ident and ident in _pending.get(key, set()):
                continue  # уже показали в этом же прогоне — не дублируем
            if ident and ident in set(seen.get(key, [])):
                continue  # видели в прошлых прогонах — это и есть кулдаун
            out.append(it)
            if ident:
                _pending.setdefault(key, set()).add(ident)
        return out
    except Exception:
        return items


def commit() -> None:
    """Зафиксировать watermark: слить `_pending` в файл. Зовётся при save_brief (разведка собрана).

    До commit ничего на диск не попадает — прогон без брифа watermark не двигает (безопасно)."""
    if not _pending:
        return
    try:
        seen = _load()
        for key, idents in _pending.items():
            merged = list(seen.get(key, [])) + [i for i in idents if i]
            # держим последние SEEN_CAP уникальных (порядок вставки = давность)
            uniq: list[str] = []
            for x in merged:
                if x not in uniq:
                    uniq.append(x)
            seen[key] = uniq[-SEEN_CAP:]
        _save(seen)
    finally:
        _pending.clear()
