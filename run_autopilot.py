"""Автопилот завода: сам запускает флагман-прогон в свой день и час.

    python run_autopilot.py            # ОДНА проверка и выход — для Планировщика задач Windows
    python run_autopilot.py --daemon   # живой процесс: проверяет раз в 10 минут
    python run_autopilot.py --status   # показать вердикт и настройки, НИЧЕГО не запускать

Что делает, когда «пора» (вердикт даёт core/schedule): ставит метку «сегодня гоняли» → гонит
`run_pipeline.run_cycle` (тема из банка → Криейтор → 2FA → обложка → нативная отложка канала) →
пишет владельцу в Telegram, что вышло. Упал — тоже пишет: молча мёртвым завод быть не должен.

ПРЕДОХРАНИТЕЛИ (все — в коде, не в промпте):
  1. нет файла `data/autopilot_on` → не делает НИЧЕГО (главный выключатель);
  2. режим `/test` → не публикует (иначе Haiku-пост уйдёт в канал по расписанию);
  3. не задан PUBLISH_CHANNEL → отказ с объяснением (публиковать некуда);
  4. вне окна старта / не тот день / сегодня уже гоняли / слот занят → пропуск (см. core/schedule.due);
  5. метка ставится ДО прогона → падение не превращается в цикл перезапусков и трату денег.

Владельцу: настройка, чек-лист и «как выключить» — docs/AUTOPILOT.md.
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import datetime

from connectors.telegram_publish import publish
from core import bot_alert, config, content_plan, logging_setup, runmode, schedule

logging_setup.setup()
log = logging.getLogger(__name__)

TG_ALERT_LIMIT = 3500   # запас под лимит Telegram (4096) — алерт не должен упасть на длинном отчёте


def _busy_dates(channel: str):
    """Даты, на которые в канале уже стоят отложенные посты. None — проверить не удалось."""
    try:
        return {dt.astimezone(content_plan.tz()).date() for dt in publish.scheduled_times(channel)}
    except Exception:  # noqa: BLE001 — нет сессии/сети: не повод отменять выход, см. schedule.due
        log.exception("[автопилот] не смог прочитать «Отложенные» канала — иду по плану")
        return None


def _digest(report: str) -> str:
    """Компактная выжимка прогона для Telegram: заголовок поста + слот + итог-панель.

    Полный отчёт остаётся в логах/консоли; владельцу в чат нужен ответ на «что вышло и куда встало».
    """
    lines = report.splitlines()
    parts: list[str] = []
    for i, ln in enumerate(lines):
        if "ГОТОВЫЙ ПОСТ" in ln:
            title = next((x.strip().replace("**", "") for x in lines[i + 1:i + 6] if x.strip()), "")
            if title:
                parts.append(f"📝 {title[:200]}")
            break
    for ln in lines:
        if any(m in ln for m in ("Поставил в отложенные", "⛔ Свежего поста", "❌ Не поставил")):
            parts.append(ln.strip())
    panel = report.find("━━━━━━ ИТОГ")
    if panel >= 0:
        parts.append(report[panel:].strip())
    out = "\n\n".join(parts) if parts else report[-TG_ALERT_LIMIT:]
    return out[:TG_ALERT_LIMIT]


def _run(kind: str, slot) -> None:
    """Реальный прогон: метка → пайплайн → отчёт владельцу. Исключения не пробрасываем наружу."""
    import run_pipeline  # ленивый импорт: --status не должен тянуть весь пайплайн

    logging_setup.set_agent("autopilot")
    logging_setup.new_request()
    schedule.mark_run(kind)   # ЗАЯВКА до прогона: падение не даст перезапускать и жечь деньги
    when = content_plan.human(slot)
    log.info("[автопилот] старт прогона '%s', слот %s", kind, when)
    bot_alert.notify_owner(f"🚀 Автопилот: запускаю {content_plan.kind_label(kind)} — "
                           f"выход в канал на {when}. Отчёт пришлю, как закончу (~10-20 мин).")
    try:
        report = run_pipeline.run_cycle(scope=False, evergreen=True, emit=print)
    except Exception as e:  # noqa: BLE001 — падение прогона обязано ДОЙТИ до владельца, а не в лог
        log.exception("[автопилот] прогон упал")
        bot_alert.notify_owner(f"❌ Автопилот: прогон упал — {type(e).__name__}: {e}\n\n"
                               f"В канал ничего не ушло. Подробности в логах; повторить руками: "
                               f"python run_pipeline.py")
        return
    bot_alert.notify_owner(f"✅ Автопилот: прогон закончен ({when}).\n\n{_digest(report)}")


def check_once() -> str:
    """Одна проверка. Возвращает короткий код исхода (для логов и --daemon): off/test/no-channel/skip/run."""
    if not schedule.enabled():
        print(f"⏸ Автопилот ВЫКЛЮЧЕН (нет файла {schedule.ON_FILE.name}) — ничего не делаю.")
        return "off"
    channel = config.get_optional("PUBLISH_CHANNEL")
    if not channel:
        print("❌ PUBLISH_CHANNEL не задан в .env — публиковать некуда, прогон не начинаю.")
        bot_alert.notify_owner("❌ Автопилот: PUBLISH_CHANNEL не задан в .env — выход пропущен.")
        return "no-channel"
    verdict = schedule.due("flagship", busy_dates=_busy_dates(channel))
    print(f"{'✅' if verdict['go'] else '⏭'} {verdict['why']}")
    if not verdict["go"]:
        return "skip"
    mode = runmode.get()
    if mode["mode"] == "test":
        # /test = дешёвая модель для проверки механики. Такой пост в канал ставить нельзя.
        # Метку НЕ ставим: вернёшь /main внутри окна — прогон состоится в эту же проверку.
        print("🧪 Режим /test — публикацию НЕ делаю (в канал ушёл бы Haiku-пост). Верни /main.")
        bot_alert.notify_owner("🧪 Автопилот: пора гнать флагман, но завод в режиме /test — "
                               "публикацию не делаю. Верни /main, если выход нужен сегодня.")
        return "test"
    _run("flagship", verdict["slot"])
    return "run"


def status() -> None:
    """Что автопилот думает прямо сейчас — без побочных действий (для чек-листа перед включением)."""
    now = datetime.now(content_plan.tz())
    win = schedule.window("flagship", now.date())
    print("=== Автопилот: состояние ===")
    print(f"  выключатель   : {'✅ ВКЛЮЧЁН' if schedule.enabled() else '⏸ выключен'} "
          f"({schedule.ON_FILE})")
    print(f"  сейчас        : {content_plan.human(now)} · пояс {content_plan.tz_label()}")
    mode = runmode.get()
    label = f"🧪 test ({mode['model'] or ''})" if mode["mode"] == "test" else "боевой /main"
    print(f"  режим завода  : {label}")
    print(f"  канал         : {config.get_optional('PUBLISH_CHANNEL') or '❌ не задан (PUBLISH_CHANNEL)'}")
    days = "/".join(content_plan.RU_DOW[i] for i in content_plan.days_for("flagship"))
    print(f"  флагман выходит: {days} в {content_plan._slot_time('flagship'):%H:%M}")
    print(f"  окно старта    : {f'{win[0]:%H:%M}–{win[1]:%H:%M}' if win else '— сегодня не день флагмана'} "
          f"(лид {schedule.lead_hours():g}ч, запас {schedule.margin_minutes():g} мин)")
    print(f"  последний авто : {schedule.last_run('flagship') or '— ни разу'}")
    v = schedule.due("flagship", busy_dates=None)
    print(f"  вердикт сейчас : {'✅ пора' if v['go'] else '⏭ пропуск'} — {v['why']}")


def main() -> None:
    if "--status" in sys.argv:
        status()
        return
    if "--daemon" in sys.argv:
        pause = schedule.check_every()
        print(f"🤖 Автопилот в режиме демона: проверка раз в {pause / 60:.0f} мин. Ctrl+C — выход.")
        while True:
            try:
                check_once()
            except Exception:  # noqa: BLE001 — демон не имеет права умереть от одной проверки
                log.exception("[автопилот] проверка упала — продолжаю цикл")
            time.sleep(pause)
    check_once()


if __name__ == "__main__":
    main()
