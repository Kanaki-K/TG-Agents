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
import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from connectors.telegram_publish import publish as tg_publish
from core import (config, content_plan, cost, llm, logging_setup, runmode, threads_creator,
                  threads_distill_journal, threads_lint, threads_source)

logging_setup.setup()

# Разнос постов серии (серия бывает только у мини-флагмана). Решение владельца 09.09 (THREADS_AUTONOMY §4):
# «первый тред в то же время, каждый следующий — через 2 часа». До 11.09.2026 стояло 10 минут.
THREADS_SERIES_GAP_MIN = 120


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
    name = Path(path.replace("\\", "/")).name
    for folder in ("journal_covers", "source_media"):
        local = config.ROOT / "data" / folder / name
        if local.exists():
            return str(local)
    return ""


def _series_times(kind: str, n: int) -> list[datetime]:
    """Время ревью-копий: слот СВОЕГО формата + шаг серии.

    До 11.09.2026 брался слот короткого формата для обоих: мини-флагман вторника вставал на среду (день
    скоупа), рядом с мини-скоупом и раньше самого ТГ-флагмана. content_plan знает форматы как 'flagship'
    и 'short' (скоуп — исторически короткий), поэтому имя переводим здесь."""
    base = content_plan.next_slot("flagship" if kind == "flagship" else "short")
    return [base + timedelta(minutes=THREADS_SERIES_GAP_MIN * i) for i in range(n)]


def _cover_for(src: dict) -> tuple[str, str]:
    """Обложка исходного ТГ-поста для мини-скоупа: (путь или "", строка для отчёта).

    Записи журнала с 11.09.2026 ссылаются на КОПИЮ обложки в data/journal_covers — ей верим. Старые
    ссылаются прямо на кадр в data/source_media, а его имя (scope_1_0.jpg) переиспользует каждый ТГ-прогон:
    к 11.09 обложки записей 09.09 и 10.09 уже были картинками другого поста. Файл изменён позже дня записи —
    не берём: ревью текстом честнее, чем чужая картинка под подписью «обложка ТГ-поста»."""
    raw = (src.get("cover") or "").strip()
    if not raw:
        return "", "🖼 У исходного поста обложки в журнале нет (старый пост из выгрузки) — ревью текстом."
    path = _cover_on_disk(raw)
    if not path:
        return "", f"🖼 Обложка ТГ-поста не найдена на диске ({raw}) — ревью уйдёт текстом."
    if Path(path).parent.name == "source_media":
        try:
            changed = datetime.fromtimestamp(Path(path).stat().st_mtime).date()
            posted = date.fromisoformat((src.get("date") or "")[:10])
        except (OSError, ValueError):
            changed = posted = None
        if changed and posted and changed > posted:
            return "", (f"🖼 ⚠️ Обложку НЕ беру: {Path(path).name} перезаписан ТГ-прогоном {changed:%d.%m}, "
                        "это уже картинка другого поста. Ревью уйдёт текстом — поставь картинку ТГ-поста руками.")
    return path, f"🖼 Беру обложку ТГ-поста: {Path(path).name}"


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
    # Два предупреждения отдельными строками, а не в скобках «Источника» (ревью 11.09.2026): оба значат, что
    # в Threads может уйти не то, и оба же повторяются в уведомлении на мейн.
    if src.get("unverified"):
        out("⚠️ КАНАЛ НЕ ПРОЧИТАН — не проверил, остался ли этот пост в ТГ-отложке. Если ты его удалил, "
            "удали и Threads-версию из ревью.")
    if src.get("repeat"):
        out(f"⚠️ ПОВТОР: этот пост уже перерабатывали в Threads {src['repeat']}. Нужна ли вторая версия — реши в ревью.")
    # Анти-повтор/домен/ориентир на мини-флагмане НЕ нужны: флагман уже прошёл все гейты (Скаут,
    # антиповтор темы, пикер, 2FA) ДО создания — мы его лишь дистиллируем. Эта машинерия — для Формата 2
    # (он originates контент), модули threads_dedup/orientation_digest ждут его, к мини-флагману не привязаны.
    out(f"✍️ Делаю {fmt['label']} (Sonnet, свой свод правил — без Скаута/2FA/обложки)...\n")
    try:
        # ровно тот источник, что показан выше; в журнал переработок пишем ниже — только поставленное в отложку
        series = threads_creator.write(kind, hint, src=src, record=False)
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
            # Стоп, а не «посмотрим по факту»: неопознанный адрес Telegram может разрешить в чужой канал с
            # похожим именем — серия уехала бы не туда (аудит 11.09.2026). Серия выше остаётся на ревью.
            out(f"   ⛔ Канал НЕ опознан: {pre['channel_error']} — не ставлю, серия выше осталась на ревью.")
            out("\n" + cost.summary())
            return "\n".join(report)
    except Exception:
        out("   (предполётную проверку канала сделать не вышло — смотрю по факту публикации)")
    # Время в отложке: слот своего формата, серия флагмана — через 2 часа (_series_times). Когда появится
    # авто-публикация в Threads, это станет реальным временем выхода, а отложка ревью — пультом.
    times = _series_times(kind, len(posts))
    # ОБЛОЖКА (решение владельца 09.09): мини-скоуп идёт с ТОЙ ЖЕ картинкой, что уже вышла с ТГ-постом
    # — искать и судить кадр заново незачем, он одобрен. Мини-флагману картинка не нужна вовсе.
    cover, cover_note = _cover_for(src) if kind == "scope" else ("", "")
    if cover_note:
        out(cover_note)
    ok = 0
    landed: list[str] = []      # что реально легло — только это идёт в журнал переработок
    failed: list[int] = []      # номера упавших — владелец узнаёт о них из уведомления
    for i, p in enumerate(posts):
        when = times[i]
        # Копия — РОВНО текст для Threads, без служебной шапки «🧵 [THREADS · …]»: владелец копирует пост
        # целиком, а уведомление обещает «уйдёт та версия, что в отложке» — шапка ушла бы в Threads (аудит
        # 11.09.2026). Порядок серии и так виден: посты стоят через THREADS_SERIES_GAP_MIN минут.
        res = tg_publish.publish(channel, p, cover if i == 0 else None, when)
        if res.get("ok"):
            ok += 1
            landed.append(p)
            out(f"  ✅ пост {i + 1}/{len(posts)} → {content_plan.human(when)} ({res.get('mode', '?')})")
        else:
            failed.append(i + 1)
            out(f"  ❌ пост {i + 1}/{len(posts)}: {res.get('error', '?')}")
    out(f"🗓 В отложке канала: {ok}/{len(posts)} постов. Проверь/поправь в нативных «Отложенных».")
    # Связь «ТГ-пост → Threads-версия» — только для легших постов: сверщик потом ищет их в Threads, а
    # упавший №2 серии там не появится никогда (аудит 11.09.2026). См. threads_creator.write(record=False).
    if landed:
        threads_distill_journal.record(src, ("\n" + threads_creator.POST_SEP + "\n").join(landed),
                                       threads_creator.POST_SEP)
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
    if target and (ok or failed):
        first = content_plan.human(times[0])
        msg = (f"🧵 Threads · {fmt['label']}: {ok} пост(а) готовы и лежат в «Отложенных» канала "
               f"«{channel}» (первый на {first}).\n"
               f"Источник — {fmt['source_label']} от {src.get('date', '?')} ({src.get('origin', 'журнал')}).\n"
               "Проверь и поправь ПРЯМО В ОТЛОЖКЕ: в Threads уйдёт та версия, что там останется. "
               "Не годится — удали сообщение, и в Threads ничего не уйдёт.")
        if src.get("unverified"):
            msg += "\n⚠️ Канал не прочитан: не проверил, что ТГ-пост остался в отложке."
        if src.get("repeat"):
            msg += f"\n⚠️ Повтор: этот ТГ-пост уже перерабатывали в Threads {src['repeat']}."
        # Провал постановки — тоже повод написать: без человека у терминала молчание = «всё хорошо».
        if failed:
            msg += f"\n❌ Не легли в отложку: №{', №'.join(map(str, failed))} — причина в отчёте прогона."
        if not ok:
            msg = (f"❌ Threads · {fmt['label']}: ни один из {len(posts)} пост(ов) не лёг в отложку канала "
                   f"«{channel}». Причина в отчёте прогона, серия там же.")
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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Строгий разбор командной строки: опечатка — ошибка, а не молчаливый другой режим.

    Аудит 11.09.2026: разбор по `in sys.argv` запускал на `-scope` мини-ФЛАГМАН и ставил его в отложку,
    `--old=3` молча игнорировал (шёл журнальный путь), а `--old 0` превращал в 1 (выгрузка вместо журнала)."""
    ap = argparse.ArgumentParser(prog="run_threads_pipeline.py",
                                 description="Threads-пайплайн: вышедший ТГ-пост → пост(ы) Threads.")
    ap.add_argument("--scope", action="store_true", help="мини-скоуп (без флага — мини-флагман)")
    ap.add_argument("--review-only", action="store_true", help="только показать, в отложку не ставить")
    ap.add_argument("--old", nargs="?", const=1, type=int, metavar="N",
                    help="обкатка: N-й с конца пост формата из выгрузки канала (1 = самый свежий)")
    args = ap.parse_args(argv)
    if args.old is not None and args.old < 1:
        ap.error("--old N: N начинается с 1 (1 = самый свежий пост канала)")
    return args


def main() -> None:
    # Эмодзи в выводе: консоль русского Windows (cp1251) или перенаправление в файл падали бы на первой же
    # строке «=== 🧵». Тот же приём, что в run_autopilot.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — нет reconfigure (перехваченный поток): не повод падать
            pass
    args = _parse_args()
    logging_setup.set_agent("threads-pipeline")
    logging_setup.new_request()
    run_threads_cycle(publish=not args.review_only, kind="scope" if args.scope else "flagship",
                      back=args.old or 0)


if __name__ == "__main__":
    main()
