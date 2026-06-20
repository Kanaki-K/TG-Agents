"""Обёртка над Claude API: один проход диалога с поддержкой инструментов.

Реализован ручной агентный цикл: модель может несколько раз вызвать
инструменты (tool_use), мы выполняем их и возвращаем результат (tool_result),
пока модель не выдаст финальный текстовый ответ.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from anthropic import Anthropic

from core import config, cost

MAX_TOKENS = 16384  # вывод одного ответа: полный «не урезанный» бриф Скаута (5 направлений + вердикт) не влезал ни в 4096, ни в 8192
MAX_STEPS = 30     # предохранитель: максимум проходов цикла инструментов (глубокая разведка читает много источников)

# Кэш клиентов по ключу — у каждого агента может быть свой API-ключ.
_clients: dict[str, Anthropic] = {}


def _client(api_key: str | None = None) -> Anthropic:
    key = api_key or config.get_secret("ANTHROPIC_API_KEY")
    if key not in _clients:
        _clients[key] = Anthropic(api_key=key)
    return _clients[key]


def build_system(persona: str, memory_context: str) -> str:
    today = date.today().isoformat()
    return (f"{persona}\n\nСегодня: {today} — используй эту дату для оценки свежести "
            f"и актуальности; не считай свежим то, что старше нескольких дней без причины.\n\n"
            f"# Текущая память (контекст этой сессии)\n{memory_context}")


def reply(model: str, system: str, history: list[dict], user_text: str,
          tools_schema: list[dict], dispatch: Callable[[str, dict], str],
          api_key: str | None = None, thinking: dict | None = None) -> tuple[str, list[dict]]:
    """Один проход диалога с агентным циклом инструментов.

    tools_schema/dispatch — набор «рук» конкретного агента (память, аналитика, ...).
    api_key — свой ключ агента (если None, берётся общий ANTHROPIC_API_KEY).
    thinking — конфиг мышления (напр. {"type": "adaptive"}); None = выключено.
    Возвращает (текст ответа, обновлённую history).
    """
    client = _client(api_key)
    messages = history + [{"role": "user", "content": user_text}]

    # снять старые точки кэша из переданной истории (в ботах она переиспользуется между ходами —
    # иначе метки накопятся и превысят лимит в 4 брейкпоинта → 400). Дальше расставим заново.
    for _m in messages:
        _c = _m.get("content")
        if isinstance(_c, list):
            for _b in _c:
                if isinstance(_b, dict):
                    _b.pop("cache_control", None)

    # PROMPT CACHING растущей истории: двигаем ОДНУ точку кэша на последний результат инструментов
    # каждый проход. Тогда на следующем вызове весь прежний диалог (система+история+большие
    # результаты веб-поиска) читается из кэша за ~0.1×, а полную цену платим только за НОВое.
    prev_cache_block: dict | None = None

    steps = 0
    while True:
        steps += 1
        params = dict(
            model=model,
            max_tokens=MAX_TOKENS,
            # PROMPT CACHING: системный промпт (мануал/бренд/стандарт/плейбук) огромный и СТАТИЧНЫЙ —
            # кэшируем его, чтобы в агентном цикле (до 30 проходов на пост) он НЕ оплачивался заново
            # каждый раз, а читался из кэша за ~0.1× цены. Главный рычаг против перерасхода токенов.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=tools_schema,
            messages=messages,
        )
        if thinking:
            params["thinking"] = thinking
        resp = client.messages.create(**params)
        cost.record(model, resp.usage)  # учёт расхода: лог в консоль + копим для итога (run_pipeline)
        # сохраняем ответ ассистента (включая блоки tool_use/server_tool_use) в историю
        messages.append({"role": "assistant", "content": resp.content})

        # клиентские инструменты (наши «руки»); серверные (веб-поиск) тип server_tool_use —
        # их выполняет Anthropic, мы их здесь не диспетчеризуем
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            # серверный инструмент мог приостановить ход (pause_turn) — возобновляем,
            # повторно отправив накопленные messages (без добавления «Continue»)
            if resp.stop_reason == "pause_turn" and steps < MAX_STEPS:
                continue
            text = "".join(b.text for b in resp.content if b.type == "text")
            return text.strip(), messages

        if steps >= MAX_STEPS:  # предохранитель от зацикливания на инструментах
            text = "".join(b.text for b in resp.content if b.type == "text")
            return (text or "(достигнут предел шагов инструментов)").strip(), messages

        # выполняем инструменты и возвращаем результаты модели
        results = []
        for tu in tool_uses:
            output = dispatch(tu.name, tu.input or {})
            # tool_result не может быть пустым — иначе Anthropic отклонит запрос (400)
            if not (output and str(output).strip()):
                output = "(инструмент не вернул данных)"
            results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": str(output),
            })
        # двигаем точку кэша: ставим на последний результат этого прохода, снимаем с прошлого
        # (держим максимум одну такую точку + одну на system — под лимитом в 4 брейкпоинта)
        if prev_cache_block is not None:
            prev_cache_block.pop("cache_control", None)
        results[-1]["cache_control"] = {"type": "ephemeral"}
        prev_cache_block = results[-1]
        messages.append({"role": "user", "content": results})
