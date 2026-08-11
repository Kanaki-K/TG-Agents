"""Автопилот завода: сам запускает флагман-прогон в свой день и час.

    python run_autopilot.py            # ОДНА проверка и выход — для Планировщика задач Windows
    python run_autopilot.py --daemon   # живой процесс: проверяет раз в 10 минут
    python run_autopilot.py --status   # показать вердикт и настройки, НИЧЕГО не запускать
    python run_autopilot.py --log      # хвост своего лога (data/autopilot.log) — «что случилось»
    python run_autopilot.py --install  # аварийно: поставить будильник в ОС + включить (штатно — фразой в чате)
    python run_autopilot.py --uninstall # аварийно: снять будильник + выключить

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
import os
import sys
import time

from connectors.telegram_publish import publish
from core import bot_alert, config, content_plan, logging_setup, runmode, schedule

logging_setup.setup()
log = logging.getLogger(__name__)

TG_ALERT_LIMIT = 3500   # запас под лимит Telegram (4096) — алерт не должен упасть на длинном отчёте
LOG_FILE = config.ROOT / "data" / "autopilot.log"


def _prepare_unattended() -> None:
    """Подготовить процесс к работе БЕЗ человека. Три конкретных провала, которых иначе не видно.

    1) КОДИРОВКА. Машина владельца — русский Windows (cp1251). Под Планировщиком задач вывод не в
       консоль, и Python берёт кодировку локали: первый же print с эмодзи (а их тут и в пайплайне
       много) упал бы с UnicodeEncodeError — прогон умер бы на печати, а не на деле.
    2) ЛОГИ. Общий logging пишет в stderr, который у задачи Планировщика уходит в никуда: при падении
       ДО отправки алерта не осталось бы никаких следов. Дублируем лог в data/autopilot.log
       (с ротацией, чтобы файл не рос вечно) — есть куда посмотреть после тихого сбоя.
    """
    # 3) НЕТ ВЫВОДА ВООБЩЕ. Задача Планировщика запускается через pythonw.exe (иначе каждые 30 минут
    #    мигало бы консольное окно). У pythonw sys.stdout = None, и первый же print упал бы с
    #    AttributeError — то есть «тихий» запуск убивал бы прогон. Подменяем на «в никуда»: рассказ
    #    прогона всё равно идёт в файловый лог, ради этого он и сделан.
    if sys.stdout is None or sys.stderr is None:
        devnull = open(os.devnull, "w", encoding="utf-8")   # noqa: SIM115 — живёт до конца процесса
        sys.stdout = sys.stdout or devnull
        sys.stderr = sys.stderr or devnull
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — нет reconfigure (перехваченный поток): не повод падать
            pass
    logging_setup.set_agent("autopilot")   # метка [autopilot/…] в КАЖДОЙ строке (конвенция P2-15)
    logging_setup.add_file_log(LOG_FILE)


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


def _emit(line: str = "") -> None:
    """Куда пайплайн рассказывает о себе: в консоль И в лог-файл.

    Без этого лог автопилота был БЕСПОЛЕЗЕН для ремонта: пайплайн ведёт рассказ через print (86 мест),
    а в logging пишет три строки — то есть на диске оставались обрывки, по которым не понять, где
    прогон встал. Теперь каждая строка прогона есть в data/autopilot.log с временем: видно и ГДЕ
    остановилось, и КОГДА. Многострочные блоки (готовый пост, итог-панель) разбиваем — иначе одна
    запись лога на 4000 знаков нечитаема.
    """
    print(line)
    for part in str(line).splitlines():
        if part.strip():
            log.info("прогон | %s", part.rstrip())


def _published_ok(report: str) -> bool:
    """Реально ли пост лёг в отложку. Прогон может «закончиться» и без публикации (нет повода, отказ
    планировщика) — тогда честный значок ⚠️, а не ✅: иначе владелец решит, что пост в очереди."""
    return "Поставил в отложенные" in report


def _run(kind: str, slot) -> None:
    """Реальный прогон: метка → пайплайн → отчёт владельцу. Исключения не пробрасываем наружу."""
    import run_pipeline  # ленивый импорт: --status не должен тянуть весь пайплайн

    logging_setup.new_request()
    schedule.mark_run(kind)   # ЗАЯВКА до прогона: падение не даст перезапускать и жечь деньги
    when = content_plan.human(slot)
    log.info("=== СТАРТ прогона '%s' → выход %s (режим боевой) ===", kind, when)
    bot_alert.notify_owner(f"🚀 Автопилот: запускаю {content_plan.kind_label(kind)} — "
                           f"выход в канал на {when}. Отчёт пришлю, как закончу (~10-20 мин).")
    try:
        report = run_pipeline.run_cycle(scope=False, evergreen=True, emit=_emit)
    except Exception as e:  # noqa: BLE001 — падение прогона обязано ДОЙТИ до владельца, а не в лог
        log.exception("=== ПРОГОН УПАЛ: %s ===", type(e).__name__)
        schedule.mark_result(kind, f"❌ упал: {type(e).__name__}: {e}"[:300])
        bot_alert.notify_owner(f"❌ Автопилот: прогон упал — {type(e).__name__}: {e}\n\n"
                               f"В канал ничего не ушло. Что смотреть: последние строки "
                               f"data/autopilot.log (или `run_autopilot.py --log`). "
                               f"Повторить руками: python run_pipeline.py")
        return
    ok = _published_ok(report)
    schedule.mark_result(kind, f"{'✅ в отложке на ' + when if ok else '⚠️ прогон прошёл, но пост НЕ поставлен'}")
    log.info("=== ПРОГОН ЗАВЕРШЁН: %s ===", "пост в отложке" if ok else "пост НЕ поставлен")
    bot_alert.notify_owner(f"{'✅' if ok else '⚠️'} Автопилот: прогон закончен "
                           f"({'пост в отложке на ' + when if ok else 'пост НЕ поставлен'}).\n\n{_digest(report)}")


def check_once() -> str:
    """Одна проверка. Возвращает короткий код исхода (для логов и --daemon): off/test/no-channel/skip/run."""
    if not schedule.enabled():
        # Пишем и в лог: строка «проверка была, но автопилот выключен» отвечает на половину вопросов
        # «почему в канале тишина» — видно, что задача Планировщика жива, а выключатель снят.
        log.info("выключен (нет файла %s) — ничего не делаю", schedule.ON_FILE.name)
        print(f"⏸ Автопилот ВЫКЛЮЧЕН (нет файла {schedule.ON_FILE.name}) — ничего не делаю.")
        return "off"
    channel = config.get_optional("PUBLISH_CHANNEL")
    if not channel:
        log.error("канал публикации не задан — прогон не начинаю")
        print("❌ PUBLISH_CHANNEL не задан — публиковать некуда, прогон не начинаю.")
        if not schedule.warned_today("no-channel"):   # проверки частые: алерт один раз в день, не спам
            bot_alert.notify_owner("❌ Автопилот: канал публикации не задан (PUBLISH_CHANNEL) — выход пропущен.")
            schedule.mark_warned("no-channel")
        return "no-channel"
    # ДВА ЗАХОДА, дешёвый сначала. Первый — без сети: день недели, окно, «сегодня уже гоняли». Только
    # если он говорит «пора», лезем в «Отложенные» канала (это MTProto-сессия бёрнера — трогать её
    # каждые 10 минут в понедельник незачем: и лишняя активность аккаунта, и медленно).
    verdict = schedule.due("flagship")
    if not verdict["go"]:
        log.info("пропуск: %s", verdict["why"])
        print(f"⏭ {verdict['why']}")
        return "skip"
    verdict = schedule.due("flagship", busy_dates=_busy_dates(channel))
    log.info("вердикт: %s — %s", "пора" if verdict["go"] else "пропуск", verdict["why"])
    print(f"{'✅' if verdict['go'] else '⏭'} {verdict['why']}")
    if not verdict["go"]:
        return "skip"
    mode = runmode.get()
    if mode["mode"] == "test":
        # /test = дешёвая модель для проверки механики. Такой пост в канал ставить нельзя.
        # Метку НЕ ставим: вернёшь /main внутри окна — прогон состоится в эту же проверку.
        log.warning("режим /test (модель %s) — публикацию не делаю", mode.get("model") or "?")
        print("🧪 Режим /test — публикацию НЕ делаю (в канал ушёл бы Haiku-пост). Верни /main.")
        if not schedule.warned_today("test-mode"):
            bot_alert.notify_owner("🧪 Автопилот: пора гнать флагман, но завод в режиме /test — "
                                   "публикацию не делаю. Верни /main, если выход нужен сегодня.")
            schedule.mark_warned("test-mode")
        return "test"
    _run("flagship", verdict["slot"])
    return "run"


def status() -> None:
    """Что автопилот думает прямо сейчас — без побочных действий (для чек-листа перед включением).

    Панель ОДНА для CLI и для /autopilot в боте (schedule.status_text) — чтобы в терминале и в чате
    владелец видел одно и то же, а не две расходящиеся правды.
    """
    print(schedule.status_text("flagship"))
    print(f"\nвыключатель: {schedule.ON_FILE}")


def tail_log(n: int = 60) -> None:
    """Показать хвост своего лога — «чинить оперативно» без раскопок файлов на Windows.

    Отдельная команда, потому что смотреть лог приходится ИМЕННО когда что-то не так, и в этот момент
    искать путь к файлу — лишний шаг. Полный файл: data/autopilot.log.
    """
    if not LOG_FILE.exists():
        print(f"Лога ещё нет ({LOG_FILE}) — автопилот ни разу не запускался в этом окружении.")
        return
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        print(f"Не смог прочитать {LOG_FILE}: {e}")
        return
    print(f"=== {LOG_FILE} — последние {min(n, len(lines))} из {len(lines)} строк ===")
    for ln in lines[-n:]:
        print(ln)


def main() -> None:
    _prepare_unattended()   # кодировка вывода + файловый лог: ДО первого print/лога, см. функцию
    # Аварийный путь на случай, когда бот Криейтора не запущен: штатно владелец включает/выключает
    # автопилот ФРАЗОЙ в чате, и будильник ставится там же (контракт «одна фраза = работает»).
    if "--install" in sys.argv or "--uninstall" in sys.argv:
        from core import os_task
        res = os_task.remove() if "--uninstall" in sys.argv else os_task.install()
        if "--install" in sys.argv and res["ok"]:
            schedule.turn_on("установлено из терминала")
        elif "--uninstall" in sys.argv:
            schedule.turn_off()
        print(("✅ " if res["ok"] else "❌ ") + res["detail"])
        print(schedule.status_text("flagship"))
        return
    if "--log" in sys.argv:
        tail_log()
        return
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
