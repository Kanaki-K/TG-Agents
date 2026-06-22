"""Полная цепочка контент-завода ОДНИМ запуском (оркестратор v0 — ручной триггер):

    python run_pipeline.py                # полный прогон: Скаут → Криейтор → отложка
    python run_pipeline.py --skip-scout   # БЕЗ Скаута: Криейтор берёт ПОСЛЕДНИЙ бриф

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

from core import config, cost, creator_bot, creator_tools, llm, runmode, scout_bot, scout_tools

logging.basicConfig(level=logging.INFO)


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
    print("🔍 [1/3] Скаут: разведка трендов...")
    text, _ = _threaded(llm.reply, model, scout_bot._system(), [], scout_bot.COMMANDS["scan"],
                        tools, scout_tools.dispatch, key, thinking)
    print((text or "(пусто)").strip()[:700], "\n")


def _run_creator() -> None:
    cfg, model, key, thinking = _agent("creator")
    tools = list(creator_tools.TOOLS)
    if cfg.get("web_search"):
        tools.append(creator_bot.WEB_SEARCH_TOOL)
    try:  # свежий аутбокс обложки — только картинка этого прогона
        if creator_tools.MEDIA_OUTBOX.exists():
            creator_tools.MEDIA_OUTBOX.unlink()
    except Exception:
        pass
    print("✍️ [2/3] Криейтор: пишет пост по свежему брифу + обложка...")
    text, _ = _threaded(llm.reply, model, creator_bot._system(), [], creator_bot.COMMANDS["post"],
                        tools, creator_tools.dispatch, key, thinking)
    print((text or "(пусто)").strip()[:700], "\n")


def main() -> None:
    skip_scout = "--skip-scout" in sys.argv
    cost.reset()  # начинаем замер стоимости всего прогона (Скаут→Криейтор→отложка)
    print("=== Контент-завод: полный прогон ===\n")
    _mode = runmode.get()
    if _mode["mode"] == "test":
        print(f"🧪 ТЕСТ-режим: все модели → {_mode['model']} (дёшево, НЕ для прода). /main в боте — боевой.\n")
    if skip_scout:
        print("⏭ Скаута пропускаю (--skip-scout): Криейтор возьмёт последний бриф.\n")
    else:
        try:
            _run_scout()
        except Exception:
            logging.exception("Скаут упал — продолжаю на последнем имеющемся брифе (если он есть)")
    try:
        _run_creator()
    except Exception as e:
        print(f"❌ Криейтор не сделал пост: {e}\nПостановку в отложку пропускаю — в канал ничего не уйдёт.")
        return
    print("🗓 [3/3] Ставлю в отложенные канала...")
    print(_threaded(creator_tools.dispatch, "publish_now", {}))
    print("\n=== Готово. Проверь пост в нативных «Отложенных» канала. ===")
    print("\n" + cost.summary())  # реальная цена прогона Скаут→пост в $


if __name__ == "__main__":
    main()
