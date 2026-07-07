"""Полная цепочка контент-завода ОДНИМ запуском (оркестратор v0 — ручной триггер):

    python run_pipeline.py                # флагман на свежую тему: Скаут → пост → отложка
    python run_pipeline.py --evergreen    # флагман на вечную тему из банка (без Скаута)
    python run_pipeline.py --scope        # короткий 🔭 «Под прицелом» (аналитич., обложка из первоисточника) → отложка
    python run_pipeline.py --skip-scout   # БЕЗ Скаута: Криейтор берёт ПОСЛЕДНИЙ бриф
    python run_pipeline.py --no-image     # БЕЗ GPT-обложки (только текст). В /test-режиме включается САМ.

МИКС 2×/нед: один флагман запускай обычно (топикал, свежая тема), второй — с --evergreen (вечная
из банка). Так канал не «новостник» и не «без актуальности». Вечная тема Скаута не гоняет — дешевле.

Скаут НЕ дёргается впустую: если последний бриф разведки младше SCOUT_FRESH_HOURS (3ч) — прогон берёт
его, повторный поиск пропускается (--skip-scout форсит пропуск всегда; свежесть и так бережёт кредиты).

В день публикации прогоняет цепь без твоего участия в передаче:
  0) Актуальность данных — если выгрузка канала устарела (>12ч), тянет свежие посты (collect +
     enrich_topics), чтобы анти-повтор сверялся с тем, что РЕАЛЬНО уже опубликовано (core/dedup);
  1) Скаут — разведка → бриф (топ-темы) в memory/briefs/ [можно пропустить --skip-scout];
  1.5) Анти-повтор (флагман) — сверяет направления брифа с историей канала: повтор → берёт другую
     тему; ВСЕ повторы → пост не делает (дубль в канал не уйдёт);
  2) Криейтор — утверждённая НЕ-повторная тема: пост + обложка (make_image), сохраняет драфт;
  3) Постановка — нативная ОТЛОЖКА в канал на слот контент-плана + уведомление на @Kanaki_K.
Дальше проверяешь готовый пост в нативных «Отложенных» канала.

llm.reply каждого агента гоняется в ОТДЕЛЬНОМ потоке (как в боте через asyncio.to_thread): так
make_image (playwright-браузер) получает рабочий event-loop на Windows (иначе NotImplementedError).
Шаги 1-2 стоят кредитов Claude; шаг 3 (отложка) — нет. Любой шаг упал — печатаем причину; если пост
не родился — публикацию пропускаем (пустое в канал не уйдёт). База будущего оркестратора по расписанию.
"""
import concurrent.futures
import datetime
import logging
import sys
import time
from pathlib import Path

from core import (config, cost, creator_bot, creator_tools, dedup, llm, runmode, scope_writer,
                  scout_bot, scout_tools, verify)

logging.basicConfig(level=logging.INFO)

SCOUT_FRESH_HOURS = 3  # бриф свежее этого — повторную разведку не запускаем (бережём кредиты)
# Дни ГЛУБОКОЙ разведки: Пн=0, Вт=1, Чт=3. В остальные дни берём последний бриф из «банка» — мы НЕ
# новостник (горячка не цель), мануал Скаута + актуальность важнее свежей разведки на каждый пост.
# Скаут с ~6×/нед → 3×/нед. Если брифа в банке вообще нет — разведка запустится в любой день.
SCOUT_DAYS = {0, 1, 3}


def _latest_brief_age_hours() -> float | None:
    """Возраст последнего НЕ-недельного брифа разведки в часах (None — брифов нет)."""
    d = scout_tools.BRIEFS_DIR
    if not d.exists():
        return None
    files = [p for p in d.glob("*.md") if "weekly" not in p.stem]
    if not files:
        return None
    newest = max(p.stat().st_mtime for p in files)
    return (time.time() - newest) / 3600.0


def _latest_draft_mtime() -> float:
    """mtime самого свежего драфта (0 — драфтов нет). Гейт «пост создан в ЭТОМ прогоне»: сравниваем
    до и после генерации — если новее не появилось, scope/Криейтор отказался и публиковать НЕЧЕГО."""
    files = creator_tools._md_files(creator_tools.DRAFTS_DIR)
    return files[0].stat().st_mtime if files else 0.0


def _threaded(fn, *args):
    """Выполнить в отдельном потоке (как asyncio.to_thread в боте) — нужно для playwright на Windows."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(fn, *args).result()


def _agent(name: str):
    cfg = config.load_agent(name)
    thinking = {"type": "adaptive"} if cfg.get("thinking") == "adaptive" else None
    # модель резолвим через runmode: /test (или env MODEL_OVERRIDE) делает прогон дешёвым
    return cfg, runmode.resolve(cfg["model"]), config.agent_api_key(cfg), thinking


def _run_scout(scope: bool = False) -> None:
    cfg, model, key, thinking = _agent("scout")
    tools = list(scout_tools.TOOLS)
    if cfg.get("web_search"):
        tools.append(scout_bot.WEB_SEARCH_TOOL)
    cost.set_context("scout")
    print("🔍 [1/3] Скаут: разведка трендов...")
    # coverage-зрение Скаута — ТОЛЬКО во флагман-прогоне; scope получает пре-сессионного Скаута.
    text, _ = _threaded(llm.reply, model, scout_bot._system(coverage=not scope), [],
                        scout_bot.COMMANDS["scan"], tools, scout_tools.dispatch, key, thinking)
    print((text or "(пусто)").strip()[:700], "\n")


def _run_creator(command: str = "post", avoid: str = "", hint: str = "", bank: list | None = None,
                 evergreen: bool = False, no_image: bool = False) -> str:
    cfg, model, key, thinking = _agent("creator")
    # no_image (тест/итерация): убираем make_image из инструментов — GPT-обложку не дёргаем вообще.
    tools = [t for t in creator_tools.TOOLS if not (no_image and t.get("name") == "make_image")]
    if cfg.get("web_search"):
        tools.append(creator_bot.WEB_SEARCH_TOOL)
    try:  # свежий аутбокс обложки — только картинка этого прогона (scope её не делает → отложка текстом)
        if creator_tools.MEDIA_OUTBOX.exists():
            creator_tools.MEDIA_OUTBOX.unlink()
    except Exception:
        pass
    cost.set_context("creator")
    _cover = "без обложки" if no_image else "+ обложка"
    label = ("короткий 🔭 «Под прицелом» (без обложки)" if command == "scope"
             else f"ВЕЧНАЯ тема из банка ({_cover})" if evergreen
             else f"пост по свежему брифу ({_cover})")
    print(f"✍️ [2/3] Криейтор: {label}...")
    user = creator_bot.COMMANDS[command]
    if no_image:  # тест/итерация — не трогаем GPT: картинку не делаем, только текст
        user = ("БЕЗ ОБЛОЖКИ (тест/итерация): make_image НЕ вызывай, картинку не делай — выдай только "
                "готовый текст поста и сохрани через save_draft.\n\n") + user
    if evergreen:  # ВЕЧНАЯ ТЕМА: осознанно НЕ новость — образовательный флагман из банка вечных тем.
        guard = ("Пиши образовательный флагман на ВЕЧНУЮ тему (не новость, не из поводов брифа). "
                 "Возьми ОДНУ тему из банка:\n"
                 + "\n".join(f"- {t}" for t in (bank or [])) + "\n"
                 "— которой НЕ было на канале за последние ~6 месяцев (сверь с постами в контексте; учитывай "
                 "и соседний домен: «смерть альтов» = «90% умирают» = «выживают лидеры»).\n"
                 "ЗАГОЛОВОК, ГОЛОС и ПОДАЧУ равняй на эталоны в контексте — они твой образец, не изобретай "
                 "своё и не своди пост к морали про DCA. Готовый пост, сохрани save_draft.\n\n")
        user = guard + user
    elif avoid or hint or bank:  # СВЕЖАЯ ТЕМА: из брифа, иначе падаем в банк.
        guard = "АНТИ-ПОВТОР (сверено со свежей выгрузкой канала).\n"
        if avoid:
            guard += f"НЕ бери эти направления (уже выходили / домен на паузе): {avoid}.\n"
        if hint:
            guard += f"В брифе как сильный НЕ-повтор выглядит «{hint}» (подсказка, не приказ).\n"
        if bank:
            guard += ("ВАЖНО: если в брифе НЕТ ни одной реально свежей темы (всё уже выходило на канале / "
                      "уже отрисовано в твоих драфтах / домен на паузе) — НЕ пиши дубль и НЕ уходи в "
                      "рассуждения «какой драфт выбрать». Возьми ОДНУ ВЕЧНУЮ тему из банка и раскрой её "
                      "своей обычной подачей (не новость, не пересказ старого поста):\n"
                      + "\n".join(f"- {t}" for t in bank) + "\n")
        guard += ("Выбери сильнейшую СВЕЖУЮ тему (свежая из брифа — если есть; иначе из банка) и НАПИШИ "
                  "ГОТОВЫЙ ПОСТ — текст, не мета-рассуждение. Обязательно сохрани через save_draft.\n\n")
        user = guard + user
    text, _ = _threaded(llm.reply, model, creator_bot._system(), [], user,
                        tools, creator_tools.dispatch, key, thinking)
    print((text or "(пусто)").strip()[:700], "\n")
    return text or ""


def _run_scope(avoid: str = "") -> str:
    """🔭 «Под прицелом» — ОТДЕЛЬНАЯ ветка (core/scope_writer): свой лёгкий контекст + модель + 2FA
    внутри. Обложку НЕ рисует (не GPT), но ТЯНЕТ картинку из ПЕРВОИСТОЧНИКА повода (og:image + vision-
    гейт) — путь кладёт в SCOPE_COVER; нет годной → уйдёт текстом. Флагман-аутбокс к scope не относится."""
    try:  # флагман-аутбокс GPT-обложки чистим — scope им не пользуется (у него свой SCOPE_COVER)
        if creator_tools.MEDIA_OUTBOX.exists():
            creator_tools.MEDIA_OUTBOX.unlink()
    except Exception:
        pass
    cost.set_context("scope")
    print("✍️ [2/3] 🔭 Под прицелом: короткий аналитический (отдельная ветка, обложка из первоисточника)...")
    text = _threaded(scope_writer.write, "", avoid)
    print((text or "(пусто)").strip()[:700], "\n")
    return text or ""


def _run_creator_fix(post: str, verdict: str) -> str:
    """Криейтор САМ правит факты по вердикту 2FA (конфликт→верное, неподтверждённое→убрать/смягчить)."""
    cfg, model, key, thinking = _agent("creator")
    tools = list(creator_tools.TOOLS)
    if cfg.get("web_search"):
        tools.append(creator_bot.WEB_SEARCH_TOOL)
    cost.set_context("creator-fix")
    user = creator_bot.FIX_FACTS.format(post=post.split("[[SPLIT]]")[0], verdict=verdict)
    text, _ = _threaded(llm.reply, model, creator_bot._system(), [], user,
                        tools, creator_tools.dispatch, key, thinking)
    return text or post


def run_cycle(scope: bool = False, skip_scout: bool = False, draft_only: bool = False,
              evergreen: bool = False, no_image: bool = False, emit=print) -> str:
    """Полный прогон цепи (свежесть→Скаут→анти-повтор→Криейтор/scope→2FA→отложка). ВОЗВРАЩАЕТ отчёт.

    emit — куда слать прогресс по ходу: по умолчанию print (терминал); бот передаёт свой коллектор,
    чтобы вернуть отчёт в чат. Вынесено из main(), чтобы тот же цикл дёргать и из бота (там — ленивый
    импорт run_pipeline во избежание циклического импорта: run_pipeline сам импортирует creator_bot).
    """
    report: list[str] = []

    def out(s: str = "") -> None:
        emit(s)
        report.append(s)

    cost.reset()  # начинаем замер стоимости всего прогона (Скаут→Криейтор→отложка)
    kind = ("🔭 Под прицелом (короткий)" if scope
            else "флагман (вечная тема из банка)" if evergreen
            else "флагман (свежая тема)")
    out(f"=== Контент-завод: прогон [{kind}] ===\n")
    _mode = runmode.get()
    if _mode["mode"] == "test":
        out(f"🧪 ТЕСТ-режим: все модели → {_mode['model']} (дёшево, НЕ для прода). /main в боте — боевой.\n")
        no_image = True  # в тесте GPT-обложку НЕ дёргаем (её качество не тестим — экономим)
    if no_image and not scope:
        out("🖼 GPT-обложку не делаю (тест/--no-image) — только текст.\n")
    # АКТУАЛЬНОСТЬ ДАННЫХ: выгрузка канала устарела → тянем свежие посты ДО разведки и анти-повтора
    # (иначе сверка «было/не было» врёт на самых недавних постах — там и прячется самый частый дубль).
    out("🗂 [0] Актуальность данных канала (для анти-повтора)...")
    out(str(dedup.refresh_if_stale()) + "\n")
    age = _latest_brief_age_hours()
    scout_day = datetime.date.today().weekday() in SCOUT_DAYS
    if skip_scout or evergreen:
        out("⏭ Скаута пропускаю — вечная тема из банка, разведка не нужна.\n"
            if evergreen else
            "⏭ Скаута пропускаю (--skip-scout): Криейтор возьмёт последний бриф.\n")
    elif age is not None and age < SCOUT_FRESH_HOURS:
        out(f"⏭ Скаута пропускаю: последний бриф свежий ({age:.1f}ч < {SCOUT_FRESH_HOURS}ч) — "
            f"повторная разведка не нужна, берём его.\n")
    elif age is not None and not scout_day:
        out(f"⏭ Скаута пропускаю: сегодня не день разведки (глубокий поиск Пн/Вт/Чт) — беру последний "
            f"бриф из банка ({age:.1f}ч). Мы не новостник: мануал Скаута + актуальность важнее горячки.\n")
    else:
        if age is None:
            out("🔄 Брифа в банке нет — запускаю разведку (даже вне дня поиска: писать не из чего).\n")
        else:
            out(f"🔄 Последний бриф старше {SCOUT_FRESH_HOURS}ч ({age:.1f}ч), сегодня день разведки — "
                f"запускаю свежую.\n")
        try:
            _run_scout(scope)
        except Exception:
            logging.exception("Скаут упал — продолжаю на последнем имеющемся брифе (если он есть)")
    # АНТИ-ПОВТОР — ВЕТКИ РАЗДЕЛЕНЫ (scope и флагман не мешают друг другу):
    #  • SCOPE — как ДО этой сессии: независимый Haiku-дедуп (repeat_themes + all_repeats-стоп) +
    #    финальный детерминированный _hits_paused ниже. Эту ветку НЕ трогаем.
    #  • ФЛАГМАН (доработка сессии) — Криейтор САМ видит покрытие канала (topics_digest в его контексте)
    #    и берёт тему из банка; отдельный Haiku-проход ему не нужен, avoid/hint пустые.
    avoid = hint = ""
    if scope:
        try:
            cost.set_context("dedup")  # чтобы анти-повтор логировался под своей меткой, не под чужой
            verdict = dedup.check(verify.latest_brief(),
                                  api_key=config.agent_api_key(config.load_agent("creator")))
            out("🔁 [Анти-повтор] Сверка тем брифа с уже опубликованным (свежая выгрузка):")
            out(str(verdict) + "\n")
            if dedup.all_repeats(verdict):
                out("⛔ Все направления брифа — повторы уже вышедших постов. Пост НЕ делаю — дубль в "
                    "канал не уйдёт. Нужна свежая разведка (/scan у Скаута) или новый угол.")
                return "\n".join(report)
            avoid = dedup.repeat_themes(verdict)
        except Exception:
            logging.exception("Анти-повтор не сработал — не блокирую, тему дальше берём из брифа сами")
    # Банк вечных тем ВСЕГДА под рукой у флагмана: если бриф исчерпан (всё уже выходило/отрисовано) или
    # домен на паузе — Криейтор берёт тему оттуда и пишет, а не впадает в ступор «какой драфт выбрать».
    bank = dedup.bank_topics() if not scope else []
    if bank:
        out(f"🧭 Банк вечных тем подключён ({len(bank)} шт.) — если в брифе всё уже выходило, тема берётся оттуда.\n")
    pre_mtime = _latest_draft_mtime()  # снимок ДО генерации: публикуем только если появится НОВЕЕ
    try:
        # scope — ОТДЕЛЬНАЯ ветка (свой лёгкий контекст/модель + встроенный 2FA), флагман — Криейтор.
        post = _run_scope(avoid) if scope else _run_creator("post", avoid, hint, bank,
                                                            evergreen=evergreen, no_image=no_image)
    except Exception as e:
        out(f"❌ Пост не сделан: {e}\nПостановку в отложку пропускаю — в канал ничего не уйдёт.")
        return "\n".join(report)
    # ЖЁСТКИЙ СТОП scope (детерминированно, как у флагмана): scope сам себя не ловит — если написал повод
    # из paused/затёртого домена (x402/стейблы/смена-рук/Strategy…), код заворачивает. В канал не идёт:
    # лучше молчать, чем фастфуд-новость по обдроченной теме. Список пауз — core/dedup.py PAUSED_DOMAINS.
    if scope and post:
        _hit = dedup._hits_paused(post)
        if _hit:
            out(f"⛔ scope написал затёртый/paused-домен («{_hit}») — НЕ публикую. Повод обдрочен, лучше "
                "молчать, чем гнать фастфуд. Список пауз правится в core/dedup.py (PAUSED_DOMAINS).")
            out("\n" + cost.summary())
            return "\n".join(report)
    # 2FA флагмана (Sonnet): нашёл замечания → Криейтор САМ исправляет → перепроверка. У scope свой
    # 2FA уже прошёл внутри его ветки — здесь его НЕ дублируем.
    if post and not scope:
        ckey = config.agent_api_key(config.load_agent("creator"))
        out("🔎 [Фактчек 2FA] Независимая проверка цифр/фактов (Sonnet)...")
        try:
            verdict = verify.verify_post(post, verify.latest_brief(), api_key=ckey)
            out(str(verdict) + "\n")
            if verify.has_issues(verdict):
                out("🛠 Есть замечания — Криейтор исправляет САМ (без твоей проверки)...")
                post = _run_creator_fix(post, verdict)
                out((post or "").strip()[:600] + "\n")
                out("🔎 Повторный фактчек после правок:")
                out(str(verify.verify_post(post, verify.latest_brief(), api_key=ckey)) + "\n")
        except Exception:
            logging.exception("Фактчек 2FA не удался — пост НЕ блокирую, ставлю как есть")
    out("📝 --- ГОТОВЫЙ ПОСТ ---")
    out((post or "").strip())
    # ГЕЙТ «свежий пост»: публикуем ТОЛЬКО если в этом прогоне сохранён НОВЫЙ драфт. scope/Криейтор мог
    # ОТКАЗАТЬСЯ писать (нет свежего повода — штатно) и не вызвать save_draft — тогда самый свежий драфт
    # на диске СТАРЫЙ (из архива), и publish_now поставил бы в канал его (был баг: старый флагман ушёл под
    # меткой «короткий»). Нет нового драфта → НИЧЕГО не публикуем и обложку не трогаем.
    if _latest_draft_mtime() <= pre_mtime:
        out("\n⛔ Свежего поста в этом прогоне НЕ создано (scope/Криейтор не сохранил драфт — вероятно, "
            "нет подходящего повода). В отложку НИЧЕГО не ставлю — старый драфт из архива в канал не уйдёт.")
        out("\n" + cost.summary())
        return "\n".join(report)
    if draft_only:  # тест-режим: драфт готов и напечатан — обложку GPT НЕ генерим и в отложку НЕ ставим
        out("\n🧪 draft-only: драфт выше. Обложку GPT НЕ генерирую и в отложку НЕ ставлю (смотрим тему/текст).")
        out("\n" + cost.summary())
        return "\n".join(report)
    # ОБЛОЖКА флагмана: 2FA-фикс пересохраняет драфт ПОЗЖЕ make_image — и mtime-гейт publish_now ронял
    # валидную обложку в текст. Берём обложку ЭТОГО прогона из аутбокса и передаём publish_now ЯВНО (минуя
    # гейт). Аутбокс пуст (Криейтор не вызвал make_image в длинном ТЗ) → генерим САМИ из ФИНАЛЬНОГО поста:
    # одна генерация, лимит бережём, заголовок берём из финала. scope — своя ветка обложки ниже (из
    # первоисточника, не GPT): путь берём из SCOPE_COVER, который положил scope_writer.
    cover_path = ""
    if not scope and (post or "").strip():
        try:
            ob = creator_tools.MEDIA_OUTBOX
            have = [l.strip() for l in ob.read_text(encoding="utf-8").splitlines() if l.strip()] \
                if ob.exists() else []
            if have:
                out("🖼 Обложка прогона есть (Криейтор вызвал make_image в ходе) — прицеплю её.")
            else:
                body = post.split("[[SPLIT]]")[0]
                title = next((l.strip() for l in body.splitlines() if l.strip()), "").replace("**", "")
                out("🖼 Обложки в прогоне нет (Криейтор не вызвал make_image) — генерирую из финала через GPT...")
                out(str(_threaded(creator_tools.dispatch, "make_image",
                                  {"title": title, "post_text": body})))
                have = [l.strip() for l in ob.read_text(encoding="utf-8").splitlines() if l.strip()] \
                    if ob.exists() else []
            cover_path = have[-1] if have else ""
            out(f"🖼 Обложка к публикации: {cover_path}" if cover_path
                else "⚠️ Обложку получить не удалось — флагман уйдёт ТЕКСТОМ.")
        except Exception:
            logging.exception("обложка: не смог получить/сгенерить — флагман уйдёт текстом")
    elif scope and (post or "").strip():
        # Картинка для 🔭 ОБЯЗАТЕЛЬНА (правило владельца: без картинки пост не нужен). scope достал og:image
        # со статей-кандидатов, vision выбрал подходящую по смыслу → путь в SCOPE_COVER. Пусто → НЕ публикуем.
        try:
            sc = creator_tools.SCOPE_COVER
            cp = sc.read_text(encoding="utf-8").strip() if sc.exists() else ""
            cover_path = cp if cp and Path(cp).exists() else ""
        except Exception:
            logging.exception("scope-обложка: не смог подхватить SCOPE_COVER")
            cover_path = ""
        if not cover_path:
            out("\n⛔ У 🔭-поста НЕТ подходящей картинки — по правилу «без картинки не публикуем» в отложку "
                "НЕ ставлю. Драфт сохранён в архиве (добавь картинку вручную или пропусти повод).")
            out("\n" + cost.summary())
            return "\n".join(report)
        out(f"🖼 Обложка выбрана (по смыслу подходит посту): {cover_path}")
    out("\n🗓 [3/3] Ставлю в отложенные канала...")
    out(str(_threaded(creator_tools.dispatch, "publish_now",
                      {"kind": "short" if scope else "", "cover": cover_path})))
    out("\n=== Готово. Проверь пост в нативных «Отложенных» канала. ===")
    out("\n" + cost.summary())  # реальная цена прогона Скаут→пост в $
    return "\n".join(report)


def main() -> None:
    run_cycle(scope="--scope" in sys.argv, skip_scout="--skip-scout" in sys.argv,
              draft_only="--draft-only" in sys.argv, evergreen="--evergreen" in sys.argv,
              no_image="--no-image" in sys.argv)


if __name__ == "__main__":
    main()
