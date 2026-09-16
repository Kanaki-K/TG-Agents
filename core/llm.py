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

# ⚠️ ВЫКЛЮЧЕННОЕ МЫШЛЕНИЕ ОПАСНО НЕ ВЕЗДЕ (16.09.2026). На Opus 5 мышление включено ПО УМОЛЧАНИЮ, и
# явное `disabled` там даёт два известных сбоя: модель иногда пишет ВЫЗОВ ИНСТРУМЕНТА обычным текстом
# вместо блока tool_use (ход завершается успешно, вызова нет, ошибки нет) и подтекает тегами
# <thinking>. Для завода первый сбой критичен: пост попадает на диск ТОЛЬКО через save_draft — вызов,
# написанный текстом, означает потерянный пост при зелёном логе.
# ЛЕЧЕНИЕ (рекомендация Anthropic): не выключать мышление, а включить адаптивное и понизить УСИЛИЕ.
# Это чинит оба сбоя и выходит дешевле выключенного мышления на высоком усилии по умолчанию.
_DISABLED_THINK_RISKY = ("opus-5",)
# Усилия: low | medium | high | xhigh | max. Роли без мышления получают low — им нужна не глубина
# рассуждения, а отсутствие сбоя; глубину на этих ролях и раньше не использовали.
_EFFORT_FOR_NO_THINK = "low"


def _supports_thinking(model: str) -> bool:
    return any(tag in model for tag in _ADAPTIVE_OK)


def _disabled_think_risky(model: str) -> bool:
    """Модель, на которой явное «мышление выключено» ломает вызовы инструментов."""
    return any(tag in model for tag in _DISABLED_THINK_RISKY)


# ── ВЕБ-ПОИСК: ВАРИАНТ ЗАВИСИТ ОТ МОДЕЛИ (16.09.2026) ───────────────────────────────────────────
# Завод объявлял поиск как web_search_20250305 в ШЕСТИ местах — это базовый вариант марта 2025.
# У текущего (web_search_20260209) есть динамическая фильтрация выдачи, и это прямо про нашу боль:
# «получался пересказ пресс-релиза» (22.07). Но живёт он только на Opus 4.6+ / Sonnet 4.6+, а /test
# и MODEL_OVERRIDE подменяют роль на Haiku — там новый тип вернёт 400 на весь прогон.
# Поэтому вариант выбирается ПО МОДЕЛИ в одном месте, как и конфиг мышления, а не хардкодится у ролей.
_WEB_SEARCH_MODERN_OK = ("opus-4-6", "opus-4-7", "opus-4-8", "opus-5", "sonnet-4-6", "sonnet-5",
                         "fable-5", "mythos-5")


def web_search_tool(model: str, max_uses: int = 4) -> dict:
    """Объявление веб-поиска, которое ЭТА модель примет. Новый вариант — с фильтрацией выдачи."""
    modern = any(tag in model for tag in _WEB_SEARCH_MODERN_OK)
    return {"type": "web_search_20260209" if modern else "web_search_20250305",
            "name": "web_search", "max_uses": max_uses}


def fix_web_search(tools: list, model: str) -> list:
    """Привести объявления веб-поиска в списке инструментов к варианту, который примет МОДЕЛЬ.

    Роли собирают свои списки инструментов на импорте, когда реальная модель ещё не известна
    (её выбирает runmode уже в вызове — /test и MODEL_OVERRIDE подменяют роль на дешёвую). Поэтому
    тип поиска чиним в момент вызова, сохраняя max_uses роли: у Скаута он 4, у 2FA 1, у скоупа 5 —
    это настроенные числа, не трогаем."""
    out = []
    for t in tools or []:
        if isinstance(t, dict) and str(t.get("type", "")).startswith("web_search_"):
            out.append(web_search_tool(model, int(t.get("max_uses") or 4)))
        else:
            out.append(t)
    return out


# ПОСЛЕДНИЙ ПУСТОЙ ОТВЕТ — для панели прогона. Лог видит разработчик, а владелец смотрит вывод
# команды: «модель ничего не выдала» без причины отправляет чинить наугад (случай 10.09).
LAST_EMPTY: dict = {}


def empty_reason() -> str:
    """Человеческая причина последнего пустого ответа ('' — пустых ответов не было)."""
    e = LAST_EMPTY
    if not e:
        return ""
    if e.get("stop") == "max_tokens":
        return (f"модель {e.get('model')} упёрлась в потолок вывода ({e.get('out')} из "
                f"{e.get('cap')} токенов) и не оставила текста — весь бюджет ушёл в размышление")
    return (f"модель {e.get('model')} вернула ответ без текста (stop={e.get('stop')}, "
            f"блоки: {', '.join(e.get('blocks') or []) or 'нет'})")


def no_think(model: str) -> dict:
    """Параметры вызова для роли, которой мышление НЕ нужно (готово к `**no_think(model)`).

    Нужен ПРЯМЫМ вызовам мимо llm.reply: у них нет предохранителя, а «не прислать параметр» на
    моделях новее 4.6 означает «думай сколько хочешь» — и весь max_tokens уходит в размышление.
    Так уже дважды терялся результат (судья обложек 07.09, мини-флагман Threads 10.09)."""
    return {"thinking": {"type": "disabled"}} if _supports_thinking(model) else {}


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
          cache_system: bool = True, effort: str = "") -> tuple[str, list[dict]]:
    """Один проход диалога с агентным циклом инструментов.

    tools_schema/dispatch — набор «рук» конкретного агента (память, аналитика, ...).
    api_key — свой ключ агента (если None, берётся общий ANTHROPIC_API_KEY).
    thinking — конфиг мышления (напр. {"type": "adaptive"}); None = выключено.
    cache_system=False — для ONE-SHOT вызовов без инструментов и повторов (threads_creator):
    запись 1h-кэша стоит 2× входа, и без единого перечтения это чистое УДОРОЖАНИЕ (аудит 15.07).
    effort — глубина работы модели (low|medium|high|xhigh|max; по умолчанию сервер берёт high).
    Первый рычаг цены после кэша: на ролях, где глубина не нужна, low экономит, ничего не ломая.
    Возвращает (текст ответа, обновлённую history).
    """
    client = _client(api_key)
    # ВЕБ-ПОИСК ПРИВОДИМ К МОДЕЛИ ЗДЕСЬ, а не у каждой роли: только тут известны ОБА — и список
    # инструментов, и модель, которую реально выбрал runmode. Роли объявляют поиск на импорте, когда
    # подмена на дешёвую модель (/test, MODEL_OVERRIDE) ещё не случилась.
    tools_schema = fix_web_search(tools_schema, model)
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
    force_no_think = False      # включается на повторе, когда мышление съело весь потолок вывода
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
        _th = None if force_no_think else _thinking_for(model, thinking)
        if _th:
            params["thinking"] = _th
        elif _supports_thinking(model):
            # «БЕЗ МЫШЛЕНИЯ» НАДО ГОВОРИТЬ ВСЛУХ (10.09.2026). Модели новее 4.6 думают ПО УМОЛЧАНИЮ:
            # не прислать параметр — это не «мышление выключено», это «решай сам». Конфиг роли при
            # этом говорит off, и расхождение стоит целого прогона: мини-флагман Threads на Sonnet 5
            # выдал ровно 16384 токена вывода (весь потолок) и НИ ОДНОГО блока текста — всё ушло в
            # мышление, серия пришла пустой, $0.20 в никуда. Тот же корень уже ловили 07.09 у судьи
            # обложек и лечили точечно в scope_writer; лечим в одном месте для всех ролей.
            if _disabled_think_risky(model):
                # См. _DISABLED_THINK_RISKY: на Opus 5 «disabled» роняет вызовы инструментов в текст,
                # а у завода через инструмент идёт сам пост. Включаем адаптивное на НИЗКОМ усилии —
                # это дешевле выключенного мышления на дефолтном high и без обоих сбоев.
                params["thinking"] = {"type": "adaptive"}
                params["output_config"] = {"effort": _EFFORT_FOR_NO_THINK}
            else:
                params["thinking"] = {"type": "disabled"}
        if effort and "output_config" not in params:
            params["output_config"] = {"effort": effort}
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
            if not text.strip():
                # ПУСТОЙ ОТВЕТ — НЕ «модель отказалась». Называем причину: стоп-код и типы блоков.
                # Без этой строки вызывающий печатает «модель ничего не выдала», и диагностика
                # начинается с догадок вместо факта (урок 07.09).
                LAST_EMPTY.clear()
                LAST_EMPTY.update({"model": model, "stop": resp.stop_reason, "cap": MAX_TOKENS,
                                   "out": resp.usage.output_tokens,
                                   "blocks": [b.type for b in resp.content]})
                logging.warning("модель %s вернула ПУСТОЙ текст: stop_reason=%s, блоки=%s, "
                                "выход %s ток (потолок %s)", model, resp.stop_reason,
                                [b.type for b in resp.content] or "нет", resp.usage.output_tokens,
                                MAX_TOKENS)
                if (resp.stop_reason == "max_tokens" and not force_no_think
                        and _supports_thinking(model) and steps < MAX_STEPS):
                    # Мышление съело весь потолок вывода. Один повтор с ЯВНО выключенным мышлением:
                    # ответ без мышления хуже ответа с ним, но несравнимо лучше пустого прогона.
                    logging.warning("повторяю вызов с выключенным мышлением — весь потолок вывода "
                                    "ушёл в размышление, текста не осталось")
                    messages.pop()          # ответ без текста в историю не кладём
                    force_no_think = True
                    continue
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
