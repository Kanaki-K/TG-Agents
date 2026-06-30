"""Полная цепочка контент-завода ОДНИМ запуском (оркестратор v0 — ручной триггер):

    python run_pipeline.py                # полный прогон: Скаут → Криейтор (флагман) → отложка
    python run_pipeline.py --scope        # короткий 🔭 «Под прицелом» (аналитич., БЕЗ обложки) → отложка
    python run_pipeline.py --skip-scout   # БЕЗ Скаута: Криейтор берёт ПОСЛЕДНИЙ бриф

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


def _threaded(fn, *args):
    """Выполнить в отдельном потоке (как asyncio.to_thread в боте) — нужно для playwright на Windows."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(fn, *args).result()


def _agent(name: str):
    cfg = config.load_agent(name)
    thinking = {"type": "adaptive"} if cfg.get("thinking") == "adaptive" else None
    # модель резолвим через runmode: /test (или env MODEL_OVERRIDE) делает прогон дешёвым
    return cfg, runmode.resolve(cfg["model"]), config.agent_api_key(cfg), thinking


def _run_scout() -> None:
    cfg, model, key, thinking = _agent("scout")
    tools = list(scout_tools.TOOLS)
    if cfg.get("web_search"):
        tools.append(scout_bot.WEB_SEARCH_TOOL)
    cost.set_context("scout")
    print("🔍 [1/3] Скаут: разведка трендов...")
    text, _ = _threaded(llm.reply, model, scout_bot._system(), [], scout_bot.COMMANDS["scan"],
                        tools, scout_tools.dispatch, key, thinking)
    print((text or "(пусто)").strip()[:700], "\n")


def _run_creator(command: str = "post", avoid: str = "", hint: str = "") -> str:
    cfg, model, key, thinking = _agent("creator")
    tools = list(creator_tools.TOOLS)
    if cfg.get("web_search"):
        tools.append(creator_bot.WEB_SEARCH_TOOL)
    try:  # свежий аутбокс обложки — только картинка этого прогона (scope её не делает → отложка текстом)
        if creator_tools.MEDIA_OUTBOX.exists():
            creator_tools.MEDIA_OUTBOX.unlink()
    except Exception:
        pass
    cost.set_context("creator")
    label = ("короткий 🔭 «Под прицелом» (без обложки)" if command == "scope"
             else "пост по свежему брифу + обложка")
    print(f"✍️ [2/3] Криейтор: {label}...")
    user = creator_bot.COMMANDS[command]
    if avoid or hint:  # анти-повтор — это ОГРАНИЧЕНИЕ («чего не брать»), а НЕ приказ «пиши вот это».
        # Криейтор сам выбирает сильнейшее НЕ-повторное направление и комбинирует источники (шаги 1-2
        # его ТЗ) — иначе пост скатывается в один слабый повод и сухость (урок 30.06).
        guard = "АНТИ-ПОВТОР (сверено со свежей выгрузкой канала).\n"
        if avoid:
            guard += f"НЕ бери эти направления — они уже выходили на канале: {avoid}.\n"
        if hint:
            guard += f"Подсказка (НЕ приказ, решаешь ты): сильным НЕ-повтором выглядит «{hint}».\n"
        guard += ("Из ОСТАЛЬНЫХ направлений брифа выбери сильнейшее САМ (шаги 1-2 ТЗ: возьми сильнейшее, "
                  "СКОМБИНИРУЙ несколько источников вокруг одной антитезы, выбери формат) — не зацикливайся "
                  "на одном поводе/источнике.\n\n")
        user = guard + user
    text, _ = _threaded(llm.reply, model, creator_bot._system(), [], user,
                        tools, creator_tools.dispatch, key, thinking)
    print((text or "(пусто)").strip()[:700], "\n")
    return text or ""


def _run_scope(avoid: str = "") -> str:
    """🔭 «Под прицелом» — ОТДЕЛЬНАЯ ветка (core/scope_writer): свой лёгкий контекст + модель + 2FA
    внутри. Картинку не делает — в отложку уйдёт текстом (publish_now с kind=short)."""
    try:  # на всякий случай чистим аутбокс обложки — scope её не делает, отложка должна быть текстом
        if creator_tools.MEDIA_OUTBOX.exists():
            creator_tools.MEDIA_OUTBOX.unlink()
    except Exception:
        pass
    cost.set_context("scope")
    print("✍️ [2/3] 🔭 Под прицелом: короткий аналитический (отдельная ветка, без обложки)...")
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


def run_cycle(scope: bool = False, skip_scout: bool = False, emit=print) -> str:
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
    kind = "🔭 Под прицелом (короткий)" if scope else "флагман"
    out(f"=== Контент-завод: прогон [{kind}] ===\n")
    _mode = runmode.get()
    if _mode["mode"] == "test":
        out(f"🧪 ТЕСТ-режим: все модели → {_mode['model']} (дёшево, НЕ для прода). /main в боте — боевой.\n")
    # АКТУАЛЬНОСТЬ ДАННЫХ: выгрузка канала устарела → тянем свежие посты ДО разведки и анти-повтора
    # (иначе сверка «было/не было» врёт на самых недавних постах — там и прячется самый частый дубль).
    out("🗂 [0] Актуальность данных канала (для анти-повтора)...")
    out(str(dedup.refresh_if_stale()) + "\n")
    age = _latest_brief_age_hours()
    scout_day = datetime.date.today().weekday() in SCOUT_DAYS
    if skip_scout:
        out("⏭ Скаута пропускаю (--skip-scout): Криейтор возьмёт последний бриф.\n")
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
            _run_scout()
        except Exception:
            logging.exception("Скаут упал — продолжаю на последнем имеющемся брифе (если он есть)")
    # АНТИ-ПОВТОР (флагман И scope): сверяем направления свежего брифа с уже опубликованным ДО письма —
    # дешевле поймать дубль на теме, чем после готового поста. Данные уже актуализированы (шаг 0).
    # ГЕЙТ для обоих (дубль в канал не уйдёт); но ТЕМУ подменяем только флагману — scope сам берёт свой
    # 🔭-повод из брифа по гейту важности, ему чужая «сильнейшая не-повторная» тема не нужна.
    avoid = hint = ""
    try:
        cost.set_context("dedup")  # иначе анти-повтор логировался под чужой меткой (scout/«?») — путал в отчёте
        verdict = dedup.check(verify.latest_brief(),
                              api_key=config.agent_api_key(config.load_agent("creator")))
        out("🔁 [Анти-повтор] Сверка тем брифа с уже опубликованным (свежая выгрузка):")
        out(str(verdict) + "\n")
        if dedup.all_repeats(verdict):
            out("⛔ Все направления брифа — повторы уже вышедших постов. Пост НЕ делаю — дубль в "
                "канал не уйдёт. Нужна свежая разведка (/scan у Скаута) или новый угол.")
            return "\n".join(report)
        # Повторы — мимо для ОБОИХ. scope раньше avoid НЕ получал и брал уже вышедшую тему (баг 30.06:
        # взял x402 после поста 23.06). Тему-ПОДСКАЗКУ даём только флагману; scope повод выбирает САМ,
        # но теперь с запретом на повторы (рельсовый «пиши ИМЕННО это» давал сухой однотемный пост).
        avoid = dedup.repeat_themes(verdict)
        if not scope:
            hint = dedup.recommended_theme(verdict)
    except Exception:
        logging.exception("Анти-повтор не сработал — не блокирую, тему дальше берём из брифа сами")
    try:
        # scope — ОТДЕЛЬНАЯ ветка (свой лёгкий контекст/модель + встроенный 2FA), флагман — Криейтор.
        post = _run_scope(avoid) if scope else _run_creator("post", avoid, hint)
    except Exception as e:
        out(f"❌ Пост не сделан: {e}\nПостановку в отложку пропускаю — в канал ничего не уйдёт.")
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
    # ОБЛОЖКА флагмана: 2FA-фикс пересохраняет драфт ПОЗЖЕ make_image — и mtime-гейт publish_now ронял
    # валидную обложку в текст. Берём обложку ЭТОГО прогона из аутбокса и передаём publish_now ЯВНО (минуя
    # гейт). Аутбокс пуст (Криейтор не вызвал make_image в длинном ТЗ) → генерим САМИ из ФИНАЛЬНОГО поста:
    # одна генерация, лимит бережём, заголовок берём из финала. scope — текстом, обложку не трогаем.
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
    out("\n🗓 [3/3] Ставлю в отложенные канала...")
    out(str(_threaded(creator_tools.dispatch, "publish_now",
                      {"kind": "short" if scope else "", "cover": cover_path})))
    out("\n=== Готово. Проверь пост в нативных «Отложенных» канала. ===")
    out("\n" + cost.summary())  # реальная цена прогона Скаут→пост в $
    return "\n".join(report)


def main() -> None:
    run_cycle(scope="--scope" in sys.argv, skip_scout="--skip-scout" in sys.argv)


if __name__ == "__main__":
    main()
