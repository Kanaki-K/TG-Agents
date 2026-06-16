"""Бот Скаута — разведчик трендов/источников. Обвязка над общим рантаймом.

Ищет тренды и тезисы (фиды Тир-2 + веб-поиск), проверяет достоверность и
релевантность нише (memory/brand.md), сверяется с историей канала (дедуп),
предлагает НАПРАВЛЕНИЯ для контента. Постов не пишет — это Криейтор.

Запуск: python run_scout.py   (нужны SCOUT_BOT_TOKEN и ключ Claude)
"""
from __future__ import annotations

from core import agent_runtime, analytics, config, llm, scout_tools

AGENT_NAME = "scout"

# Серверный веб-поиск Anthropic: «руки» для разведки за пределами ядра источников.
# Его выполняет Claude (не наш dispatch). max_uses — кап на стоимость одного /scan.
# Версия 20250305 (без динамической фильтрации) — не использует code-execution/контейнер,
# поэтому работает в нашем простом цикле без передачи container_id. Версия 20260209 даёт
# фильтрацию результатов кодом, но требует прокидывать container_id — это под отдельный апгрейд.
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 8}

WELCOME = (
    "Я Скаут команды KANAKI CRYPTO. Ищу тренды, тезисы и авторитетные источники, "
    "проверяю на достоверность и релевантность нише, сверяюсь с историей канала — "
    "и предлагаю НАПРАВЛЕНИЯ для контента (посты не пишу, это Криейтор).\n"
    "Команда: /scan — свежая разведка по источникам и трендам."
)

COMMANDS = {
    "scan": (
        "Проведи ГЛУБОКУЮ разведку по обоим трекам: 1) scan_sources, scan_telegram и scan_x (track='crypto' И "
        "'ai') + веб-поиск; scan_x (твиты лидеров) — ранний первичный сигнал, невидимый веб-поиску, начни с него по горячему; "
        "отдельно прогони ЦЕЛЕВЫЕ поиски пересечения AI×крипта (AI-агенты+платежи/"
        "стейблкоины; AI-капекс/энергия→макро→крипта; AI-инфра+доверие) — генуинное пересечение это гем, "
        "но не фабрикуй; 2) ГЛУБИНА: открывай ссылки через fetch_url и тащи ТОЧНЫЕ цифры-крючки "
        "(индекс страха, корреляции, ETF-потоки, даты) с источником; 3) отбери направления — целься в "
        "БЕРУЩИЙСЯ угол (контрарный инсайт, который автор захочет написать, не пересказ новости, на "
        "который скажут «ну и что»). Крипта — приоритет; чистый AI без крипто-моста → «контекст, не для "
        "поста». Сильную тему у красной линии (медвежий-звучащий макро) НЕ бросай — дай безопасный "
        "разворот (BTC не проигравший); 4) достоверность (ярлык тира требует ссылки; цифра без "
        "первоисточника → «не подтверждено»), дедуп (find_posts/by_theme), красные линии (без политоты "
        "кроме влияния на крипту; Россия — табу); 5) учти themes_overview, выдай 3-5 направлений в формате из личности."
    ),
}


def _read(rel: str) -> str:
    p = config.ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _system() -> str:
    persona = config.load_agent(AGENT_NAME)["persona"]
    ctx = (
        "## Канон бренда — фильтр релевантности (memory/brand.md)\n"
        f"{_read('memory/brand.md')}\n\n"
        "## Стандарт поста — какой контент тут силён, под что искать темы (memory/post_standard.md)\n"
        f"{_read('memory/post_standard.md')}\n\n"
        "## Реестр источников и тиры (memory/sources.md)\n"
        f"{_read('memory/sources.md')}\n\n"
        "## Сводка по каналу (для дедупа и оценки релевантности)\n"
        f"{analytics.summary()}\n"
    )
    return llm.build_system(persona, ctx)


async def main() -> None:
    cfg = config.load_agent(AGENT_NAME)
    tools = list(scout_tools.TOOLS)
    if cfg.get("web_search"):
        tools.append(WEB_SEARCH_TOOL)
    await agent_runtime.run(
        AGENT_NAME,
        tools_schema=tools,
        dispatch=scout_tools.dispatch,
        system_builder=_system,
        welcome=WELCOME,
        commands=COMMANDS,
    )
