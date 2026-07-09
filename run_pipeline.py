"""Полная цепочка контент-завода ОДНИМ запуском (оркестратор v0 — ручной триггер):

    python run_pipeline.py                # ФЛАГМАН: тема из банка (польза) + свежий якорь (актуальность) → отложка
    python run_pipeline.py --scope        # 🔭 «Под прицелом» — НОВОСТНОЙ короткий (Скаут+свежесть, обложка из первоисточника)
    python run_pipeline.py --draft-only   # драфт без публикации (тест/итерация)
    python run_pipeline.py --no-image     # БЕЗ GPT-обложки (только текст). В /test-режиме включается САМ.

МОДЕЛЬ А: флагман = ПОЛЬЗА (тема ВСЕГДА из банка, бренд-ядро) + АКТУАЛЬНОСТЬ (Криейтор якорит свежей
цифрой/примером). Новость как ТЕМА — это scope, не флагман. Флагман Скаута НЕ гоняет → дешевле.

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
import random
import re
import sys
import time
from pathlib import Path

from core import (analytics, config, cost, creator_bot, creator_tools, dedup, llm, market_tools,
                  runmode, scope_writer, scout_bot, scout_tools, verify)

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
    thinking = llm.resolve_thinking(cfg.get("thinking"))  # 'adaptive' | целое-бюджет | off
    # модель резолвим через runmode: /test (или env MODEL_OVERRIDE) делает прогон дешёвым
    return cfg, runmode.resolve(cfg["model"]), config.agent_api_key(cfg), thinking


def _run_scout() -> None:
    cfg, model, key, thinking = _agent("scout")
    tools = list(scout_tools.TOOLS)
    if cfg.get("web_search"):
        tools.append(scout_bot.WEB_SEARCH_TOOL)
    cost.set_context("scout")
    print("🔍 [1/3] Скаут: разведка трендов...")
    # coverage-зрение Скаута — для ОБЕИХ веток (хорошее универсальное решение: не тащить повтор у
    # истока ни во флагман, ни в scope). Это РАЗВЕДКА, не письмо — тут scope/флагман не разделяем.
    text, _ = _threaded(llm.reply, model, scout_bot._system(), [], scout_bot.COMMANDS["scan"],
                        tools, scout_tools.dispatch, key, thinking)
    print((text or "(пусто)").strip()[:700], "\n")


def _run_creator(command: str = "post", avoid: str = "", hint: str = "", theme: str = "",
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
    if evergreen:  # ВЕЧНАЯ ТЕМА (Модель А): тему ВЫБРАЛ пикер, Криейтор её РАСКРЫВАЕТ (не выбирает из 200).
        guard = ("Пиши образовательный флагман на ВЕЧНУЮ тему (не новость). Тема ВЫБРАНА за тебя из банка:\n"
                 f"  {theme}\n"
                 "Раскрой ИМЕННО ЕЁ (и её угол после тире) — не бери другую, не изобретай свою.\n"
                 "ЗАЯКОРИ на КОНКРЕТИКЕ (актуальность): живая цифра (market_price), реальный пример/кейс, "
                 "историческая параллель — не абстрактное «представьте, что Вы…».\n"
                 "ЦЕЛЬ — пост, которым хочется поделиться с другом: расширяет кругозор, живая человеческая/"
                 "культурная деталь, большие деньги в бытовом сравнении, яркая метрика.\n"
                 "ЗАГОЛОВОК, ГОЛОС и ПОДАЧУ равняй на эталоны в контексте, не своди к морали про DCA. "
                 "Готовый пост, сохрани save_draft.\n\n")
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


def _pick_timely_theme() -> tuple[str, str, dict]:
    """Тема флагмана по АКТУАЛЬНОСТИ. Возвращает (тема, ФАКТОР_РЕШЕНИЯ, вход_измеримо).

    Фактор — что именно решило (свежесть/рынок/бриф/случайно): это и есть «повлияла ли аналитика».
    вход — dict измеримых входов (кандидаты, сколько покрытия учтено, есть ли рынок/бриф) для лог-панели.
    Фолбэк — случайная тема, если рынок/бриф/модель недоступны (тогда фактор='случайно')."""
    pool = dedup.available_bank_themes()
    if len(pool) <= 1:
        return (pool[0] if pool else ""), ("без вариантов" if pool else "банк пуст"), {}
    sample = random.sample(pool, min(25, len(pool)))
    try:
        market = market_tools.handle("market_price", {}) or ""
    except Exception:  # noqa: BLE001
        market = ""
    brief = (verify.latest_brief() or "")[:2500]
    try:
        coverage = analytics.topics_digest(limit=80) or ""
    except Exception:  # noqa: BLE001
        coverage = ""
    meas = {"кандидатов": len(sample),
            "покрытие_учтено": sum(1 for l in coverage.splitlines() if l.strip()),
            "рынок": bool(market), "бриф": bool(brief)}
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(sample))
    system = (
        "Ты выбираешь ОДНУ тему образовательного флагмана крипто-канала о ДОЛГОСРОЧНОМ инвесторе (DCA). "
        "Порядок:\n"
        "1) СВЕЖЕСТЬ (ГЛАВНОЕ, обязательно): СНАЧАЛА выкинь темы, которые канал УЖЕ раскрывал — сверься со "
        "списком опубликованного ниже ПО СУТИ, не по словам. Крахи/FTX/«−50% требует +100%»/«−90% альтов»/"
        "циклы падений канал жевал МНОГО раз — это банально, НЕ бери. Банальный повтор хуже свежей темы.\n"
        "2) НАСТРОЕНИЕ РЫНКА: обвал/страх → психология удержания; ATH/жадность → поздний вход/FOMO; "
        "спокойно/боковик → принятие/применение/AI или словарь.\n"
        "3) БРИФ (бонус): горячий домен из брифа → тема своевременнее.\n"
        "Из оставшихся СВЕЖИХ бери самую резонансную по рынку. Ответ СТРОГО в формате `номер | фактор`, "
        "где фактор — ОДНО слово, что перевесило: свежесть | рынок | бриф. Пример: `7 | свежесть`."
    )
    user = (f"ТЕМЫ:\n{numbered}\n\nЧТО КАНАЛ УЖЕ ПУБЛИКОВАЛ (не повторять ПО СУТИ):\n{coverage}\n\n"
            f"РЫНОК СЕЙЧАС:\n{market or '(нет данных)'}\n\nСВЕЖИЙ БРИФ:\n{brief or '(нет брифа)'}")
    try:
        cost.set_context("theme-pick")
        key = config.agent_api_key(config.load_agent("creator"))
        text, _ = llm.reply(runmode.resolve("claude-sonnet-4-6"), system, [], user, [],
                            lambda _n, _a: "", key, None)
        raw = (text or "").strip()
        nums = re.findall(r"\d+", raw.split("|")[0])  # номер — ДО разделителя (фактор может быть без цифр)
        factor = next((f for f in ("свежесть", "рынок", "бриф") if f in raw.lower()), "актуальность")
        if nums and 0 <= int(nums[0]) - 1 < len(sample):
            return sample[int(nums[0]) - 1], factor, meas
    except Exception:  # noqa: BLE001
        logging.exception("Актуальный выбор темы упал — беру случайную из выборки")
    return random.choice(sample), "случайно", meas


def run_cycle(scope: bool = False, skip_scout: bool = False, draft_only: bool = False,
              evergreen: bool = False, no_image: bool = False, emit=print) -> str:
    """Полный прогон цепи (свежесть→Скаут→анти-повтор→Криейтор/scope→2FA→отложка). ВОЗВРАЩАЕТ отчёт.

    emit — куда слать прогресс по ходу: по умолчанию print (терминал); бот передаёт свой коллектор,
    чтобы вернуть отчёт в чат. Вынесено из main(), чтобы тот же цикл дёргать и из бота (там — ленивый
    импорт run_pipeline во избежание циклического импорта: run_pipeline сам импортирует creator_bot).
    """
    report: list[str] = []
    panel: dict = {}  # измеримые итоги стадий → компактная панель «вход→решение→почему» в конце

    def out(s: str = "") -> None:
        emit(s)
        report.append(s)

    def _panel_block() -> str:
        """Компактная сводка прогона: только измеримое, что на что повлияло."""
        if not panel:
            return ""
        width = max(len(k) for k in panel)
        rows = [f"  {k.ljust(width)} : {v}" for k, v in panel.items()]
        return "━━━━━━ ИТОГ (вход → решение → почему) ━━━━━━\n" + "\n".join(rows)

    cost.reset()  # начинаем замер стоимости всего прогона (Скаут→Криейтор→отложка)
    if not scope:
        evergreen = True  # МОДЕЛЬ А: флагман ВСЕГДА из банка (новость как ТЕМА = scope) — из любого вызова
    kind = ("🔭 Под прицелом (короткий)" if scope
            else "флагман (вечная тема из банка)" if evergreen
            else "флагман (свежая тема)")
    out(f"=== Контент-завод: прогон [{kind}] ===\n")
    _mode = runmode.get()
    panel["формат"] = kind
    panel["режим"] = "🧪 тест (дёшево)" if _mode["mode"] == "test" else "боевой"
    if _mode["mode"] == "test":
        out(f"🧪 ТЕСТ-режим: все модели → {_mode['model']} (дёшево, НЕ для прода). /main в боте — боевой.\n")
        no_image = True     # в тесте GPT-обложку НЕ дёргаем (её качество не тестим — экономим)
        draft_only = True   # тест НЕ публикует и НЕ метит тему [вышло] (иначе дешёвый пост уходит в канал)
    if no_image and not scope:
        out("🖼 GPT-обложку не делаю (тест/--no-image) — только текст.\n")
    # АКТУАЛЬНОСТЬ ДАННЫХ: выгрузка канала устарела → тянем свежие посты ДО разведки и анти-повтора
    # (иначе сверка «было/не было» врёт на самых недавних постах — там и прячется самый частый дубль).
    out("🗂 [0] Актуальность данных канала (для анти-повтора)...")
    _refresh = str(dedup.refresh_if_stale())
    out(_refresh + "\n")
    panel["данные канала"] = _refresh.splitlines()[0][:70] if _refresh.strip() else "актуальны"
    age = _latest_brief_age_hours()
    scout_day = datetime.date.today().weekday() in SCOUT_DAYS
    if skip_scout or evergreen:
        panel["Скаут"] = "пропущен — вечная тема из банка" if evergreen else "пропущен (--skip-scout)"
        out("⏭ Скаута пропускаю — вечная тема из банка, разведка не нужна.\n"
            if evergreen else
            "⏭ Скаута пропускаю (--skip-scout): Криейтор возьмёт последний бриф.\n")
    elif age is not None and age < SCOUT_FRESH_HOURS:
        panel["Скаут"] = f"пропущен — бриф свежий ({age:.1f}ч)"
        out(f"⏭ Скаута пропускаю: последний бриф свежий ({age:.1f}ч < {SCOUT_FRESH_HOURS}ч) — "
            f"повторная разведка не нужна, берём его.\n")
    elif age is not None and not scout_day:
        panel["Скаут"] = f"пропущен — не день разведки, бриф {age:.1f}ч"
        out(f"⏭ Скаута пропускаю: сегодня не день разведки (глубокий поиск Пн/Вт/Чт) — беру последний "
            f"бриф из банка ({age:.1f}ч). Мы не новостник: мануал Скаута + актуальность важнее горячки.\n")
    else:
        panel["Скаут"] = "разведка запущена (брифа нет)" if age is None else "разведка запущена (день поиска)"
        if age is None:
            out("🔄 Брифа в банке нет — запускаю разведку (даже вне дня поиска: писать не из чего).\n")
        else:
            out(f"🔄 Последний бриф старше {SCOUT_FRESH_HOURS}ч ({age:.1f}ч), сегодня день разведки — "
                f"запускаю свежую.\n")
        try:
            _run_scout()
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
                panel["🔁 анти-повтор"] = "СТОП — все направления брифа уже выходили"
                out("⛔ Все направления брифа — повторы уже вышедших постов. Пост НЕ делаю — дубль в "
                    "канал не уйдёт. Нужна свежая разведка (/scan у Скаута) или новый угол.")
                out(_panel_block())
                return "\n".join(report)
            avoid = dedup.repeat_themes(verdict)
            panel["🔁 анти-повтор"] = f"повтор тем: {avoid}" if avoid else "повторов нет — тема свежая"
        except Exception:
            logging.exception("Анти-повтор не сработал — не блокирую, тему дальше берём из брифа сами")
    # ФЛАГМАН (Модель А): ОДНА тема из банка по РОТАЦИИ — пикер выбирает в пайплайне (не отдаём 200 тем
    # в промпт), пропуская вышедшие <полугода назад. Помечаем [вышло ДАТА] ТОЛЬКО при реальной публикации.
    theme = theme_why = ""
    if not scope:
        theme, theme_why, meas = _pick_timely_theme()
        if not theme:
            out("⚠️ Банк тем пуст — флагману не из чего писать. Пополни memory/flagship_topics.md.\n")
            return "\n".join(report)
        panel["🧭 тема"] = f"«{theme}»  ← {theme_why}"
        out("🧭 [Тема] вход → решение:")
        out(f"   ├ кандидатов из банка ..... {meas.get('кандидатов', '—')}")
        out(f"   ├ покрытие канала учтено .. {meas.get('покрытие_учтено', '—')} постов (свежесть)")
        out(f"   ├ рынок ................... {'✓ учтён' if meas.get('рынок') else '— нет данных'}")
        out(f"   ├ бриф Скаута ............. {'✓ учтён' if meas.get('бриф') else '— нет'}")
        out(f"   └→ РЕШЕНИЕ: «{theme}»   ПОЧЕМУ: {theme_why}\n")
    pre_mtime = _latest_draft_mtime()  # снимок ДО генерации: публикуем только если появится НОВЕЕ
    try:
        # scope — ОТДЕЛЬНАЯ ветка (свой лёгкий контекст/модель + встроенный 2FA), флагман — Криейтор.
        post = _run_scope(avoid) if scope else _run_creator("post", avoid, hint, theme,
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
            panel["публикация"] = f"⛔ СТОП — paused-домен «{_hit}»"
            out(f"⛔ scope написал затёртый/paused-домен («{_hit}») — НЕ публикую. Повод обдрочен, лучше "
                "молчать, чем гнать фастфуд. Список пауз правится в core/dedup.py (PAUSED_DOMAINS).")
            out(_panel_block())
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
                panel["🔎 фактчек 2FA"] = "были замечания → Криейтор исправил"
                out("🛠 Есть замечания — Криейтор исправляет САМ (без твоей проверки)...")
                post = _run_creator_fix(post, verdict)
                out((post or "").strip()[:600] + "\n")
                out("🔎 Повторный фактчек после правок:")
                out(str(verify.verify_post(post, verify.latest_brief(), api_key=ckey)) + "\n")
            else:
                panel["🔎 фактчек 2FA"] = "чисто — замечаний нет"
        except Exception:
            logging.exception("Фактчек 2FA не удался — пост НЕ блокирую, ставлю как есть")
    out("📝 --- ГОТОВЫЙ ПОСТ ---")
    out((post or "").strip())
    # ГЕЙТ «свежий пост»: публикуем ТОЛЬКО если в этом прогоне сохранён НОВЫЙ драфт. scope/Криейтор мог
    # ОТКАЗАТЬСЯ писать (нет свежего повода — штатно) и не вызвать save_draft — тогда самый свежий драфт
    # на диске СТАРЫЙ (из архива), и publish_now поставил бы в канал его (был баг: старый флагман ушёл под
    # меткой «короткий»). Нет нового драфта → НИЧЕГО не публикуем и обложку не трогаем.
    if _latest_draft_mtime() <= pre_mtime:
        panel["публикация"] = "⛔ свежий пост не создан (нет повода) — ничего не ставлю"
        out("\n⛔ Свежего поста в этом прогоне НЕ создано (scope/Криейтор не сохранил драфт — вероятно, "
            "нет подходящего повода). В отложку НИЧЕГО не ставлю — старый драфт из архива в канал не уйдёт.")
        out(_panel_block())
        out("\n" + cost.summary())
        return "\n".join(report)
    if draft_only:  # тест-режим: драфт готов и напечатан — обложку GPT НЕ генерим и в отложку НЕ ставим
        panel["публикация"] = "🧪 draft-only — не публикую (смотрим тему/текст)"
        out("\n🧪 draft-only: драфт выше. Обложку GPT НЕ генерирую и в отложку НЕ ставлю (смотрим тему/текст).")
        out(_panel_block())
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
            panel["🖼 обложка"] = "GPT-обложка" if cover_path else "нет — уйдёт текстом"
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
            panel["🖼 обложка"] = "нет подходящей картинки"
            panel["публикация"] = "⛔ СТОП — без картинки не публикуем"
            out("\n⛔ У 🔭-поста НЕТ подходящей картинки — по правилу «без картинки не публикуем» в отложку "
                "НЕ ставлю. Драфт сохранён в архиве (добавь картинку вручную или пропусти повод).")
            out(_panel_block())
            out("\n" + cost.summary())
            return "\n".join(report)
        panel["🖼 обложка"] = "первоисточник (og:image)"
        out(f"🖼 Обложка выбрана (по смыслу подходит посту): {cover_path}")
    out("\n🗓 [3/3] Ставлю в отложенные канала...")
    out(str(_threaded(creator_tools.dispatch, "publish_now",
                      {"kind": "short" if scope else "", "cover": cover_path})))
    panel["публикация"] = "✅ в отложке канала (проверь и одобри)"
    # РЕЦИКЛИНГ: тема флагмана ушла в канал → метим [вышло ДАТА], пикер не даст её ~полгода, потом вернёт.
    # Только на РЕАЛЬНОЙ публикации (draft-only сюда не доходит — вышел выше), чтобы тест не «съедал» темы.
    if theme and not scope:
        if dedup.mark_theme_used(theme):
            out(f"🧭 Тема помечена [вышло] в банке — вернётся в ротацию через ~{dedup.BANK_REUSE_DAYS//30} мес.")
    out("\n=== Готово. Проверь пост в нативных «Отложенных» канала. ===")
    out(_panel_block())
    out("\n" + cost.summary())  # реальная цена прогона Скаут→пост в $
    return "\n".join(report)


def main() -> None:
    # МОДЕЛЬ А: флагман ВСЕГДА берёт тему из банка (польза) + якорит свежим (актуальность) — новость
    # как ТЕМА это scope, не флагман. Значит любой флагман-прогон = evergreen (Скаута не гоняем → дешевле).
    scope = "--scope" in sys.argv
    run_cycle(scope=scope, skip_scout="--skip-scout" in sys.argv,
              draft_only="--draft-only" in sys.argv, evergreen=not scope,
              no_image="--no-image" in sys.argv)


if __name__ == "__main__":
    main()
