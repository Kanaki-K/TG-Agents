"""Защита аккаунта Threads: стоп-кран, темп, бюджет, предохранитель, журнал.

ЗАЧЕМ ЭТОТ ФАЙЛ СУЩЕСТВУЕТ (14-15.07.2026).
14.07 владелец выгрузил 5000 своих ответов, и в тот же вечер аккаунт получил проверку. Первая
версия этой шапки называла выгрузку причиной проверки. ЭТО ОПРОВЕРГНУТО — см. разбор в
notes/THREADS_API_REPORT_2026-07-14.md и память threads-api-quota-real. Факты (реконструкция
15.07 по логам сессий):
  - за день ушло ~254 запроса, все GET, все по своему аккаунту, все по официальному API;
  - это ≤0.53% от МИНИМАЛЬНО возможной квоты Meta (пол — 48 000/сутки);
  - ни одного 429, ни одного кода лимита (4/17/32/613/80001) — API ни разу не сказал «часто»;
  - сам дамп шёл 200 страниц по 25 с паузой 2.5с и прошёл БЕЗ единой ошибки.
Совпадение по времени ≠ причина.

Что мы действительно сделали плохо — прогон A (19:22-19:33): ~51 запрос к /{uid}/threads,
который ретраился по кругу в повторяющуюся ошибку и не принёс НИ ОДНОЙ записи. Не смертельно
(51 запрос — ничто), но это наш баг, и лечится он именно здесь:
  1) ретрай в ошибку — теперь первый признак лимита = стоп прогона (trip/COOLDOWN), без повторов;
  2) счёта нет      — никто не видел, сколько ушло; теперь журнал + бюджеты + чтение x-app-usage;
  3) watermark нет  — повтор тянул ленту с нуля, хотя данные лежали на диске (лечится в collect).

ЧЕГО ЗДЕСЬ НЕТ И НЕ БУДЕТ: маскировки под человека. Подставной браузерный UA и «ночной режим»
были здесь до 15.07 и сняты — они не защищали аккаунт, а превращали законное чтение своих
данных в то, что Платформенные условия Meta запрещают дословно («circumvent, bypass, or override
any technological measures»). Темп и бюджеты ниже — вежливость к чужому API, и обоснованы именно
так. Мы готовы показать Meta этот файл целиком; всё, что нельзя показать, здесь не место.

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
# ВТОРОЙ стоп-кран — только для ЗАПИСИ (пост/ответ/удаление). Чтение и запись развязаны
# намеренно: аналитика своего аккаунта — рутина, а каждая запись — публичное действие с
# последствиями. Ключи поворачиваются отдельно и каждый со своей причиной: открыл чтение —
# запись НЕ открылась «заодно». Для записи нужны ОБА ключа.
WRITE_UNLOCK_FILE = _DATA / "threads_write_unlocked"
# Предохранитель: ставится автоматом при троттлинге, внутри — до какого времени молчим.
COOLDOWN_FILE = _DATA / "threads_cooldown"
# Журнал: строка на каждый запрос. Он же источник дневного счётчика.
LOG_FILE = _DATA / "threads_api_log.jsonl"

# --- Темп: не грузить чужой сервер. Это вежливость к API, а НЕ маскировка под человека. ---
# Разброс вместо константы — стандартный джиттер: он разводит запросы во времени и не даёт
# ретраям выстроиться в залп. (Прежнее обоснование здесь было «ровные паузы — машинная подпись»,
# т.е. попытка не выглядеть машиной. Снято 15.07.2026: мы машина и не скрываем этого.)
GAP_MIN = float(os.getenv("THREADS_GAP_MIN", "4.0"))
GAP_MAX = float(os.getenv("THREADS_GAP_MAX", "11.0"))
# Раз в N запросов — пауза подлиннее: длинная пагинация не должна идти сплошной очередью.
BREATHER_EVERY = (8, 18)
BREATHER_SECONDS = (30.0, 120.0)

# --- Бюджеты. Потолок против РУНАВЕЯ (цикл в пустую), а не главная защита. ---
# Главный предохранитель против вреда аккаунту — стоп по КВОТЕ META (x-app-usage 80%, ниже):
# он смотрит реальный расход глазами Meta, а не наш счётчик. Поэтому счётные бюджеты держим
# АДЕКВАТНЫМИ работе, а не душащими: инкрементальный сбор стоит ~50-120 запросов (метрики+комменты
# по окну 30 дней), и прежние 60/сутки 150 не давали ему даже ДОБЕЖАТЬ — фейл-закрыто выбрасывало
# всё собранное (гоняли вхолостую). Всё ещё намного ниже пола Meta 48 000/сутки (~1%).
# Урок 14.07 (51 запрос в пустоту) закрыт не крошечным лимитом, а СЧЁТОМ+СВОДКОЙ (run_summary).
RUN_BUDGET = int(os.getenv("THREADS_RUN_BUDGET", "200"))   # запросов за прогон (хватает на полный сбор ×~2)
DAY_BUDGET = int(os.getenv("THREADS_DAY_BUDGET", "500"))   # за скользящие 24ч (сбор ~ежедневно + отчёты)

# --- Полоса ЗАПИСИ: строже чтения на порядок. ---
# Лимиты Meta на запись: 250 постов + 1000 ответов / 24ч (threads_publishing_limit). Наши
# потолки — ~1-2% от них: стратегия «меньше, но качественнее» зашита ЧИСЛОМ, а не пожеланием.
# Один пост = 2 write-запроса (контейнер + publish), т.е. 24/сутки ≈ 12 публикаций максимум.
WRITE_RUN_BUDGET = int(os.getenv("THREADS_WRITE_RUN_BUDGET", "10"))   # за прогон (≈5 публикаций)
WRITE_DAY_BUDGET = int(os.getenv("THREADS_WRITE_DAY_BUDGET", "24"))   # за скользящие 24ч
# Темп записи заметно медленнее чтения: публикации не должны идти очередью. Меряем от
# ПРОШЛОЙ ЗАПИСИ (чтение между записями паузу записи не сбрасывает).
WRITE_GAP_MIN = float(os.getenv("THREADS_WRITE_GAP_MIN", "30.0"))
WRITE_GAP_MAX = float(os.getenv("THREADS_WRITE_GAP_MAX", "75.0"))

# --- Квота глазами Meta (заголовок x-app-usage, проценты 0-100). ---
# Тормозим САМИ на 80%, не дожидаясь лимита: 100% — это уже отказ и отметка в их системе.
USAGE_WARN_PERCENT = float(os.getenv("THREADS_USAGE_WARN", "50"))
USAGE_STOP_PERCENT = float(os.getenv("THREADS_USAGE_STOP", "80"))

# --- Предохранитель. Коды Meta, означающие «ты слишком частый». ---
# 4/17/32 — application/user/page request limit; 613 — calls per second; 80001 — Threads-specific.
THROTTLE_CODES = {4, 17, 32, 613, 80001}
COOLDOWN_HOURS = float(os.getenv("THREADS_COOLDOWN_HOURS", "6"))

_run_count = 0          # запросов в этом процессе
_write_run_count = 0    # из них — записей (пост/ответ/удаление)
_run_by_kind: dict[str, int] = {}   # endpoint-класс → счётчик за процесс (для сводки «куда ушло»)
_peak_usage_pct = 0.0   # макс. x-app-usage % за процесс — расход ГЛАЗАМИ Meta
_next_breather = random.randint(*BREATHER_EVERY)
_last_call_at = 0.0
_last_write_at = 0.0


class ThreadsBlocked(RuntimeError):
    """Запрос НЕ отправлен — сработала защита (стоп-кран, остывание или бюджет).

    Отдельный тип, а не ThreadsError: вызывающий код обязан отличать «мы сами не пошли»
    от «сходили и получили ошибку». Первое НЕ должно попадать в данные как ошибка поста.
    """


def _now() -> float:
    return time.time()


# Ночного режима здесь больше нет (снят 15.07.2026). Он запрещал ходить в API по ночам на том
# основании, что «приложение, которое ходит в API в 4 утра, — не человек». Это была подгонка
# поведения под детекцию, а не забота о лимитах: квоте время суток безразлично. Мы автоматика,
# работаем по расписанию владельца и не притворяемся кем-то ещё. Темп и бюджеты ниже делают всю
# полезную работу, которую якобы делал ночной режим.


def frozen_reason(write: bool = False) -> str:
    """Почему сейчас нельзя в сеть. Пустая строка = можно. write=True — проверка ОБОИХ ключей."""
    if not UNLOCK_FILE.exists():
        return (
            f"сеть Threads закрыта (нет файла {UNLOCK_FILE.name}). Это состояние ПО УМОЛЧАНИЮ "
            f"после проверки аккаунта 14.07.2026. Открыть осознанно: threads_unlock('причина')"
        )
    if write and not WRITE_UNLOCK_FILE.exists():
        return (
            f"ЗАПИСЬ в Threads закрыта (нет файла {WRITE_UNLOCK_FILE.name}). Чтение открыто, но "
            f"запись — отдельный ключ: каждый пост/ответ — публичное действие. "
            f"Открыть осознанно: _guard.unlock_write('причина')"
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
    """Закрыть сеть Threads обратно (запись закрывается автоматически — ей нужны оба ключа)."""
    UNLOCK_FILE.unlink(missing_ok=True)
    log.warning("Сеть Threads закрыта.")


def unlock_write(reason: str) -> None:
    """Открыть ЗАПИСЬ в Threads (второй ключ; без открытого чтения записи всё равно не будет).

    Тот же принцип, что unlock(): причина обязательна и остаётся в файле — «кто и зачем открыл»
    видно глазами без раскопок. Закрыл чтение — запись фактически тоже встала.
    """
    if not (reason or "").strip():
        raise ValueError("Открывать запись в Threads без указанной причины нельзя.")
    WRITE_UNLOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    WRITE_UNLOCK_FILE.write_text(f"{stamp}\n{reason.strip()}\n", encoding="utf-8")
    log.warning("ЗАПИСЬ в Threads ОТКРЫТА: %s", reason.strip())


def lock_write() -> None:
    """Закрыть запись в Threads (чтение не трогает)."""
    WRITE_UNLOCK_FILE.unlink(missing_ok=True)
    log.warning("Запись в Threads закрыта.")


def _calls_last_24h(kind: str | None = None) -> int:
    """Сколько запросов ушло за скользящие сутки — считаем по журналу.

    kind='write' — только записи (пост/ответ/удаление); None — все подряд.
    """
    if not LOG_FILE.exists():
        return 0
    cutoff = _now() - 86400
    n = 0
    try:
        with LOG_FILE.open(encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    if row.get("at", 0) >= cutoff and (kind is None or row.get("kind") == kind):
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


def before(endpoint: str, *, write: bool = False) -> float:
    """Вызывается ПЕРЕД каждым запросом. Либо выдерживает паузу, либо бьёт по рукам.

    write=True — запись (пост/ответ/удаление): свой стоп-кран, свои бюджеты, свой темп.
    Возвращает t0 для замера длительности. Кидает ThreadsBlocked — тогда запроса НЕ будет.
    """
    global _run_count, _write_run_count, _next_breather, _last_call_at

    reason = frozen_reason(write)
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
    if write:
        if _write_run_count >= WRITE_RUN_BUDGET:
            raise ThreadsBlocked(
                f"Бюджет ЗАПИСИ за прогон исчерпан ({WRITE_RUN_BUDGET}). «Меньше, но качественнее» "
                f"— остальное завтра или следующим осознанным прогоном."
            )
        wday = _calls_last_24h("write")
        if wday >= WRITE_DAY_BUDGET:
            raise ThreadsBlocked(
                f"Дневной бюджет ЗАПИСИ исчерпан ({wday}/{WRITE_DAY_BUDGET} за сутки). Ждём."
            )

    # Пауза отсчитывается от КОНЦА прошлого запроса: сеть уже съела часть времени.
    gap = random.uniform(GAP_MIN, GAP_MAX)
    if _run_count and _run_count >= _next_breather:
        gap = random.uniform(*BREATHER_SECONDS)
        _next_breather = _run_count + random.randint(*BREATHER_EVERY)
        log.info("Threads: пауза %.0fс после %d запросов (не долбим лентой)", gap, _run_count)
    wait_until = _last_call_at + gap
    if write and _last_write_at:
        # Темп записи меряем от прошлой ЗАПИСИ: чтение между записями паузу не сбрасывает.
        wait_until = max(wait_until, _last_write_at + random.uniform(WRITE_GAP_MIN, WRITE_GAP_MAX))
    waited = wait_until - _now()
    if waited > 0:
        time.sleep(waited)

    _run_count += 1
    if write:
        _write_run_count += 1
    return _now()


def _classify(endpoint: str) -> str:
    """Класс запроса для сводки «куда ушло»: лента/метрики/комменты/прочее."""
    e = (endpoint or "").lower()
    if "insights" in e:
        return "метрики"
    if "replies" in e or "conversation" in e:
        return "комменты"
    if "threads" in e:
        return "лента/посты"
    return "прочее"


def after(endpoint: str, t0: float, *, status: int | None, error: str = "",
          usage: dict | None = None, write: bool = False) -> None:
    """Вызывается ПОСЛЕ запроса (успех или ошибка) — пишет журнал + учёт для сводки."""
    global _last_call_at, _last_write_at, _peak_usage_pct
    _last_call_at = _now()
    if write:
        _last_write_at = _last_call_at
    kind = _classify(endpoint)
    _run_by_kind[kind] = _run_by_kind.get(kind, 0) + 1
    if usage:
        pct = _peak_percent(usage)
        if pct > _peak_usage_pct:
            _peak_usage_pct = pct
    _journal(
        at=round(_last_call_at, 3),
        iso=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        endpoint=endpoint,
        kind="write" if write else None,   # запись/чтение: по этому полю считается write-бюджет
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
        "записей за прогон": _write_run_count,
        "записей за сутки": _calls_last_24h("write"),
        "бюджет записи (прогон/сутки)": f"{WRITE_RUN_BUDGET}/{WRITE_DAY_BUDGET}",
        "блокировка чтения": frozen_reason() or "нет",
        "блокировка записи": frozen_reason(write=True) or "нет",
    }


def run_summary() -> str:
    """Человеческая сводка расхода за прогон: сколько, КУДА ушло, дневной остаток, квота Meta.
    Печатается в конце сбора — чтобы «сколько куда потратили» было видно без раскопок журнала."""
    day = _calls_last_24h()
    lines = ["📊 Threads API — расход этого прогона:",
             f"   всего: {_run_count} запрос(ов)  (бюджет прогона {RUN_BUDGET})"]
    for kind, n in sorted(_run_by_kind.items(), key=lambda x: -x[1]):
        lines.append(f"      ├ {kind}: {n}")
    left = max(0, DAY_BUDGET - day)
    lines.append(f"   за сутки: {day}/{DAY_BUDGET} (осталось ~{left})")
    lines.append(f"   квота Meta (x-app-usage, наш стоп {USAGE_STOP_PERCENT:.0f}%): пик {_peak_usage_pct:.1f}%")
    return "\n".join(lines)
