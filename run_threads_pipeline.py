"""🧵 Threads-пайплайн: вышедший ТГ-пост → пост(ы) площадки. ДВА формата, свои правила у каждого.

    python run_threads_pipeline.py                 # мини-флагман (из вышедшего ТГ-флагмана)
    python run_threads_pipeline.py --scope         # мини-скоуп  (из вышедшего ТГ-скоупа)
    python run_threads_pipeline.py --review-only   # только показать, в отложку НЕ ставить
    python run_threads_pipeline.py --scope --old 3 # ОБКАТКА: третий с конца скоуп ИЗ ВЫГРУЗКИ канала

ЧЕТЫРЕ СВОДА ПРАВИЛ (площадка × формат) не смешиваются: ТГ-флагман, ТГ-скоуп, Threads-флагман,
Threads-скоуп. Формат выбирает, чей мануал/эталоны/уроки грузятся — см. core/threads_creator.

ОБКАТКА (Фаза 1): серию кладём в нативную «Отложенную» очередь ТГ-канала — ТЕМ ЖЕ механизмом, что
флагман/скоуп (telegram_publish, MTProto, слот content_plan) — чтобы увидеть посты живьём. Это НЕ
живая публикация: очередь на проверку, владелец смотрит/удаляет в «Отложенных».

⚠️ КУДА едет отложка: в THREADS_TEST_CHANNEL, а если он не задан — в общий PUBLISH_CHANNEL завода
(туда же, куда флагман/скоуп). Сейчас (решение владельца 15.07) PUBLISH_CHANNEL — ТЕСТОВЫЙ канал,
так что отдельный ключ не нужен: вся обкатка и так в тесте. Предупреждение в коде остаётся на
будущее: когда PUBLISH_CHANNEL станет боевым — либо заведи THREADS_TEST_CHANNEL, либо помни, что
Threads-серии лягут в общую отложку рядом с настоящими постами.

Реальная публикация в Threads (веха E) — отдельно; пока владелец ставит отложку руками в приложении.

Скаут в этой ветке НЕ участвует: Threads-формат ничего не разведывает — он перерабатывает уже готовый,
уже прошедший 2FA ТГ-пост (вход — core.published_journal). Анти-повтор/домен/ориентир — не нужны (пост
выверен до создания), это машинерия Формата 2. Изоляция от ТГ-мира: общий только нейтральный слой.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

from connectors.telegram_publish import publish as tg_publish
from core import (config, content_plan, cost, llm, logging_setup, runmode, threads_creator,
                  threads_lint, threads_source)

logging_setup.setup()

THREADS_SERIES_GAP_MIN = 10   # разнос постов серии по времени, чтобы легли ОТДЕЛЬНЫМИ отложенными


def _review_channel() -> str:
    """Куда кладём ревью-копии Threads. Ключ окружения главнее, иначе — настройка плана на диске.

    Почему две двери: файл с ключами закрыт хуком на запись (харденинг секретов), и завести туда
    канал самому нельзя — а владельцу «допиши строку руками» ради обкатки мешает работать. Поэтому
    канал ревью живёт ещё и в data/plan_settings.json (там же, где дни и время выхода): его правит
    чат, он переживает перезапуск и не смешивается с секретами. Приоритет у окружения — если владелец
    однажды пропишет ключ, он победит настройку из чата, а не наоборот."""
    from core import content_plan as cp
    return (config.get_optional("THREADS_TEST_CHANNEL")
            or str(cp.settings().get("threads_test_channel") or "").strip())


def _cover_on_disk(path: str) -> str:
    """Путь к обложке, который РЕАЛЬНО существует здесь. Пустая строка — картинки нет.

    В журнал путь пишется абсолютным, а завод живёт в двух местах: боевые прогоны идут на Windows,
    проверки — в контейнере на том же диске, но с другим корнем. Абсолютный путь из чужой среды не
    открывается, хотя файл лежит на месте, — поэтому вторым заходом ищем его по имени в data/source_media."""
    path = (path or "").strip()
    if not path:
        return ""
    if Path(path).exists():
        return path
    local = config.ROOT / "data" / "source_media" / Path(path.replace("\\", "/")).name
    return str(local) if local.exists() else ""


def run_threads_cycle(hint: str = "", publish: bool = True, emit=print, kind: str = "flagship",
                      back: int = 0) -> str:
    """Полный прогон Threads-формата: журнал → переработка по СВОЕМУ своду → ОТЛОЖКА ТГ-канала
    (тестового, если THREADS_TEST_CHANNEL задан; иначе боевого PUBLISH_CHANNEL — с предупреждением).

    kind — 'flagship' (мини-флагман) или 'scope' (мини-скоуп); имена общие с ТГ (content_plan).
    back — 0: последний вышедший пост из журнала (боевой путь); N≥1: N-й с конца пост этого формата
    ИЗ ВЫГРУЗКИ канала (обкатка на старых постах — их в журнале нет, он моложе).
    publish=False (или --review-only / тест-режим) — только показать, в отложку не ставить.
    emit — куда слать прогресс (print в терминал; бот передаёт свой коллектор, чтобы вернуть в чат)."""
    kind = content_plan.norm_kind(kind)
    fmt = threads_creator.spec(kind)
    report: list[str] = []

    def out(s: str = "") -> None:
        emit(s)
        report.append(s)

    cost.reset()
    out(f"=== 🧵 Threads · {fmt['label']} (переработка вышедшего {fmt['source_label']}а) ===\n")
    _mode = runmode.get()
    if _mode["mode"] == "test":
        out(f"🧪 ТЕСТ-режим: модель → {_mode['model']} (дёшево, НЕ для прода).\n")

    if threads_creator.manual_missing(kind):
        out(f"⛔ Свод правил формата «{fmt['label']}» ещё не написан ({fmt['manual']}). Пока он пуст — "
            "не пишу: модель добрала бы правила из соседнего формата, а это ровно то, чего мы не хотим.")
        out("\n" + cost.summary())
        return "\n".join(report)

    src = threads_source.resolve(kind, back)
    # Записи журнала, отброшенные сверкой с каналом, показываем ДО источника: владелец должен видеть, что
    # удалённый из отложки пост заметили, а не проигнорировали молча.
    for note in (src or {}).get("skipped") or []:
        out(f"⏭ Пропустил {fmt['source_label']} {note}")
    if not src or not src.get("text"):
        if src and src.get("why"):
            out(f"⛔ {src['why']}")
        else:
            where = (f"в выгрузке канала нет {back}-го с конца поста формата «{fmt['source_label']}»"
                     if back else
                     f"в журнале вышедших ТГ-постов нет ни одного формата «{fmt['source_label']}»")
            out(f"⛔ {where} — перерабатывать нечего.\n"
                f"   Боевой путь: опубликуй {fmt['source_label']} в ТГ (он запишется в журнал).\n"
                f"   Обкатка: возьми пост из истории канала — флаг --old N (1 = самый свежий).")
        out("\n" + cost.summary())
        return "\n".join(report)

    out(f"🧵 Источник: {fmt['source_label']} от {src.get('date', '?')} — "
        f"«{src.get('theme') or '(без темы)'}» [{src.get('origin', 'журнал')}], "
        f"{len(src['text'])} знаков")
    # Анти-повтор/домен/ориентир на мини-флагмане НЕ нужны: флагман уже прошёл все гейты (Скаут,
    # антиповтор темы, пикер, 2FA) ДО создания — мы его лишь дистиллируем. Эта машинерия — для Формата 2
    # (он originates контент), модули threads_dedup/orientation_digest ждут его, к мини-флагману не привязаны.
    out(f"✍️ Делаю {fmt['label']} (Sonnet, свой свод правил — без Скаута/2FA/обложки)...\n")
    try:
        series = threads_creator.write(kind, hint, src=src)   # ровно тот источник, что показан выше
    except Exception as e:
        out(f"❌ Дистилляция не удалась: {e}")
        out("\n" + cost.summary())
        return "\n".join(report)

    if series.startswith("⚠️"):      # threads_creator вернул отказ (пустой журнал) — показываем как есть
        out(series)
        out("\n" + cost.summary())
        return "\n".join(report)

    posts, guide = threads_creator.split_output(series)
    if not posts:
        # ПРИЧИНА, А НЕ КОНСТАТАЦИЯ (10.09): «модель ничего не выдала» отправляло чинить наугад.
        why = llm.empty_reason() or "модель ответила, но разбор не нашёл в тексте ни одного поста"
        out(f"⚠️ Серия пустая — {why}. Повтори прогон; если повторится — смотри лог вызова.")
        out("Сырой вывод:")
        out(series)
        out("\n" + cost.summary())
        return "\n".join(report)

    out(f"📝 --- {fmt['label'].upper()} · {len(posts)} пост(а) [THREADS] ---\n")
    for i, p in enumerate(posts, 1):
        over = f"  ⚠️ >{threads_creator.MAX_LEN} — Threads такой пост не примет" \
            if len(p) > threads_creator.MAX_LEN else ""
        out(f"🧵 [THREADS {i}/{len(posts)}]  ({len(p)} симв.{over})")
        out(p)
        out("")
    if threads_creator.LAST_LENGTH_NOTE:
        out(f"📏 Длина: {threads_creator.LAST_LENGTH_NOTE}\n")
    # ПРОВЕРКА ПО ЗАМЕРУ ВИРАЛЬНОСТИ (09.09.2026). Текст НЕ переписываем: линтер называет цену
    # («нет ставки» = ×3.6 мимо), решает автор в отложке. Проверено на 64 живых постах — у лидеров
    # корпуса претензий нет, у дна есть у всех, поэтому претензии можно читать всерьёз.
    lint_report = threads_lint.check_series(posts)
    if lint_report:
        out(lint_report + "\n")
    # Блок для ВЛАДЕЛЬЦА (что осталось в ТГ, какой спор пойдёт в ответах, что честно отвечать).
    # В отложку и в Threads он не идёт — это подсказка к дежурству в комментах, метод владельца Шаг 7.
    if guide:
        out("💬 --- ДЛЯ ТЕБЯ (не публикуется): что осталось в ТГ и как вести комменты ---")
        out(guide)
        out("")

    # ОБКАТКА: серию — в ОТЛОЖКУ тестового ТГ-канала (тем же механизмом, что флагман/скоуп). НЕ живая
    # публикация: очередь на проверку. В тест-режиме (дешёвая модель) и при --review-only — не ставим.
    if not publish or _mode["mode"] == "test":
        why = "тест-режим" if _mode["mode"] == "test" else "review-only"
        out(f"🧪 В отложку НЕ ставлю ({why}) — серия выше на проверку.")
        out("\n" + cost.summary())
        return "\n".join(report)
    channel = _review_channel()
    if not channel:
        channel = config.get_optional("PUBLISH_CHANNEL")
        if channel:
            out("ℹ️ THREADS_TEST_CHANNEL не задан — еду в общий PUBLISH_CHANNEL завода. Посты лягут "
                "в «Отложенные» рядом с флагманом/скоупом: если этот канал уже боевой — проверь и "
                "удали их оттуда, НЕ дай выйти в эфир.\n"
                "   Как развести: заведи ОТДЕЛЬНЫЙ тестовый канал под Threads, добавь бота-публикатора "
                "туда админом и пропиши ключ  THREADS_TEST_CHANNEL=@имя_канала  рядом с остальными "
                "ключами (файл окружения проекта).")
    if not channel:
        out("⚠️ Ни THREADS_TEST_CHANNEL, ни PUBLISH_CHANNEL не заданы в .env — публиковать некуда, "
            "серия осталась на ревью выше.")
        out("\n" + cost.summary())
        return "\n".join(report)
    out(f"\n🗓 Ставлю в ОТЛОЖКУ канала «{channel}» (ревью; это НЕ публикация в Threads)...")
    # ПРЕДПОЛЁТНАЯ ПРОВЕРКА: показать, КУДА именно резолвится канал. Приватный канал, названный просто
    # именем, Telegram может разрешить в ЧУЖОЙ публичный с тем же @username — тогда посты уехали бы не
    # туда (эту грабку уже ловили на ТГ-публикаторе). Название в отчёте = подтверждение адреса глазами.
    try:
        pre = tg_publish.check(channel)
        if pre.get("channel"):
            out(f"   Канал опознан: «{pre['channel']}» (аккаунт-публикатор {pre.get('account', '?')})")
        elif pre.get("channel_error"):
            out(f"   ⚠️ Канал НЕ опознан: {pre['channel_error']}")
    except Exception:
        out("   (предполётную проверку канала сделать не вышло — смотрю по факту публикации)")
    # Время в отложке — ПЛЕЙСХОЛДЕР: якорь-слот короткого формата, посты разнесены по 10 минут. Своего
    # времени выхода у Threads пока нет (открытый вопрос владельца) — когда будет, слот станет реальным
    # временем публикации в Threads, а отложка ревью-канала — пультом «оставить / поправить / удалить».
    base = content_plan.next_slot("short")
    # ОБЛОЖКА (решение владельца 09.09): мини-скоуп идёт с ТОЙ ЖЕ картинкой, что уже вышла с ТГ-постом
    # — искать и судить кадр заново незачем, он одобрен. Мини-флагману картинка не нужна вовсе.
    cover = _cover_on_disk(src.get("cover")) if kind == "scope" else ""
    if kind == "scope":
        if cover:
            out(f"🖼 Беру обложку ТГ-поста: {Path(cover).name}")
        elif src.get("cover"):
            out(f"🖼 Обложка ТГ-поста не найдена на диске ({src['cover']}) — ревью уйдёт текстом.")
        else:
            out("🖼 У исходного поста обложки в журнале нет (старый пост из выгрузки) — ревью текстом.")
    ok = 0
    for i, p in enumerate(posts):
        when = base + timedelta(minutes=THREADS_SERIES_GAP_MIN * i)
        body = f"🧵 [THREADS · {fmt['label']} {i + 1}/{len(posts)}]\n\n{p}"
        res = tg_publish.publish(channel, body, cover if i == 0 else None, when)
        if res.get("ok"):
            ok += 1
            out(f"  ✅ пост {i + 1}/{len(posts)} → {content_plan.human(when)} ({res.get('mode', '?')})")
        else:
            out(f"  ❌ пост {i + 1}/{len(posts)}: {res.get('error', '?')}")
    out(f"🗓 В отложке канала: {ok}/{len(posts)} постов. Проверь/поправь в нативных «Отложенных».")
    # ПРОВЕРКА: читаем отложенные обратно — подтвердить, что посты реально легли (а не «ok» вхолостую).
    # Тот же приём, что у ТГ-публикатора: «ok» от API ещё не значит, что сообщение видно в канале.
    try:
        out(f"   Проверка: в «Отложенных» канала «{channel}» сейчас "
            f"{len(tg_publish.scheduled_times(channel))} сообщ.")
    except Exception:
        out("   (проверку отложенных сделать не вышло — глянь канал глазами)")
    # УВЕДОМЛЕНИЕ НА МЕЙН — как после флагмана/скоупа: завод не имеет права молчать о том, что сделал.
    # Тот же ключ PUBLISH_NOTIFY и тот же аккаунт-публикатор, второй настройки не заводим.
    target = config.get_optional("PUBLISH_NOTIFY")
    if target and ok:
        first = content_plan.human(base)
        msg = (f"🧵 Threads · {fmt['label']}: {ok} пост(а) готовы и лежат в «Отложенных» канала "
               f"«{channel}» (первый на {first}).\n"
               f"Источник — {fmt['source_label']} от {src.get('date', '?')} ({src.get('origin', 'журнал')}).\n"
               "Проверь и поправь ПРЯМО В ОТЛОЖКЕ: в Threads уйдёт та версия, что там останется. "
               "Не годится — удали сообщение, и в Threads ничего не уйдёт.")
        # Претензии линтера идут В УВЕДОМЛЕНИЕ, а не в ревью-копию: копия — это ровно тот текст,
        # который уйдёт в Threads, и служебные строки в ней стали бы частью поста.
        if lint_report:
            msg += "\n\n" + lint_report[:700]
        n = tg_publish.notify(target, msg)
        out("📨 Уведомил мейн владельца." if n.get("ok")
            else f"📨 Уведомление на мейн НЕ ушло: {n.get('error', '?')}")
    # ОТМЕТКА ДЛЯ СБОРА АНАЛИТИКИ (решение владельца 09.09: «скрипт сбора работает только при
    # пайплайне скоуп Threads»). Своего расписания у сбора больше нет: он идёт в Meta только после
    # того, как этот пайплайн отработал. Связь — файл на диске, потому что браузер живёт на машине
    # владельца, а пайплайн в контейнере: запустить процесс Windows отсюда нельзя, оставить метку
    # на общем диске — можно. Метку кладём ПОСЛЕ успешной постановки в отложку: прогон, который
    # ничего не выдал, поводом ходить за цифрами не является.
    if kind == "scope" and ok:
        try:
            (config.ROOT / "data" / "threads_insights_request.txt").write_text(
                datetime.now(content_plan.tz()).isoformat(timespec="seconds") + "\n", encoding="ascii")
            out("📊 Отметил, что можно снять свежую аналитику Threads (снимет браузер владельца).")
        except Exception:  # noqa: BLE001 — метка вторична к посту
            out("   (отметку для сбора аналитики поставить не вышло — соберём следующим прогоном)")
    out("Публикация в сам Threads пока руками из приложения (авто-публикация из отложки — следующий шаг).")
    out("\n" + cost.summary())
    return "\n".join(report)


def _arg_old() -> int:
    """--old N → N (какой с конца пост канала брать). Без флага 0 = штатный путь через журнал."""
    if "--old" not in sys.argv:
        return 0
    i = sys.argv.index("--old")
    raw = sys.argv[i + 1] if len(sys.argv) > i + 1 else "1"
    return int(raw) if raw.isdigit() and int(raw) > 0 else 1


def main() -> None:
    logging_setup.set_agent("threads-pipeline")
    logging_setup.new_request()
    kind = "scope" if "--scope" in sys.argv else "flagship"
    run_threads_cycle(publish="--review-only" not in sys.argv, kind=kind, back=_arg_old())


if __name__ == "__main__":
    main()
