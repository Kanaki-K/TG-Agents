"""Полная цепочка контент-завода ОДНИМ запуском (оркестратор v0 — ручной триггер):

    python run_pipeline.py                # полный прогон: Скаут → Криейтор (флагман) → отложка
    python run_pipeline.py --scope        # короткий 🔭 «Под прицелом» (аналитич., БЕЗ обложки) → отложка
    python run_pipeline.py --skip-scout   # БЕЗ Скаута: Криейтор берёт ПОСЛЕДНИЙ бриф

Скаут НЕ дёргается впустую: если последний бриф разведки младше SCOUT_FRESH_HOURS (3ч) — прогон берёт
его, повторный поиск пропускается (--skip-scout форсит пропуск всегда; свежесть и так бережёт кредиты).

В день публикации прогоняет цепь без твоего участия в передаче:
  1) Скаут — разведка → бриф (топ-темы) в memory/briefs/ [можно пропустить --skip-scout];
  2) Криейтор — тема №1: пост + обложка (make_image), сохраняет драфт;
  3) Постановка — нативная ОТЛОЖКА в канал на слот контент-плана + уведомление на @Kanaki_K.
Дальше проверяешь готовый пост в нативных «Отложенных» канала.

llm.reply каждого агента гоняется в ОТДЕЛЬНОМ потоке (как в боте через asyncio.to_thread): так
make_image (playwright-браузер) получает рабочий event-loop на Windows (иначе NotImplementedError).
Шаги 1-2 стоят кредитов Claude; шаг 3 (отложка) — нет. Любой шаг упал — печатаем причину; если пост
не родился — публикацию пропускаем (пустое в канал не уйдёт). База будущего оркестратора по расписанию.
"""
import concurrent.futures
import logging
import sys
import time

from core import (config, cost, creator_bot, creator_tools, llm, runmode, scope_writer,
                  scout_bot, scout_tools, verify)

logging.basicConfig(level=logging.INFO)

SCOUT_FRESH_HOURS = 3  # бриф свежее этого — повторную разведку не запускаем (бережём кредиты)


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


def _run_creator(command: str = "post") -> str:
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
    text, _ = _threaded(llm.reply, model, creator_bot._system(), [], creator_bot.COMMANDS[command],
                        tools, creator_tools.dispatch, key, thinking)
    print((text or "(пусто)").strip()[:700], "\n")
    return text or ""


def _run_scope() -> str:
    """🔭 «Под прицелом» — ОТДЕЛЬНАЯ ветка (core/scope_writer): свой лёгкий контекст + модель + 2FA
    внутри. Картинку не делает — в отложку уйдёт текстом (publish_now с kind=short)."""
    try:  # на всякий случай чистим аутбокс обложки — scope её не делает, отложка должна быть текстом
        if creator_tools.MEDIA_OUTBOX.exists():
            creator_tools.MEDIA_OUTBOX.unlink()
    except Exception:
        pass
    cost.set_context("scope")
    print("✍️ [2/3] 🔭 Под прицелом: короткий аналитический (отдельная ветка, без обложки)...")
    text = _threaded(scope_writer.write, "")
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


def main() -> None:
    skip_scout = "--skip-scout" in sys.argv
    scope = "--scope" in sys.argv
    cost.reset()  # начинаем замер стоимости всего прогона (Скаут→Криейтор→отложка)
    kind = "🔭 Под прицелом (короткий)" if scope else "флагман"
    print(f"=== Контент-завод: прогон [{kind}] ===\n")
    _mode = runmode.get()
    if _mode["mode"] == "test":
        print(f"🧪 ТЕСТ-режим: все модели → {_mode['model']} (дёшево, НЕ для прода). /main в боте — боевой.\n")
    age = _latest_brief_age_hours()
    if skip_scout:
        print("⏭ Скаута пропускаю (--skip-scout): Криейтор возьмёт последний бриф.\n")
    elif age is not None and age < SCOUT_FRESH_HOURS:
        print(f"⏭ Скаута пропускаю: последний бриф свежий ({age:.1f}ч < {SCOUT_FRESH_HOURS}ч) — "
              f"повторная разведка не нужна, берём его.\n")
    else:
        if age is not None:
            print(f"🔄 Последний бриф старше {SCOUT_FRESH_HOURS}ч ({age:.1f}ч) — запускаю свежую разведку.\n")
        try:
            _run_scout()
        except Exception:
            logging.exception("Скаут упал — продолжаю на последнем имеющемся брифе (если он есть)")
    try:
        # scope — ОТДЕЛЬНАЯ ветка (свой лёгкий контекст/модель + встроенный 2FA), флагман — Криейтор.
        post = _run_scope() if scope else _run_creator("post")
    except Exception as e:
        print(f"❌ Пост не сделан: {e}\nПостановку в отложку пропускаю — в канал ничего не уйдёт.")
        return
    # 2FA флагмана (Sonnet): нашёл замечания → Криейтор САМ исправляет → перепроверка. У scope свой
    # 2FA уже прошёл внутри его ветки — здесь его НЕ дублируем.
    if post and not scope:
        ckey = config.agent_api_key(config.load_agent("creator"))
        print("🔎 [Фактчек 2FA] Независимая проверка цифр/фактов (Sonnet)...")
        try:
            verdict = verify.verify_post(post, verify.latest_brief(), api_key=ckey)
            print(verdict, "\n")
            if verify.has_issues(verdict):
                print("🛠 Есть замечания — Криейтор исправляет САМ (без твоей проверки)...")
                post = _run_creator_fix(post, verdict)
                print((post or "").strip()[:600], "\n")
                print("🔎 Повторный фактчек после правок:")
                print(verify.verify_post(post, verify.latest_brief(), api_key=ckey), "\n")
        except Exception:
            logging.exception("Фактчек 2FA не удался — пост НЕ блокирую, ставлю как есть")
    print("🗓 [3/3] Ставлю в отложенные канала...")
    print(_threaded(creator_tools.dispatch, "publish_now", {"kind": "short" if scope else ""}))
    print("\n=== Готово. Проверь пост в нативных «Отложенных» канала. ===")
    print("\n" + cost.summary())  # реальная цена прогона Скаут→пост в $


if __name__ == "__main__":
    main()
