"""Данные канала и банк тем флагмана — АКТУАЛЬНОСТЬ, на которой стоят все остальные проверки.

═══ ЧТО БЫЛО ═══
Модуль делал ДВА дела: держал выгрузку канала свежей И сам судил повтор темы (`check` → 🆕/🔁 +
строка «РЕКОМЕНДУЮ»). Вторая половина 31.07 УДАЛЕНА: она была одним из четырёх органов, решавших
тему, и её «РЕКОМЕНДУЮ» якорила гейт на готовый ответ — гейт повторял чужой выбор вместо
независимого суда. Логика анти-повтора (🆕/🔁, угол vs событие, новая рамка ≠ новая тема,
домен-усталость) ЦЕЛИКОМ переехала в topic_gate — туда, где тема и решается, одним судом вместе со
свежестью, пользой и брендом. Сверка не потеряна, она просто больше не живёт отдельным мнением.

═══ ЧТО ОСТАЛОСЬ ═══
  1) АКТУАЛЬНОСТЬ (`refresh_if_stale`): выгрузка канала старше CHANNEL_FRESH_HOURS → тянем свежие
     посты (collect + enrich_topics) ДО любых проверок. Без этого анти-повтор врёт: вчерашнего поста
     в выгрузке нет → «не найдено» → дубль в канал (реальный кейс x402).
  2) БАНК ТЕМ ФЛАГМАНА: пул вечных тем, ротация, пометка [вышло ДАТА]. К scope отношения не имеет.
"""
from __future__ import annotations

import datetime
import random
import re
import time

from core import analytics, config

BANK_FILE = config.ROOT / "memory" / "flagship_topics.md"  # пул вечных тем флагмана (список '- тема — угол')
BANK_REUSE_DAYS = 180  # тема, вышедшая меньше полугода назад, в ротацию НЕ идёт; позже сама возвращается
# Помеченная строка: «- [вышло ГГГГ-ММ-ДД] тема — угол». Дата = когда тему опубликовали (рециклинг).
_USED_RE = re.compile(r"^\[вышло\s+(\d{4}-\d{2}-\d{2})\]\s*(.+)$")


def bank_topics() -> list[str]:
    """Все АКТИВНЫЕ темы банка (строки '- …' без метки [вышло]). Совместимость/обзор."""
    return [t for (_, t, d) in _bank_lines() if d is None]


def _bank_lines() -> list:
    """Разбор банка: список (сырая_строка, текст_темы, дата_вышло|None). Только строки '- '."""
    try:
        text = BANK_FILE.read_text(encoding="utf-8")
    except Exception:
        return []
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s.startswith("- "):
            continue
        body = s[2:].strip()
        m = _USED_RE.match(body)
        if m:
            try:
                d = datetime.date.fromisoformat(m.group(1))
            except Exception:  # noqa: BLE001 — кривая дата: из ротации вон
                continue
            out.append((ln, m.group(2).strip(), d))
        elif body.lower().startswith("[вышло"):
            continue  # помечена [вышло] БЕЗ ISO-даты — из ротации исключена (пометь датой для авто-возврата)
        else:
            out.append((ln, body, None))
    return out


def _today():
    try:
        return datetime.date.today()
    except Exception:  # noqa: BLE001
        return None


def available_bank_themes() -> list[str]:
    """Темы, ДОСТУПНЫЕ для ротации: ещё не выходившие (приоритет) / вышедшие >BANK_REUSE_DAYS назад.
    Из них пайплайн выбирает по актуальности; пусто — банк пуст / всё в окне BANK_REUSE_DAYS."""
    lines = _bank_lines()
    if not lines:
        return []
    never = [t for (_, t, d) in lines if d is None]
    if never:
        pool = never
    else:
        today = _today()
        aged = [t for (_, t, d) in lines if d and today and (today - d).days >= BANK_REUSE_DAYS]
        if aged:
            pool = aged
        else:
            used = sorted(((t, d) for (_, t, d) in lines if d), key=lambda x: x[1])  # самая старая первой
            pool = [t for t, _ in used] or [lines[0][1]]
    return pool


def pick_bank_theme() -> str:
    """ОДНА тема по ротации — СЛУЧАЙНАЯ из доступных. Детерминированный фолбэк, если актуальный
    выбор (сентимент+бриф) в пайплайне недоступен/упал."""
    pool = available_bank_themes()
    return random.choice(pool) if pool else ""


def mark_theme_used(theme: str, date_iso: str = "") -> bool:
    """Пометить тему как [вышло ДАТА] в банке (рециклинг: скрыть из ротации на BANK_REUSE_DAYS).
    Зовётся ТОЛЬКО при реальной публикации (не в draft/test). True — записано."""
    theme = (theme or "").strip()
    if not theme:
        return False
    if not date_iso:
        t = _today()
        date_iso = t.isoformat() if t else ""
    if not date_iso:
        return False
    try:
        lines = BANK_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return False
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("- ") and s[2:].strip() == theme:  # активная строка ровно этой темы
            indent = ln[:len(ln) - len(ln.lstrip())]
            lines[i] = f"{indent}- [вышло {date_iso}] {theme}"
            try:
                BANK_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
                return True
            except Exception:
                return False
    return False

CHANNEL_FRESH_HOURS = 12  # выгрузка свежее этого — повторную тягу не запускаем (бережём время/токены)

# Окно свежести анти-повтора живёт в topic_gate.WINDOW_WEEKS — там, где повтор и судят. Здесь его больше
# нет намеренно: одно число в одном месте, иначе при правке забудешь вторую копию (урок длины 29.07).


def data_age_hours() -> float | None:
    """Возраст выгрузки канала (channel_posts.json) в часах. None — выгрузки ещё нет."""
    p = analytics.POSTS_JSON
    if not p.exists():
        return None
    return (time.time() - p.stat().st_mtime) / 3600.0


def refresh_if_stale(max_hours: float = CHANNEL_FRESH_HOURS) -> str:
    """Гейт актуальности: если выгрузка канала устарела — подтянуть свежие посты ДО сверки.

    Возвращает строку-статус для лога. Свежо → ничего не тянем. Тяга идёт через
    analytics.refresh_metrics (collect → enrich_topics и пр.); ошибки сборщика она глотает сама —
    конвейер не роняем, в худшем случае сверяемся по тому, что уже есть.
    """
    age = data_age_hours()
    if age is not None and age < max_hours:
        return f"✅ Выгрузка канала свежая ({age:.1f}ч < {max_hours:.0f}ч) — анти-повтор по актуальным данным."
    why = "выгрузки канала нет" if age is None else f"выгрузка устарела ({age:.1f}ч ≥ {max_hours:.0f}ч)"
    print(f"🔄 Актуализация данных канала: {why} — тяну свежие посты (collect + enrich_topics)...")
    res = analytics.refresh_metrics(full=False)
    fresh = data_age_hours()
    dedup_ready = fresh is not None and fresh < max_hours  # анти-повтору нужны только посты+темы
    had_errors = "ошибк" in res.lower()
    if dedup_ready and had_errors:
        # collect+enrich прошли (выгрузка свежая), но какой-то шаг упал (напр. build_table = Excel).
        # На сверку это НЕ влияет — но честно сигналим, а не маскируем зелёной галкой.
        head = ("✅ Свежие посты подтянуты — анти-повтор готов; ⚠️ один из шагов обновления упал "
                "(см. ниже, на сверку не влияет)")
    elif dedup_ready:
        head = "✅ Данные канала обновлены"
    else:
        head = "⚠️ Обновить не удалось — сверяюсь по тому, что есть"
    return f"{head}.\n{res}"


