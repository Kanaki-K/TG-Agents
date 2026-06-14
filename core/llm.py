"""Обёртка над Claude API: один проход диалога с поддержкой инструментов.

Реализован ручной агентный цикл: модель может несколько раз вызвать
инструменты (tool_use), мы выполняем их и возвращаем результат (tool_result),
пока модель не выдаст финальный текстовый ответ.
"""
from __future__ import annotations

from typing import Callable

from anthropic import Anthropic

from core import config

MAX_TOKENS = 2048

# Кэш клиентов по ключу — у каждого агента может быть свой API-ключ.
_clients: dict[str, Anthropic] = {}


def _client(api_key: str | None = None) -> Anthropic:
    key = api_key or config.get_secret("ANTHROPIC_API_KEY")
    if key not in _clients:
        _clients[key] = Anthropic(api_key=key)
    return _clients[key]


def build_system(persona: str, memory_context: str) -> str:
    return f"{persona}\n\n# Текущая память (контекст этой сессии)\n{memory_context}"


def reply(model: str, system: str, history: list[dict], user_text: str,
          tools_schema: list[dict], dispatch: Callable[[str, dict], str],
          api_key: str | None = None) -> tuple[str, list[dict]]:
    """Один проход диалога с агентным циклом инструментов.

    tools_schema/dispatch — набор «рук» конкретного агента (память, аналитика, ...).
    api_key — свой ключ агента (если None, берётся общий ANTHROPIC_API_KEY).
    Возвращает (текст ответа, обновлённую history).
    """
    client = _client(api_key)
    messages = history + [{"role": "user", "content": user_text}]

    while True:
        resp = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=tools_schema,
            messages=messages,
        )
        # сохраняем ответ ассистента (включая блоки tool_use) в историю
        messages.append({"role": "assistant", "content": resp.content})

        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            text = "".join(b.text for b in resp.content if b.type == "text")
            return text.strip(), messages

        # выполняем инструменты и возвращаем результаты модели
        results = []
        for tu in tool_uses:
            output = dispatch(tu.name, tu.input or {})
            results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": output,
            })
        messages.append({"role": "user", "content": results})
