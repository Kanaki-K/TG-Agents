"""Полная цепочка контент-завода ОДНИМ запуском (оркестратор v0 — ручной триггер):

    python run_pipeline.py

В день публикации прогоняет всю цепь без твоего участия в передаче:
  1) Скаут — разведка трендов → бриф (топ-темы) в memory/briefs/;
  2) Криейтор — берёт тему №1, пишет пост + рисует обложку (make_image), сохраняет драфт;
  3) Постановка — ставит нативную ОТЛОЖКУ в канал на слот контент-плана и шлёт тебе на @Kanaki_K.
Дальше ты проверяешь готовый пост в нативных «Отложенных» канала (правишь/отменяешь, обычно не трогаешь).

Работает «вхолостую» (без чата): дёргает логику агентов через llm.reply, как плановый прогон.
СТОИТ кредитов Claude (Скаут + Криейтор — это LLM). Постановка в отложку (шаг 3) кредитов НЕ ест.
Позже этот же прогон будет запускать ОРКЕСТРАТОР по расписанию (Вт/Чт/Пн/Ср/Пт). Любой шаг упал —
печатаем причину; если пост не родился — публикацию пропускаем (ничего пустого в канал не уйдёт).
"""
import logging

from core import config, creator_bot, creator_tools, llm, scout_bot, scout_tools

logging.basicConfig(level=logging.INFO)


def _agent(name: str):
    """Модель/ключ/мышление агента — как собирает его бот."""
    cfg = config.load_agent(name)
    thinking = {"type": "adaptive"} if cfg.get("thinking") == "adaptive" else None
    return cfg, cfg["model"], config.agent_api_key(cfg), thinking


def _run_scout() -> None:
    cfg, model, key, thinking = _agent("scout")
    tools = list(scout_tools.TOOLS)
    if cfg.get("web_search"):
        tools.append(scout_bot.WEB_SEARCH_TOOL)
    print("🔍 [1/3] Скаут: разведка трендов...")
    text, _ = llm.reply(model, scout_bot._system(), [], scout_bot.COMMANDS["scan"],
                        tools, scout_tools.dispatch, key, thinking)
    print((text or "(пусто)").strip()[:700], "\n")


def _run_creator() -> None:
    cfg, model, key, thinking = _agent("creator")
    tools = list(creator_tools.TOOLS)
    if cfg.get("web_search"):
        tools.append(creator_bot.WEB_SEARCH_TOOL)
    try:  # свежий аутбокс обложки — только картинка этого прогона, не старьё
        if creator_tools.MEDIA_OUTBOX.exists():
            creator_tools.MEDIA_OUTBOX.unlink()
    except Exception:
        pass
    print("✍️ [2/3] Криейтор: пишет пост по свежему брифу + обложка...")
    text, _ = llm.reply(model, creator_bot._system(), [], creator_bot.COMMANDS["post"],
                        tools, creator_tools.dispatch, key, thinking)
    print((text or "(пусто)").strip()[:700], "\n")


def main() -> None:
    print("=== Контент-завод: полный прогон ===\n")
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
    print(creator_tools.dispatch("publish_now", {}))
    print("\n=== Готово. Проверь пост в нативных «Отложенных» канала. ===")


if __name__ == "__main__":
    main()
