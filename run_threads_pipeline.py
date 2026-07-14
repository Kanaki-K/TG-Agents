"""🧵 Threads-пайплайн (мини-флагман) — Фаза 1: дистилляция вышедшего ТГ-флагмана в серию постов.

    python run_threads_pipeline.py                 # дистилляция → серия в ОТЛОЖКУ тестового ТГ-канала
    python run_threads_pipeline.py --review-only   # только показать серию, в отложку НЕ ставить

ОБКАТКА (Фаза 1): серию кладём в нативную «Отложенную» очередь ТЕСТОВОГО ТГ-канала — ТЕМ ЖЕ механизмом,
что флагман/скоуп (telegram_publish, MTProto, слот content_plan) — чтобы увидеть посты живьём. Это НЕ
живая публикация: очередь на проверку, владелец смотрит/удаляет в «Отложенных». Реальная публикация в
Threads (веха E) — отдельно; пока в само Threads владелец ставит отложку руками в приложении.

Скаут в этой ветке НЕ участвует: мини-флагман ничего не разведывает — он дистиллирует уже готовый,
уже прошедший 2FA флагман (вход — core.flagship_journal). Анти-повтор/домен/ориентир — не нужны (флагман
выверен до создания), это машинерия Формата 2. Изоляция от ТГ-мира: общий только нейтральный слой.
"""
import logging
import sys
from datetime import timedelta

from connectors.telegram_publish import publish as tg_publish
from core import config, content_plan, cost, flagship_journal, logging_setup, runmode, threads_creator

logging_setup.setup()

THREADS_SERIES_GAP_MIN = 10   # разнос постов серии по времени, чтобы легли ОТДЕЛЬНЫМИ отложенными


def run_threads_cycle(hint: str = "", publish: bool = True, emit=print) -> str:
    """Полный прогон мини-флагмана: журнал → дистилляция → серия → ОТЛОЖКА тестового ТГ-канала. Отчёт.

    publish=False (или --review-only / тест-режим) — только показать серию, в отложку не ставить.
    emit — куда слать прогресс (print в терминал; бот передаёт свой коллектор, чтобы вернуть в чат)."""
    report: list[str] = []

    def out(s: str = "") -> None:
        emit(s)
        report.append(s)

    cost.reset()
    out("=== 🧵 Threads · мини-флагман (дистилляция вышедшего флагмана) ===\n")
    _mode = runmode.get()
    if _mode["mode"] == "test":
        out(f"🧪 ТЕСТ-режим: модель → {_mode['model']} (дёшево, НЕ для прода).\n")

    src = flagship_journal.latest()
    if not src or not src.get("text"):
        out("⛔ Журнал вышедших флагманов ПУСТ — дистиллировать нечего. Опубликуй флагман в ТГ "
            "(он запишется в журнал), затем запускай мини-флагман.")
        out("\n" + cost.summary())
        return "\n".join(report)

    out(f"🧵 Источник: флагман от {src.get('date', '?')} — «{src.get('theme') or '(без темы)'}»")
    # Анти-повтор/домен/ориентир на мини-флагмане НЕ нужны: флагман уже прошёл все гейты (Скаут,
    # антиповтор темы, пикер, 2FA) ДО создания — мы его лишь дистиллируем. Эта машинерия — для Формата 2
    # (он originates контент), модули threads_dedup/orientation_digest ждут его, к мини-флагману не привязаны.
    out("✍️ Дистиллирую в мини-серию Threads (Sonnet, свой контекст — без Скаута/2FA/обложки)...\n")
    try:
        series = threads_creator.write(hint)
    except Exception as e:
        out(f"❌ Дистилляция не удалась: {e}")
        out("\n" + cost.summary())
        return "\n".join(report)

    if series.startswith("⚠️"):      # threads_creator вернул отказ (пустой журнал) — показываем как есть
        out(series)
        out("\n" + cost.summary())
        return "\n".join(report)

    posts = [p.strip() for p in series.split(threads_creator.POST_SEP) if p.strip()]
    if not posts:
        out("⚠️ Серия пустая — модель ничего не выдала. Сырой вывод:")
        out(series)
        out("\n" + cost.summary())
        return "\n".join(report)

    out(f"📝 --- МИНИ-ФЛАГМАН · {len(posts)} пост(а) [THREADS] ---\n")
    for i, p in enumerate(posts, 1):
        over = "  ⚠️ >500" if len(p) > 500 else ""
        out(f"🧵 [THREADS {i}/{len(posts)}]  ({len(p)} симв.{over})")
        out(p)
        out("")

    # ОБКАТКА: серию — в ОТЛОЖКУ тестового ТГ-канала (тем же механизмом, что флагман/скоуп). НЕ живая
    # публикация: очередь на проверку. В тест-режиме (дешёвая модель) и при --review-only — не ставим.
    if not publish or _mode["mode"] == "test":
        why = "тест-режим" if _mode["mode"] == "test" else "review-only"
        out(f"🧪 В отложку НЕ ставлю ({why}) — серия выше на проверку.")
        out("\n" + cost.summary())
        return "\n".join(report)
    channel = config.get_optional("PUBLISH_CHANNEL")
    if not channel:
        out("⚠️ PUBLISH_CHANNEL не задан в .env — публиковать некуда, серия осталась на ревью выше.")
        out("\n" + cost.summary())
        return "\n".join(report)
    out(f"\n🗓 Ставлю серию в ОТЛОЖКУ канала «{channel}» (обкатка; это НЕ живая публикация)...")
    base = content_plan.next_slot("short")   # якорь-слот как у короткого; посты серии разнесём по времени
    ok = 0
    for i, p in enumerate(posts):
        when = base + timedelta(minutes=THREADS_SERIES_GAP_MIN * i)
        body = f"🧵 [THREADS · мини-флагман {i + 1}/{len(posts)}]\n\n{p}"
        res = tg_publish.publish(channel, body, None, when)
        if res.get("ok"):
            ok += 1
            out(f"  ✅ пост {i + 1}/{len(posts)} → {content_plan.human(when)} ({res.get('mode', '?')})")
        else:
            out(f"  ❌ пост {i + 1}/{len(posts)}: {res.get('error', '?')}")
    out(f"🗓 В отложке канала: {ok}/{len(posts)} постов. Проверь/удали в нативных «Отложенных» (это тест).")
    out("Для реального Threads — ставь отложку руками в приложении (веха E: авто-публикация — позже).")
    out("\n" + cost.summary())
    return "\n".join(report)


def main() -> None:
    logging_setup.set_agent("threads-pipeline")
    logging_setup.new_request()
    run_threads_cycle(publish="--review-only" not in sys.argv)


if __name__ == "__main__":
    main()
