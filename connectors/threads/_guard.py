"""Защита аккаунта Threads: стоп-кран, темп, бюджет, предохранитель, журнал.

ЗАЧЕМ ЭТОТ ФАЙЛ СУЩЕСТВУЕТ (14-15.07.2026).
14.07 через этот коннектор прошла массовая выгрузка (5000 ответов) — несколько полных проходов
подряд за 40 минут, дефолтным User-Agent, без единой паузы. Аккаунт получил проверку. Разбор
показал три дыры, которые сложились в один машинный профиль:
  1) темпа нет     — запросы летели вплотную, до ~1000 залпом (голый `for` в insights.metrics_for);
  2) watermark нет — каждый повтор тянул ленту с нуля, хотя данные уже лежали на диске;
  3) журнала нет   — никто не видел, сколько запросов ушло; восстанавливали потом по mtime файлов.
Ни одна дыра по отдельности не убила бы. Вместе — дали ровно тот след, на который ловят.

Модуль закрывает 1 и 3 и служит опорой для 2. Он ЕДИНСТВЕННЫЙ вход перед сетью: `_api._open()`
зовёт before()/after() вокруг каждого запроса, обойти нельзя — других дверей наружу нет.

ПРИНЦИП: при сомнении — НЕ ходить. Лучше недособрать данные, чем потерять аккаунт. Поэтому здесь
нет retry в цикле на троттлинг: первый признак лимита = стоп всего прогона и остывание.
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_DATA = Path(__file__).resolve().parents[2] / "data"

# Стоп-кран НАОБОРОТ: сеть закрыта, пока файла НЕТ. Это принципиально.
# Наивный вариант («файл есть → блокируем») бесполезен: data/ в .gitignore, значит флаг не уезжает
# с кодом. Свежий клон/чужая машина получили бы код БЕЗ блокировки — то есть защита была бы там,
# где она уже не нужна, и отсутствовала бы там, где нужна. Инверсия делает состояние по умолчанию
# безопасным: не подумал — никуда не пошёл.
UNLOCK_FILE = _DATA / "threads_unlocked"
# Предохранитель: ставится автоматом при троттлинге, внутри — до какого времени молчим.
COOLDOWN_FILE = _DATA / "threads_cooldown"
# Журнал: строка на каждый запрос. Он же источник дневного счётчика.
LOG_FILE = _DATA / "threads_api_log.jsonl"

# --- Темп. Ровные паузы — сами по себе машинная подпись, поэтому разброс, а не константа. ---
GAP_MIN = 2.0
GAP_MAX = 6.0
# Раз в N запросов — «пауза на подумать»: человек не листает ленту 200 раз без перерыва.
BREATHER_EVERY = (12, 25)
BREATHER_SECONDS = (20.0, 75.0)

# --- Бюджеты. Потолок, а не пожелание: упёрлись — прогон встаёт сам. ---
RUN_BUDGET = int(os.getenv("THREADS_RUN_BUDGET", "120"))   # запросов за один прогон
DAY_BUDGET = int(os.getenv("THREADS_DAY_BUDGET", "300"))   # запросов за скользящие 24ч

# --- Квота глазами Meta (заголовок x-app-usage, проценты 0-100). ---
# Тормозим САМИ на 80%, не дожидаясь лимита: 100% — это уже отказ и отметка в их системе.
USAGE_WARN_PERCENT = float(os.getenv("THREADS_USAGE_WARN", "50"))
USAGE_STOP_PERCENT = float(os.getenv("THREADS_USAGE_STOP", "80"))

# --- Предохранитель. Коды Meta, означающие «ты слишком частый». ---
# 4/17/32 — application/user/page request limit; 613 — calls per second; 80001 — Threads-specific.
THROTTLE_CODES = {4, 17, 32, 613, 80001}
COOLDOWN_HOURS = float(os.getenv("THREADS_COOLDOWN_HOURS", "6"))

_run_count = 0          # запросов в этом процессе
_next_breather = random.randint(*BREATHER_EVERY)
_last_call_at = 0.0


class ThreadsBlocked(RuntimeError):
    """Запрос НЕ отправлен — сработала защита (стоп-кран, остывание или бюджет).

    Отдельный тип, а не ThreadsError: вызывающий код обязан отличать «мы сами не пошли»
    от «сходили и получили ошибку». Первое НЕ должно попадать в данные как ошибка поста.
    """


def _now() -> float:
    return time.time()


def frozen_reason() -> str:
    """Почему сейчас нельзя в сеть. Пустая строка = можно."""
    if not UNLOCK_FILE.exists():
        return (
            f"сеть Threads закрыта (нет файла {UNLOCK_FILE.name}). Это состояние ПО УМОЛЧАНИЮ "
            f"после проверки аккаунта 14.07.2026. Открыть осознанно: threads_unlock('причина')"
        )
    if COOLDOWN_FILE.exists():
        try:
            until = float(COOLDOWN_FILE.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return ""  # битый файл не должен намертво блокировать
        if _now() < until:
            left = int((until - _now()) / 60)
            when = datetime.fromtimestamp(until, timezone.utc).strftime("%d.%m %H:%M UTC")
            return f"предохранитель после троттлинга: молчим ещё {left} мин (до {when})"
        COOLDOWN_FILE.unlink(missing_ok=True)  # срок вышел — снимаем сами
    return ""


def unlock(reason: str) -> None:
    """Открыть сеть Threads. Делается ОСОЗНАННО и только когда аккаунт точно в порядке.

    reason обязателен — не формальность: файл потом читается глазами, и «кто и зачем открыл»
    должно быть видно без раскопок. Открытие НЕ снимает остывание после троттлинга.
    """
    if not (reason or "").strip():
        raise ValueError("Открывать сеть Threads без указанной причины нельзя.")
    UNLOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    UNLOCK_FILE.write_text(f"{stamp}\n{reason.strip()}\n", encoding="utf-8")
    log.warning("Сеть Threads ОТКРЫТА: %s", reason.strip())


def lock() -> None:
    """Закрыть сеть Threads обратно."""
    UNLOCK_FILE.unlink(missing_ok=True)
    log.warning("Сеть Threads закрыта.")


def _calls_last_24h() -> int:
    """Сколько запросов ушло за скользящие сутки — считаем по журналу."""
    if not LOG_FILE.exists():
        return 0
    cutoff = _now() - 86400
    n = 0
    try:
        with LOG_FILE.open(encoding="utf-8") as f:
            for line in f:
                try:
                    if json.loads(line).get("at", 0) >= cutoff:
                        n += 1
                except json.JSONDecodeError:
                    continue  # битая строка журнала не повод падать
    except OSError:
        return 0
    return n


def _journal(**row) -> None:
    """Дописать строку в журнал. Журнал — не роскошь: без него сбор снова придётся
    восстанавливать по mtime файлов, как пришлось 15.07."""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as e:  # журнал не должен ронять сбор
        log.warning("Не смог записать журнал Threads API: %s", e)


def before(endpoint: str) -> float:
    """Вызывается ПЕРЕД каждым запросом. Либо выдерживает паузу, либо бьёт по рукам.

    Возвращает t0 для замера длительности. Кидает ThreadsBlocked — тогда запроса НЕ будет.
    """
    global _run_count, _next_breather, _last_call_at

    reason = frozen_reason()
    if reason:
        raise ThreadsBlocked(f"Запрос к Threads не отправлен: {reason}")

    if _run_count >= RUN_BUDGET:
        raise ThreadsBlocked(
            f"Бюджет прогона исчерпан ({RUN_BUDGET} запросов). Прогон остановлен намеренно — "
            f"добери остаток в следующий раз, база на диске не пострадала."
        )
    day = _calls_last_24h()
    if day >= DAY_BUDGET:
        raise ThreadsBlocked(
            f"Дневной бюджет исчерпан ({day}/{DAY_BUDGET} запросов за сутки). Ждём."
        )

    # Пауза отсчитывается от КОНЦА прошлого запроса: сеть уже съела часть времени.
    gap = random.uniform(GAP_MIN, GAP_MAX)
    if _run_count and _run_count >= _next_breather:
        gap = random.uniform(*BREATHER_SECONDS)
        _next_breather = _run_count + random.randint(*BREATHER_EVERY)
        log.info("Threads: пауза %.0fс после %d запросов (не долбим лентой)", gap, _run_count)
    waited = gap - (_now() - _last_call_at)
    if waited > 0:
        time.sleep(waited)

    _run_count += 1
    return _now()


def after(endpoint: str, t0: float, *, status: int | None, error: str = "",
          usage: dict | None = None) -> None:
    """Вызывается ПОСЛЕ запроса (успех или ошибка) — пишет журнал."""
    global _last_call_at
    _last_call_at = _now()
    _journal(
        at=round(_last_call_at, 3),
        iso=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        endpoint=endpoint,
        status=status,
        ms=int((_last_call_at - t0) * 1000),
        error=error or None,
        run_no=_run_count,
        usage=usage or None,          # x-app-usage: сколько квоты сожгли ПО МНЕНИЮ META
    )


def usage_from_headers(headers) -> dict:
    """Разобрать x-app-usage / x-business-use-case-usage — расход квоты ГЛАЗАМИ META.

    Meta сама пишет в заголовке каждого ответа, сколько процентов лимита мы сожгли
    (call_count/total_cputime/total_time, 0-100). Мы эти заголовки просто выбрасывали и гадали
    о квоте по косвенным признакам. Теперь это прямой сигнал — единственный честный.
    """
    out: dict = {}
    if not headers:
        return out
    for name in ("x-app-usage", "x-business-use-case-usage"):
        try:
            raw = headers.get(name)
        except AttributeError:
            return out
        if not raw:
            continue
        try:
            out[name] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            out[name] = raw  # формат мог измениться — сохраняем как есть, лучше сырое, чем ничего
    return out


def _peak_percent(usage: dict) -> float:
    """Худший из процентов расхода. Именно худший: упрёмся в любой из лимитов — тормознут всё."""
    worst = 0.0
    app = usage.get("x-app-usage")
    if isinstance(app, dict):
        for k in ("call_count", "total_cputime", "total_time"):
            try:
                worst = max(worst, float(app.get(k) or 0))
            except (TypeError, ValueError):
                continue
    buc = usage.get("x-business-use-case-usage")
    if isinstance(buc, dict):
        for entries in buc.values():
            for e in entries if isinstance(entries, list) else []:
                for k in ("call_count", "total_cputime", "total_time"):
                    try:
                        worst = max(worst, float((e or {}).get(k) or 0))
                    except (TypeError, ValueError):
                        continue
    return worst


def check_usage(usage: dict) -> None:
    """Упреждающий тормоз по квоте Meta. Дешевле остановиться самим, чем словить лимит."""
    if not usage:
        return
    pct = _peak_percent(usage)
    if pct >= USAGE_STOP_PERCENT:
        until = _now() + COOLDOWN_HOURS * 3600
        try:
            COOLDOWN_FILE.write_text(str(until), encoding="utf-8")
        except OSError:
            pass
        raise ThreadsBlocked(
            f"Квота Meta израсходована на {pct:.0f}% (порог {USAGE_STOP_PERCENT}%). Останавливаемся "
            f"САМИ, не дожидаясь лимита. Данные на диске целы, продолжим позже."
        )
    if pct >= USAGE_WARN_PERCENT:
        log.warning("Threads: квота Meta израсходована на %.0f%% — притормаживаем", pct)


def trip(status: int | None, meta_code: int | None, detail: str) -> None:
    """Предохранитель: заметили троттлинг → гасим ВЕСЬ прогон и уходим остывать.

    Именно стоп, а не retry. Повтор в ответ на «ты слишком частый» — это ровно то поведение,
    из-за которого 14.07 три захода подряд превратились в один сплошной след.
    """
    if status != 429 and meta_code not in THROTTLE_CODES:
        return
    until = _now() + COOLDOWN_HOURS * 3600
    try:
        COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        COOLDOWN_FILE.write_text(str(until), encoding="utf-8")
    except OSError as e:
        log.error("Не смог записать файл остывания: %s", e)
    log.error("Threads ТРОТТЛИНГ (%s / code %s): %s", status, meta_code, detail)
    raise ThreadsBlocked(
        f"Threads ответил троттлингом ({status}/code {meta_code}). Прогон остановлен, "
        f"следующие {COOLDOWN_HOURS:.0f} ч в API не ходим. Это защита аккаунта, а не сбой."
    )


def stats() -> dict:
    """Короткая сводка для человека: сколько ушло и что с защитой."""
    return {
        "за прогон": _run_count,
        "за сутки": _calls_last_24h(),
        "бюджет прогона": RUN_BUDGET,
        "бюджет суток": DAY_BUDGET,
        "блокировка": frozen_reason() or "нет",
    }
