"""Полная цепочка контент-завода ОДНИМ запуском (оркестратор v0 — ручной триггер):

    python run_pipeline.py                # ФЛАГМАН: тема из банка (польза) + свежий якорь (актуальность) → отложка
    python run_pipeline.py --scope        # 🔭 «Под прицелом» — НОВОСТНОЙ короткий (Скаут+свежесть, обложка из первоисточника)
    python run_pipeline.py --draft-only   # драфт без публикации (тест/итерация)
    python run_pipeline.py --no-image     # БЕЗ GPT-обложки (только текст). В /test-режиме включается САМ.
    python run_pipeline.py --scope --force-scout  # ПОЛНАЯ разведка принудительно (игнор гейта свежести 3ч и дня разведки) — обкатка/валидация

МОДЕЛЬ А: флагман = ПОЛЬЗА (тема ВСЕГДА из банка, бренд-ядро) + АКТУАЛЬНОСТЬ (Криейтор якорит свежей
цифрой/примером). Новость как ТЕМА — это scope, не флагман. Флагман Скаута НЕ гоняет → дешевле.

Скаут НЕ дёргается впустую: если последний бриф разведки младше SCOUT_FRESH_HOURS (3ч) — прогон берёт
его, повторный поиск пропускается (--skip-scout форсит пропуск всегда; свежесть и так бережёт кредиты).

В день публикации прогоняет цепь без твоего участия в передаче:
  0) Актуальность данных — если выгрузка канала устарела (>12ч), тянет свежие посты (collect +
     enrich_topics), чтобы анти-повтор сверялся с тем, что РЕАЛЬНО уже опубликовано (core/dedup);
  1) Скаут — разведка → бриф (топ-темы) в memory/briefs/ [можно пропустить --skip-scout];
  1.5) Анти-повтор + гейт темы (scope) — сверяет направления брифа с историей канала (STEER, не вето:
     22.07 пост обязан быть) → гейт темы (topic_gate) ВСЕГДА выбирает ЛУЧШИЙ повод по свежести+пользе ДО
     генерации, ведёт writer на него (не блуждает к слабому/протухшему); дубль/слабость ловит владелец в отложке;
  2) Криейтор — утверждённая НЕ-повторная тема: пост + обложка (make_image), сохраняет драфт;
  3) Постановка — нативная ОТЛОЖКА в канал на слот контент-плана + уведомление на @Kanaki_K;
     вышедший флагман пишется в журнал (flagship_journal) — вход мини-флагмана Threads.
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

from core import (analytics, config, cost, creator_bot, creator_tools, dedup, flagship_journal, llm,
                  logging_setup, market_tools, runmode, scope_writer, scout_bot, scout_tools,
                  self_learn, topic_category, topic_gate, usefulness, verify)

logging_setup.setup()  # N-2: единая идемпотентная настройка логов

SCOUT_FRESH_HOURS = 3  # бриф свежее этого — повторную разведку не запускаем (бережём кредиты)
STALE_ALERT_HOURS = 24  # выгрузка канала старше этого ПОСЛЕ попытки тяги = сборщик молча упал (N-16:
# вероятно, единая MTProto-сессия мертва) → громкий алерт владельцу, а не тихо на устаревших данных
# Дни ГЛУБОКОЙ разведки: Пн=0, Вт=1, Чт=3. В остальные дни берём последний бриф из «банка» — мы НЕ
# новостник (горячка не цель), мануал Скаута + актуальность важнее свежей разведки на каждый пост.
# Скаут с ~6×/нед → 3×/нед. Если брифа в банке вообще нет — разведка запустится в любой день.
SCOUT_DAYS = {0, 1, 3}
# scope НОВОСТНОЙ: бриф старше этого → понедельничные поводы протухли (событие уже может быть >3 дней), а
# короткому нужна свежесть (вчера-сегодня). Для --scope зовём Скаута ДАЖЕ не в его день, если бриф просрочен
# (баг 22.07: в среду брали понедельничный бриф → писали Сейлора, событие 13.07 = 9 дней). Флагману не важно.
SCOPE_STALE_BRIEF_HOURS = 24


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


def _recent_scope_titles(hours: float = 48.0) -> list[str]:
    """Заголовки постов, СГЕНЕРированных за последние `hours` (черновики на диске) — чтобы гейт темы НЕ
    выбрал ту же тему повторно. Баг 22.07: дедуп сверяет с ОПУБЛИКОВАННЫМ каналом (channel_posts.json), а
    свежие драфты/отложка прошлых прогонов ему НЕВИДИМЫ → 3 прогона на одном брифе дали Gram-кошелёк 3× в
    отложку. Читаем первую значимую строку (заголовок) свежих драфтов — гейт исключает эти темы."""
    d = creator_tools.DRAFTS_DIR
    if not d.exists():
        return []
    cutoff = time.time() - hours * 3600
    out: list[str] = []
    for p in sorted(d.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.stat().st_mtime < cutoff:
            break
        try:
            for ln in p.read_text(encoding="utf-8").splitlines():
                s = ln.strip().lstrip("*# ").rstrip("*").strip()
                if s and "[[" not in s:          # первая значимая строка = заголовок (не мета [[...]])
                    out.append(s[:120])
                    break
        except Exception:
            continue
    return out[:8]


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
    scout_tools.reset_degraded()  # чистим след деградации прошлого прогона (аудит 20.07)
    print("🔍 [1/3] Скаут: разведка трендов...")
    # coverage-зрение Скаута — для ОБЕИХ веток (хорошее универсальное решение: не тащить повтор у
    # истока ни во флагман, ни в scope). Это РАЗВЕДКА, не письмо — тут scope/флагман не разделяем.
    text, _ = _threaded(llm.reply, model, scout_bot._system(), [], scout_bot.COMMANDS["scan"],
                        tools, scout_tools.dispatch, key, thinking)
    print((text or "(пусто)").strip()[:700], "\n")
    # Структурный детект деградации (аудит 20.07): баннер «источник недоступен» полагался на то, что
    # LLM донесёт его до чата — в headless это могло тихо потеряться. Логируем WARNING независимо.
    down = scout_tools.degraded_sources()
    if down:
        logging.warning("🛑 Скаут: источник(и) вернули ТОЛЬКО ошибки: %s — возможна деградация разведки "
                        "(протухла сессия/куки); бриф мог выйти без части сигнала. Это НЕ «тихий день».",
                        ", ".join(down))


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


def _run_scope(avoid: str = "", recommend: str = "", weak: str = "") -> str:
    """🔭 «Под прицелом» — ОТДЕЛЬНАЯ ветка (core/scope_writer): свой лёгкий контекст + модель + 2FA
    внутри. Обложку НЕ рисует (не GPT), но ТЯНЕТ картинку из ПЕРВОИСТОЧНИКА повода (og:image + vision-
    гейт) — путь кладёт в SCOPE_COVER; нет годной → уйдёт текстом. Флагман-аутбокс к scope не относится.
    recommend — повод, отобранный гейтом темы (steer); weak — чем он слабоват (для заострения)."""
    try:  # флагман-аутбокс GPT-обложки чистим — scope им не пользуется (у него свой SCOPE_COVER)
        if creator_tools.MEDIA_OUTBOX.exists():
            creator_tools.MEDIA_OUTBOX.unlink()
    except Exception:
        pass
    cost.set_context("scope")
    print("✍️ [2/3] 🔭 Под прицелом: короткий аналитический (отдельная ветка, обложка из первоисточника)...")
    text = _threaded(scope_writer.write, "", avoid, recommend, weak, False)  # verify_facts=False: факты в ре-гейте
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
    # Само-обучение: наклон ротации к категориям, что заходят на КАНАЛЕ (ТГ-сигнал; Threads НЕ берём —
    # площадки инвертированы). Мягко — веса влияют лишь на попадание в 25 кандидатов, финал за
    # свежестью/рынком/LLM. Нет данных → веса пустые → weighted_sample = обычная равномерная выборка.
    cat_w = self_learn.tg_category_weights()
    sample = self_learn.weighted_sample(pool, min(25, len(pool)),
                                        lambda t: cat_w.get(topic_category.category_of(t), 1.0))
    # Аудит 20.07: при пуле ≤25 weighted_sample отдаёт ВСЕ темы → наклон обучения НЕ влияет (тихий no-op).
    # Пока пул ~134 (норма), но банк усыхает метками [вышло] — делаем вырождение видимым, а не тихим.
    if cat_w and len(pool) <= 25:
        logging.warning("Само-обучение: пул тем ≤25 (%d) — наклон категорий НЕ влияет на выбор (все "
                        "кандидаты проходят). Пополни банк тем или проверь метки [вышло].", len(pool))
    try:
        market = market_tools.handle("market_price", {}) or ""
    except Exception:  # noqa: BLE001
        market = ""
    brief = (verify.latest_brief() or "")[:2500]
    try:
        coverage = analytics.topics_digest(limit=80) or ""
    except Exception:  # noqa: BLE001
        coverage = ""
    ranked = sorted(cat_w.items(), key=lambda kv: -kv[1])
    tilt = (f"{topic_category.label(ranked[0][0])} ×{ranked[0][1]} … "
            f"{topic_category.label(ranked[-1][0])} ×{ranked[-1][1]}") if ranked else "нет данных (равномерно)"
    meas = {"кандидатов": len(sample),
            "покрытие_учтено": sum(1 for l in coverage.splitlines() if l.strip()),
            "рынок": bool(market), "бриф": bool(brief), "наклон": tilt}
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
              evergreen: bool = False, no_image: bool = False, force_scout: bool = False,
              emit=print) -> str:
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
    # N-16 HEALTH-CHECK: если ПОСЛЕ попытки тяги выгрузка всё ещё протухла — сборщик молча упал (частая
    # причина: единая MTProto-сессия истекла/забанена, она же на выгрузку+разведку+публикацию). НЕ молчим:
    # громкий лог + строка в отчёт всегда; уведомление владельцу — через Bot API (N-45): раньше шло через
    # ту же MTProto-сессию, т.е. при её смерти (вероятная причина алерта) не доходило. Bot API от неё независим.
    _age = dedup.data_age_hours()
    if _age is None or _age >= STALE_ALERT_HOURS:
        _alert = (f"Данные канала НЕ обновляются ({'выгрузки нет' if _age is None else f'{_age:.0f}ч'} "
                  f"≥ {STALE_ALERT_HOURS:.0f}ч). Вероятно, MTProto-сессия истекла/забанена — проверь "
                  f"data/evgeniyp.session (см. docs/OPERATIONS.md). Завод работает на УСТАРЕВШИХ данных.")
        logging.critical("[health] %s", _alert)
        out("🚨 " + _alert + "\n")
        panel["данные канала"] = "🚨 НЕ обновляются — проверь MTProto-сессию"
        try:
            from core import bot_alert
            if not bot_alert.notify_owner("🚨 KANAKI-завод: " + _alert):
                logging.warning("[health] алерт владельцу не доставлен (проверь токен бота/OWNER_ID)")
        except Exception:
            logging.exception("[health] уведомление владельцу не отправилось")
    age = _latest_brief_age_hours()
    scout_day = datetime.date.today().weekday() in SCOUT_DAYS
    scout_ran = False  # бегал ли Скаут в этом прогоне — чтобы при исчерпании брифа не гонять его дважды
    if skip_scout or evergreen:
        panel["Скаут"] = "пропущен — вечная тема из банка" if evergreen else "пропущен (--skip-scout)"
        out("⏭ Скаута пропускаю — вечная тема из банка, разведка не нужна.\n"
            if evergreen else
            "⏭ Скаута пропускаю (--skip-scout): Криейтор возьмёт последний бриф.\n")
    elif not force_scout and age is not None and age < SCOUT_FRESH_HOURS:
        panel["Скаут"] = f"пропущен — бриф свежий ({age:.1f}ч)"
        out(f"⏭ Скаута пропускаю: последний бриф свежий ({age:.1f}ч < {SCOUT_FRESH_HOURS}ч) — "
            f"повторная разведка не нужна, берём его.\n")
    elif (not force_scout and age is not None and not scout_day
          and not (scope and age >= SCOPE_STALE_BRIEF_HOURS)):
        panel["Скаут"] = f"пропущен — не день разведки, бриф {age:.1f}ч"
        out(f"⏭ Скаута пропускаю: сегодня не день разведки (глубокий поиск Пн/Вт/Чт) — беру последний "
            f"бриф из банка ({age:.1f}ч). Мы не новостник: мануал Скаута + актуальность важнее горячки.\n")
    else:
        forced = force_scout and age is not None and (age < SCOUT_FRESH_HOURS or not scout_day)
        scope_stale = (scope and not force_scout and not scout_day and age is not None
                       and age >= SCOPE_STALE_BRIEF_HOURS)
        panel["Скаут"] = ("разведка ФОРСИРОВАНА (--force-scout)" if forced
                          else "разведка запущена (scope: бриф просрочен)" if scope_stale
                          else "разведка запущена (брифа нет)" if age is None
                          else "разведка запущена (день поиска)")
        if forced:
            out(f"🔄 --force-scout: запускаю ПОЛНУЮ разведку принудительно — игнорирую гейт свежести "
                f"(бриф {age:.1f}ч) и гейт «дня разведки». Обкатка источников/watermark/воронки.\n")
        elif scope_stale:
            out(f"🔄 --scope + бриф просрочен ({age:.1f}ч ≥ {SCOPE_STALE_BRIEF_HOURS}ч): запускаю Скаута "
                f"ДАЖЕ не в его день — короткому нужен свежий повод (событие ≤{topic_gate.FRESH_EVENT_DAYS}д), "
                f"на протухшем брифе получим Сейлора-с-хвостом.\n")
        elif age is None:
            out("🔄 Брифа в банке нет — запускаю разведку (даже вне дня поиска: писать не из чего).\n")
        else:
            out(f"🔄 Последний бриф старше {SCOUT_FRESH_HOURS}ч ({age:.1f}ч), сегодня день разведки — "
                f"запускаю свежую.\n")
        try:
            _run_scout()
            scout_ran = True
        except Exception:
            logging.exception("Скаут упал — продолжаю на последнем имеющемся брифе (если он есть)")
    # АНТИ-ПОВТОР + ГЕЙТ ТЕМЫ — ВЕТКИ РАЗДЕЛЕНЫ (scope и флагман не мешают друг другу):
    #  • SCOPE — дедуп (Sonnet) как STEER, НЕ вето (22.07: пост обязан быть) → гейт темы (topic_gate:
    #    свежесть+польза) ВСЕГДА выбирает лучший повод ДО генерации → пост-сверка/польза после = предупреждения.
    #  • ФЛАГМАН — Криейтор САМ видит покрытие канала (topics_digest в его контексте) и берёт тему из банка;
    #    отдельный дедуп-проход ему не нужен, avoid/hint пустые.
    avoid = hint = scope_rec = scope_weak = ""
    if scope:
        verdict = ""
        gkey = config.agent_api_key(config.load_agent("creator"))
        try:
            cost.set_context("dedup")  # чтобы анти-повтор логировался под своей меткой, не под чужой
            verdict = dedup.check(verify.latest_brief(), api_key=gkey)
            out("🔁 [Анти-повтор] Сверка тем брифа с уже опубликованным (свежая выгрузка):")
            out(str(verdict) + "\n")
            avoid = dedup.repeat_themes(verdict)
            # ПРАВИЛО ВЛАДЕЛЬЦА 22.07: запустил прогон → ПОСТ ОБЯЗАН БЫТЬ. Анти-повтор больше НЕ вето
            # (раньше all_repeats/сбой = СТОП в ноль). Дубль ловит владелец в «Отложенных». Повторы служат
            # STEER'ом (avoid), а гейт темы берёт наименее заезженный повод и велит writer'у новый угол.
            if not dedup.failed(verdict) and dedup.all_repeats(verdict):
                panel["🔁 анти-повтор"] = "все домены звучали — беру наименее заезженный (пост обязан быть)"
                out("⚠️ Все направления брифа — домены уже звучали на канале. НЕ стопаю (пост обязан быть): "
                    "гейт темы возьмёт наименее заезженный, writer даст свежий угол. Проверь в «Отложенных».")
                avoid = ""  # снять запрет-всё (иначе писать не из чего) — дубль поймает владелец глазами
            else:
                panel["🔁 анти-повтор"] = f"повтор тем: {avoid}" if avoid else "повторов нет — тема свежая"
        except Exception:
            # ФЕЙЛ-ОТКРЫТО (22.07): раньше сбой сверки = СТОП. Теперь пост обязан быть — пишем без анти-
            # повтора (writer возьмёт повод из брифа), дубль ловит владелец в «Отложенных».
            logging.exception("Анти-повтор упал — фейл-ОТКРЫТО (пост обязан быть): пишу без сверки")
            panel["🔁 анти-повтор"] = "⚠️ сбой сверки — пишу без анти-повтора (проверь в Отложенных)"
            out("⚠️ Анти-повтор упал — не стопаю (пост обязан быть): пишу, дубль поймаешь в «Отложенных».")
            verdict = ""
        # ГЕЙТ ТЕМЫ (свежесть+польза как РАНГ) — ВСЕГДА выбирает ЛУЧШИЙ повод ДО генерации (дёшево, один
        # Sonnet по готовому разбору). Урок 22.07: суд пользы ПОСЛЕ генерации жёг $1.5, а writer брал
        # слабейший протухший повод (Сейлор-13.07). Теперь свежесть+польза решают ВЫБОР темы, а не рубят.
        tg_verdict = ""
        try:
            _recent = _recent_scope_titles()  # темы прошлых прогонов (отложка/черновики) — не повторять
            if _recent:
                out(f"🧠 Гейту темы: не повторять недавно сделанное — {'; '.join(t[:40] for t in _recent[:4])}")
            scope_rec, scope_weak, tg_verdict = topic_gate.select(verdict, api_key=gkey, recent=_recent)
            if (tg_verdict or "").strip():
                out("🎯 [Гейт темы] лучший повод по свежести (≤3д идеал) + пользе, ДО генерации:")
                out(str(tg_verdict) + "\n")
        except Exception:
            logging.exception("Гейт темы упал — фолбэк на recommend дедупа")
        # БРИФ ИСЧЕРПАН (гейт нашёл только 🚫-поток/повтор/уже-сделанное) → НЕ скребём дно и не публикуем
        # слабьё: гоним Скаута за СВЕЖИМИ темами (если ещё не бегал), пере-сверяем, пере-выбираем ОДИН раз.
        # Резолвит противоречие «пост обязан быть» × «не публикуй слабое»: пост будет — но на СВЕЖЕЙ теме,
        # а не на выжатом брифе (баг 22.07: 6 прогонов одного брифа → после Gram скребли Raoul-Pal-повтор).
        try:
            if topic_gate.is_exhausted(tg_verdict) and not scout_ran and not skip_scout:
                out("♻️ Бриф исчерпан (сильные темы уже в отложке/повторы) — гоню Скаута за свежими, не скребу дно...")
                _run_scout()
                scout_ran = True
                verdict = dedup.check(verify.latest_brief(), api_key=gkey)
                out("🔁 [Анти-повтор] Пере-сверка после свежей разведки:\n" + str(verdict) + "\n")
                avoid = "" if dedup.all_repeats(verdict) else dedup.repeat_themes(verdict)
                scope_rec, scope_weak, tg_verdict = topic_gate.select(
                    verdict, api_key=gkey, recent=_recent_scope_titles())
                out("🎯 [Гейт темы] после свежей разведки:\n" + str(tg_verdict) + "\n")
                panel["♻️ исчерпан"] = "бриф был выжат → свежая разведка → новый повод"
        except Exception:
            logging.exception("Пере-разведка при исчерпании брифа упала — пишу лучшее из имеющегося")
        if not scope_rec:  # гейт молчит/сбой → фолбэк на сырой recommend (writer всё равно пишет)
            scope_rec = dedup.recommended_theme(verdict)
        if scope_rec:
            panel["🎯 гейт темы"] = f"повод: {scope_rec[:52]}" + (f"  ⚠{scope_weak[:34]}" if scope_weak else "")
            panel["🧭 рекоменд."] = scope_rec
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
        out(f"   ├ наклон категорий (ТГ) ... {meas.get('наклон', '—')}")
        out(f"   └→ РЕШЕНИЕ: «{theme}»   ПОЧЕМУ: {theme_why}\n")
    pre_mtime = _latest_draft_mtime()  # снимок ДО генерации: публикуем только если появится НОВЕЕ
    try:
        # scope — ОТДЕЛЬНАЯ ветка (свой лёгкий контекст/модель + встроенный 2FA), флагман — Криейтор.
        post = _run_scope(avoid, scope_rec, scope_weak) if scope else _run_creator("post", avoid, hint,
                                                theme, evergreen=evergreen, no_image=no_image)
    except Exception as e:
        out(f"❌ Пост не сделан: {e}\nПостановку в отложку пропускаю — в канал ничего не уйдёт.")
        return "\n".join(report)
    if scope and post:
        # ПОСТ-СВЕРКА (writer-wander): дедуп проверял КАНДИДАТОВ брифа, а писатель мог свернуть на свою
        # тему. Прогоняем ИТОГОВЫЙ пост по окну канала ещё раз. РАНЬШЕ повтор → СТОП; 22.07 (пост обязан
        # быть) → только ПРЕДУПРЕЖДЕНИЕ, дубль ловит владелец в отложке. Сбой сверки — тоже не роняет.
        try:
            pv = dedup.check(post.split("[[SPLIT]]")[0],
                             api_key=config.agent_api_key(config.load_agent("creator")))
            if not dedup.failed(pv) and dedup.all_repeats(pv):
                panel["🔁 пост-сверка"] = "⚠ близко к недавнему посту — проверь в Отложенных"
                out("⚠️ Пост-сверка: итоговый пост близок к недавнему посту канала — НЕ стопаю (пост обязан "
                    "быть), но глянь в «Отложенных», не дубль ли:\n" + str(pv) + "\n")
        except Exception:
            logging.exception("Пост-сверка scope упала — пропускаю её (осн. сверка до генерации уже прошла)")
        # ГЕЙТ ПОЛЬЗА-ЭДЖ — СОВЕТ, не вето (22.07: пост обязан быть). Польза теперь РЕШАЕТ ВЫБОР темы выше
        # (topic_gate: свежесть+польза ранжируют кандидатов ДО генерации) — это и есть «логику пользы сделать
        # существенно лучше». Здесь лишь ПОМЕЧАЕМ слабый пост для глаз владельца в «Отложенных», не рубим в
        # ноль: раньше жёсткий СТОП жёг $1.5 за прогон и оставлял без поста. Фейл-открыто (сбой не глушит).
        try:
            gv = usefulness.judge(post.split("[[SPLIT]]")[0], verify.latest_brief(),
                                  api_key=config.agent_api_key(config.load_agent("creator")))
            if usefulness.blocks(gv):
                panel["🎯 польза"] = "⚠ слабовата — публикую лучшее (проверь в Отложенных)"
                out("⚠️ Гейт польза: повод слабоват (пересказ/жидкий эдж) — но пост ОБЯЗАН быть, публикую "
                    "лучшее из имеющегося. Глянь в «Отложенных» перед одобрением:\n" + str(gv) + "\n")
            else:
                panel["🎯 польза"] = "✓ есть вывод через угол"
        except Exception:
            logging.exception("Гейт польза-эдж упал — пропускаю (не блокирует публикацию)")
        # 2FA-РЕ-ГЕЙТ scope. РАНЬШЕ (до 22.07): остался ⚠️ → СТОП «проверь вручную». Владелец 22.07:
        # «2FA ДОЛЖЕН САМ проверить и поставить верное — я не должен проверять, и пост обязан быть».
        # Поэтому: остался ⚠️/❓ → НЕ стопаем и НЕ зовём владельца, а ПРАВИМ прицельно по ЭТОМУ вердикту
        # (он называет конкретную цифру, в отличие от первого внутри write()) — ставим значение из брифа
        # ИЛИ убираем невериф. цифру (FIX-контракт), и публикуем исправленный драфт. Сбой 2FA — фейл-открыто.
        fkey = config.agent_api_key(config.load_agent("creator"))
        try:
            # АВТОРИТЕТНАЯ ВЕБ-СВЕРКА (web=True, баг 22.07): герой-цифры сверяем с РЕАЛЬНОСТЬЮ (Тир-1), а не
            # с брифом — Скаут тащит Тир-3 X-выдумки («900 часов»/«$957M за 6 дней»), а брифовый 2FA их
            # штамповал ✅ ЧИСТО. Теперь: веб противоречит → правим по ВЕБ-значению → перепроверяем.
            sv = verify.verify_post(verify.latest_draft(), verify.latest_brief(), api_key=fkey,
                                    scope=True, web=True)
            out("🔎 [2FA scope · ВЕБ-сверка с Тир-1] Проверка опубликуемого драфта:\n" + str(sv) + "\n")
            if verify.has_issues(sv):
                out("🛠 2FA: цифры расходятся с реальными источниками — правлю по ВЕБ-проверенным значениям "
                    "(бриф мог врать):")
                post = _threaded(scope_writer.fix_facts, sv, fkey) or post
                sv2 = verify.verify_post(verify.latest_draft(), verify.latest_brief(), api_key=fkey,
                                         scope=True, web=True)
                if verify.has_issues(sv2):
                    # НЕ стопаем на ОСТАТОЧНОМ ⚠️ (урок 22.07: стоп на педантичном нюансе «The Open Platform
                    # ≠ TON Foundation» = $1.3 и ноль). Фикс УЖЕ привёл герой-цифры к веб-значениям (было
                    # 6✅→стало 8✅); остаток — обычно нюанс/формулировка, а не выдумка. Публикуем исправленный,
                    # остаток идёт ПОМЕТКОЙ владельцу в отложку (он глянет). Ложь-в-посылке ловит уже сам фикс
                    # (убирает невериф. цифру); полностью пустой стоп хуже, чем исправленный пост с одним ⚠️.
                    panel["🔎 2FA scope"] = "герой-цифры сверены с вебом; остался мелкий ⚠️ — глянь в Отложенных"
                    out("⚠️ 2FA веб-сверка: основное приведено к РЕАЛЬНЫМ данным (веб), остался остаточный ⚠️ "
                        "(обычно нюанс/формулировка) — публикую исправленный, глянь в «Отложенных»:\n"
                        + str(sv2) + "\n")
                else:
                    panel["🔎 2FA scope"] = "цифры сверены с вебом (Тир-1), расхождения исправлены"
                    out("✅ Цифры приведены к реально подтверждённым (веб):")
                out((post or "").split("[[SPLIT]]")[0].strip()[:600] + "\n")
            else:
                panel["🔎 2FA scope"] = "✓ цифры сверены с реальными источниками (веб)"
        except Exception:
            logging.exception("2FA веб-сверка scope упала — пропускаю (сбой не блокирует публикацию)")
        # ✂️ РЕДАКТУРА (scope_writer.polish) — автоматизирует РУЧНУЮ правку владельца (цель 22.07: ноль
        # редактуры). Отдельный проход глазами редактора по scope_lessons: счёт пунктов, сарказм-огрызки,
        # двойное тире, имя токена — ровно то, что владелец правил в браузере. Sonnet-черновик один мах это
        # не дожимает (как и раньше — потому владелец и правил); отдельная редактура дожимает. Факты не трогает.
        try:
            out("✂️ [Редактура] Полирую стиль/композицию глазами редактора (счёт пунктов, огрызки, тире, имя)...")
            post = _threaded(scope_writer.polish, fkey) or post
            out((post or "").split("[[SPLIT]]")[0].strip()[:600] + "\n")
        except Exception:
            logging.exception("Редактурный проход scope упал — публикую как есть")
    # 2FA флагмана (Sonnet): нашёл замечания → Криейтор САМ исправляет → перепроверка. У scope свой
    # 2FA уже прошёл внутри его ветки — здесь его НЕ дублируем.
    # web=True (задача 23.07, симметрия со scope): у вечной темы БРИФА ПОД НЕЁ НЕТ (бриф на диске — от
    # прошлого scope-прогона, про другое). Сверять флагман с ним = сверять с пустотой → 2FA флудил ❓
    # «нет в брифе» и стопал пост на своём шуме, а правка без якоря ломала арифметику. Теперь герой-цифры
    # сверяются с РЕАЛЬНОСТЬЮ (веб/Тир-1), как решено для scope 22.07 (verify.FLAGSHIP_SOURCE_CHECK).
    if post and not scope:
        ckey = config.agent_api_key(config.load_agent("creator"))
        out("🔎 [Фактчек 2FA · ВЕБ-сверка с реальностью] Независимая проверка цифр/фактов (Sonnet)...")
        try:
            # brief="" осознанно: у вечной темы брифа под неё НЕТ; чужой scope-бриф не только не источник
            # истины, но и вреден — 2FA может ложно кросс-сослаться на число из его СОСЕДНЕГО раздела
            # (класс бага 15.07 «2030 из другого раздела»). Источник истины флагмана — только веб.
            verdict = verify.verify_post(post, "", api_key=ckey, web=True)
            out(str(verdict) + "\n")
            if verify.has_issues(verdict):
                panel["🔎 фактчек 2FA"] = "были замечания → Криейтор исправил по вебу"
                out("🛠 Есть замечания — Криейтор исправляет САМ по веб-проверенным значениям...")
                post = _run_creator_fix(post, verdict)
                out((post or "").strip()[:600] + "\n")
                out("🔎 Повторный фактчек после правок:")
                # Аудит флагмана 20.07: верифицируем ТО, ЧТО РЕАЛЬНО ПУБЛИКУЕТСЯ — драфт с диска
                # (latest_draft), а не строку `post` в памяти. Иначе, если фикс-модель поправила текст,
                # но забыла save_draft, гейт прошёл бы на исправленной строке, а в канал ушёл бы старый
                # драфт с той самой ⚠️-цифрой. Верна и та, и другая ветка: не сохранил → старый драфт с
                # ⚠️ → флаг (безопасно); сохранил → чистый драфт == post → проходит.
                reverdict = verify.verify_post(verify.latest_draft(), "", api_key=ckey, web=True)
                out(str(reverdict) + "\n")
                # ПРАВИЛО 22.07 «пост ОБЯЗАН быть» (scope-post-must-exist), симметрия со scope-ре-гейтом:
                # герой-цифры уже приведены к РЕАЛЬНЫМ значениям (веб), остаток обычно нюанс/формулировка,
                # а не выдумка. Не стопаем — публикуем ИСПРАВЛЕННЫЙ драфт + флаг в «Отложенные» (твои глаза
                # = финальный гейт). Фабрикацию веб-правка уже сняла; полностью пустой стоп хуже, чем
                # исправленный пост с одним остаточным ⚠️ под ручную вычитку.
                if verify.has_issues(reverdict):
                    panel["🔎 фактчек 2FA"] = "цифры сверены с вебом; остался мелкий ⚠️ — глянь в Отложенных"
                    out("⚠️ 2FA: основное приведено к РЕАЛЬНЫМ данным (веб), остался остаточный ⚠️ "
                        "(обычно нюанс/формулировка) — публикую исправленный, глянь в «Отложенных».")
                else:
                    panel["🔎 фактчек 2FA"] = "были замечания → исправлено по вебу, перепроверка чистая"
            else:
                panel["🔎 фактчек 2FA"] = "чисто — цифры сверены с реальностью (веб)"
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
        # Картинка 🔭: 1) og:image первоисточника (vision выбрал) → SCOPE_COVER; 2) НЕТ og:image → ГЕНЕРИМ
        # GPT-обложку из поста (как флагман) — на любой пост картинку можно СДЕЛАТЬ (владелец 22.07: «текстом»
        # это отмазка); 3) и GPT упал → текст (редко). Раньше: нет og:image → СТОП/текст = дыра (ETF-повод без
        # og:image давал ноль). Картинка почти всегда есть.
        try:
            sc = creator_tools.SCOPE_COVER
            cp = sc.read_text(encoding="utf-8").strip() if sc.exists() else ""
            cover_path = cp if cp and Path(cp).exists() else ""
        except Exception:
            logging.exception("scope-обложка: не смог подхватить SCOPE_COVER")
            cover_path = ""
        if cover_path:
            panel["🖼 обложка"] = "первоисточник (og:image)"
            out(f"🖼 Обложка выбрана (по смыслу подходит посту): {cover_path}")
        else:
            out("🖼 og:image первоисточника не нашёлся — генерирую GPT-обложку из поста (картинка обязательна)...")
            try:
                ob = creator_tools.MEDIA_OUTBOX
                if ob.exists():
                    ob.unlink()
                body = post.split("[[SPLIT]]")[0]
                title = next((l.strip() for l in body.splitlines() if l.strip()), "").replace("**", "")
                out(str(_threaded(creator_tools.dispatch, "make_image", {"title": title, "post_text": body})))
                have = [l.strip() for l in ob.read_text(encoding="utf-8").splitlines() if l.strip()] \
                    if ob.exists() else []
                cover_path = have[-1] if have else ""
            except Exception:
                logging.exception("scope GPT-обложка не удалась — уйдём текстом")
                cover_path = ""
            if cover_path:
                panel["🖼 обложка"] = "GPT-обложка (og:image не нашёлся)"
                out(f"🖼 GPT-обложка сгенерирована: {cover_path}")
            else:
                panel["🖼 обложка"] = "нет — текстом (og:image и GPT не дали, редко)"
                out("⚠️ Ни og:image, ни GPT-обложка не вышли — ставлю текстом (редкий случай).")
    out("\n🗓 [3/3] Ставлю в отложенные канала...")
    out(str(_threaded(creator_tools.dispatch, "publish_now",
                      {"kind": "short" if scope else "", "cover": cover_path})))
    panel["публикация"] = "✅ в отложке канала (проверь и одобри)"
    # РЕЦИКЛИНГ: тема флагмана ушла в канал → метим [вышло ДАТА], пикер не даст её ~полгода, потом вернёт.
    # Только на РЕАЛЬНОЙ публикации (draft-only сюда не доходит — вышел выше), чтобы тест не «съедал» темы.
    if theme and not scope:
        # МОСТ В THREADS: вышедший флагман (полный текст + тема) → журнал вышедших. Отсюда мини-флагман
        # (run_threads_pipeline) берёт его и дистиллирует в Threads-серию. Только боевая публикация —
        # draft-only/тест сюда не доходят (вышли выше), журнал тестами не засоряется.
        flagship_journal.record(post, theme)
        out("🧵 Флагман записан в журнал вышедших — доступен мини-флагману Threads (run_threads_pipeline).")
        if dedup.mark_theme_used(theme):
            out(f"🧭 Тема помечена [вышло] в банке — вернётся в ротацию через ~{dedup.BANK_REUSE_DAYS//30} мес.")
    out("\n=== Готово. Проверь пост в нативных «Отложенных» канала. ===")
    out(_panel_block())
    out("\n" + cost.summary())  # реальная цена прогона Скаут→пост в $
    return "\n".join(report)


def main() -> None:
    logging_setup.set_agent("pipeline")   # P2-15: логи прогона помечены; new_request даёт id этого запуска
    logging_setup.new_request()
    # МОДЕЛЬ А: флагман ВСЕГДА берёт тему из банка (польза) + якорит свежим (актуальность) — новость
    # как ТЕМА это scope, не флагман. Значит любой флагман-прогон = evergreen (Скаута не гоняем → дешевле).
    scope = "--scope" in sys.argv
    run_cycle(scope=scope, skip_scout="--skip-scout" in sys.argv,
              draft_only="--draft-only" in sys.argv, evergreen=not scope,
              no_image="--no-image" in sys.argv,
              force_scout="--force-scout" in sys.argv)


if __name__ == "__main__":
    main()
