"""🧵 Threads-пайплайн (мини-флагман) — Фаза 1: дистилляция вышедшего ТГ-флагмана в серию НА РЕВЬЮ.

    python run_threads_pipeline.py     # дистиллировать последний вышедший флагман → серия в терминал/чат

Фаза 1 НЕ публикует в Threads: выдаёт серию постов на проверку (в ТГ-бота командой /run_threads с
пометкой [THREADS]). Отложку в Threads владелец ставит РУКАМИ в приложении (нативная отложка есть).
Публикация через API — веха E, отдельно.

Скаут в этой ветке НЕ участвует: мини-флагман ничего не разведывает — он дистиллирует уже готовый,
уже прошедший 2FA флагман (вход — core.flagship_journal). Второй Threads-формат (аналог scope) —
позже, отдельной веткой. Изоляция от ТГ-мира: общий только нейтральный слой (config/llm/cost).
"""
import logging

from core import cost, flagship_journal, logging_setup, runmode, threads_creator

logging_setup.setup()


def run_threads_cycle(hint: str = "", emit=print) -> str:
    """Полный прогон мини-флагмана: журнал → дистилляция → серия на ревью. ВОЗВРАЩАЕТ отчёт.

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

    out(f"📝 --- МИНИ-ФЛАГМАН · {len(posts)} пост(а) на ревью [THREADS] ---\n")
    for i, p in enumerate(posts, 1):
        over = "  ⚠️ >500" if len(p) > 500 else ""
        out(f"🧵 [THREADS {i}/{len(posts)}]  ({len(p)} симв.{over})")
        out(p)
        out("")
    out("=== Готово. Проверь серию; понравилось — поставь в отложку Threads руками (приложение). ===")
    out("\n" + cost.summary())
    return "\n".join(report)


def main() -> None:
    logging_setup.set_agent("threads-pipeline")
    logging_setup.new_request()
    run_threads_cycle()


if __name__ == "__main__":
    main()
