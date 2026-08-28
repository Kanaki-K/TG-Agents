"""Обёртка над Claude API: один проход диалога с поддержкой инструментов.

Реализован ручной агентный цикл: модель может несколько раз вызвать
инструменты (tool_use), мы выполняем их и возвращаем результат (tool_result),
пока модель не выдаст финальный текстовый ответ.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Callable

from anthropic import Anthropic

from core import config, cost, runmode

MAX_TOKENS = 16384  # вывод одного ответа: полный «не урезанный» бриф Скаута (5 направлений + вердикт) не влезал ни в 4096, ни в 8192
MAX_STEPS = 30     # предохранитель: максимум проходов цикла инструментов (глубокая разведка читает много источников)

# adaptive thinking поддерживают НЕ все модели: Opus 4.6/4.7/4.8, Sonnet 4.6/5, Fable 5 — да;
# Haiku 4.5 и старые — НЕТ (API вернёт 400 «adaptive thinking is not supported»). Критично для
# /test-режима, где модель подменяется на дешёвую Haiku: там мышление надо молча снять.
_ADAPTIVE_OK = ("opus-4-6", "opus-4-7", "opus-4-8", "opus-5", "sonnet-4-6", "sonnet-5",
                "fable-5", "mythos-5")

# ФИКСИРОВАННЫЙ бюджет мышления (`budget_tokens`) живёт НЕ везде (28.08). На Opus 4.7/4.8/5, Sonnet 5
# и Fable 5 параметр СНЯТ и возвращает 400 — там глубина задаётся иначе. Раньше это было неважно:
# бюджет просил один Скаут, и он на Sonnet 4.6. Но как только роль переезжает на модель новее (а
# переезд ради цены теперь регулярный), молчащий конфиг превращается в упавший прогон. Поэтому
# несовместимый бюджет НЕ отправляем: снимаем и говорим об этом в лог. Падать целым прогоном из-за
# параметра мышления — худший из исходов; работа без мышления хотя бы доходит до конца.
_BUDGET_REMOVED = ("opus-4-7", "opus-4-8", "opus-5", "sonnet-5", "fable-5", "mythos-5")


def _supports_thinking(model: str) -> bool:
    return any(tag in model for tag in _ADAPTIVE_OK)


def _thinking_for(model: str, thinking: dict | None) -> dict | None:
    """Конфиг мышления, приведённый к тому, что МОДЕЛЬ реально принимает (иначе 400)."""
    if not thinking or not _supports_thinking(model):
        return None
    if "budget_tokens" in thinking and any(tag in model for tag in _BUDGET_REMOVED):
        logging.warning("модель %s не принимает budget_tokens (параметр снят) — мышление отключено на "
                        "этот вызов; задай 'adaptive' или верни роль на модель с бюджетом", model)
        return None
    return thinking

# Кэш клиентов по ключу — у каждого агента может быть свой API-ключ.
_clients: dict[str, Anthropic] = {}


def _client(api_key: str | None = None) -> Anthropic:
    key = api_key or config.get_secret("ANTHROPIC_API_KEY")
    if key not in _clients:
        _clients[key] = Anthropic(api_key=key)
    return _clients[key]


def _system_cache_control() -> dict:
    """Метка кэша для СИСТЕМНОГО блока: 5m в боевом режиме, 1h в /test.

    Запись кэша биллится дороже входа: 5m = 1.25×, 1h = 2× (чтение в обоих случаях 0.1×).
    Переплата за 1h окупается, только если ТОТ ЖЕ системный промпт перечитают в СЛЕДУЮЩЕМ
    прогоне в пределах часа. Замер журнала расходов (data/cost_log.jsonl, 17.08):
      • боевой режим — прогон scope раз в день; за всю историю кэш пережил до следующего
        прогона ДВАЖДЫ из 25, и оба раза уложились бы и в 5m (попадание в кэш продлевает
        TTL бесплатно — док Anthropic);
      • внутри прогона паузы между вызовами одной роли 21–48 сек (худшая — 127), то есть
        5-минутного окна хватает с запасом: 23 прогона scope из 25 и 32 из 41 у флагмана
        не имели ни одной внутренней паузы >5 мин.
    Цена ошибки несимметрична и мала: прогон без протухания экономит 0.75× записи, прогон
    с протуханием доплачивает 0.5× (перезапись 1.25× поверх 1.25× против одной 2×).
    В /test всё наоборот — там прогоны идут пачкой по нескольку в час, и 1h реально
    переиспользуется, поэтому дев-режиму метку оставляем.
    Экономия в боевом: ~$0.21 на прогоне scope, ~$3 из $29 за август (замер 17.08).
    """
    try:
        long_ttl = runmode.get()["mode"] == "test"
    except Exception:      # состояние режима недоступно — берём дешёвую метку
        long_ttl = False
    return {"type": "ephemeral", "ttl": "1h"} if long_ttl else {"type": "ephemeral"}


def build_system(persona: str, memory_context: str) -> str:
    today = date.today().isoformat()
    return (f"{persona}\n\nСегодня: {today} — используй эту дату для оценки свежести "
            f"и актуальности; не считай свежим то, что старше нескольких дней без причины.\n\n"
            f"# Текущая память (контекст этой сессии)\n{memory_context}")


def resolve_thinking(val) -> dict | None:
    """config['thinking'] → конфиг мышления для API. Единый маппинг для всех агентов.
    - 'adaptive' → адаптивное мышление (модель сама решает глубину; может РАЗДУВАТЬ вывод до потолка);
    - целое N>0  → ФИКСИРОВАННЫЙ бюджет N токенов: рассуждение есть, но кап на разгон (дешевле adaptive);
    - иначе (None/false/пусто) → мышление выключено.
    Расширяемо и обратно-совместимо: старое `thinking: adaptive` работает как раньше."""
    if val == "adaptive":
        return {"type": "adaptive"}
    if isinstance(val, bool):  # bool — подкласс int; `thinking: true` НЕ бюджет
        return None
    if isinstance(val, int) and val > 0:
        return {"type": "enabled", "budget_tokens": val}
    return None


def reply(model: str, system: str, history: list[dict], user_text: str,
          tools_schema: list[dict], dispatch: Callable[[str, dict], str],
          api_key: str | None = None, thinking: dict | None = None,
          cache_system: bool = True) -> tuple[str, list[dict]]:
    """Один проход диалога с агентным циклом инструментов.

    tools_schema/dispatch — набор «рук» конкретного агента (память, аналитика, ...).
    api_key — свой ключ агента (если None, берётся общий ANTHROPIC_API_KEY).
    thinking — конфиг мышления (напр. {"type": "adaptive"}); None = выключено.
    cache_system=False — для ONE-SHOT вызовов без инструментов и повторов (threads_creator):
    запись 1h-кэша стоит 2× входа, и без единого перечтения это чистое УДОРОЖАНИЕ (аудит 15.07).
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
            # PROMPT CACHING: системный промпт (мануал/бренд/стандарт/плейбук) огромный и СТАТИЧНЫЙ.
            # Внутри прогона его перечитывают 5-10 раз за ~0.1× — ради этого кэш и стоит. СРОК метки
            # выбирает _system_cache_control: 5m в боевом (прогон раз в день — переплата за 1h просто
            # сгорает), 1h в /test (там прогоны идут пачкой). Раньше 1h стоял всегда: обоснованием было
            # «2-3 прогона в час — типичный режим», но это про дев-дни, а не про боевой прогон.
            # cache_system=False — one-shot без перечтений: кэш там только удорожает (см. докстроку).
            system=([{"type": "text", "text": system, "cache_control": _system_cache_control()}]
                    if cache_system else [{"type": "text", "text": system}]),
            tools=tools_schema,
            messages=messages,
        )
        # мышление прикладываем ТОЛЬКО в том виде, какой модель принимает (Haiku в /test-режиме не
        # умеет adaptive, модели новее 4.6 не умеют budget_tokens — и то и другое = 400 на весь прогон)
        _th = _thinking_for(model, thinking)
        if _th:
            params["thinking"] = _th
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
            try:
                output = dispatch(tu.name, tu.input or {})
            except Exception as e:
                # один кривой инструмент НЕ должен ронять весь ход: вернём ошибку модели
                # как tool_result — она сможет среагировать/сообщить, а не упадёт хэндлер.
                logging.exception("Инструмент %s упал", tu.name)
                output = f"(ошибка инструмента {tu.name}: {e})"
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
