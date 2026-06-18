"""Markdown от модели → HTML, который рендерит Telegram.

Claude отвечает обычным Markdown (`**жирный**`, заголовки `#`, списки, `code`),
а Telegram по умолчанию показывает эти символы как есть. Telegram умеет parse_mode
HTML — переводим в него самые частые конструкции.

Сознательно НЕ трогаем курсив (`*x*` / `_x_`): одиночные `*` и `_` слишком часто
встречаются в коде и идентификаторах (`tool_use_id`, `propose_improvement`) — превратить
их в курсив опаснее, чем оставить как есть. Чиним главное: жирный, код, заголовки,
ссылки, маркеры списков.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

# Карта «обычный эмодзи-дублёр → custom_emoji_id» (собирается
# connectors/telegram_emoji/collect_ids.py). Если файла нет — кастом не подставляем,
# рендерим обычные эмодзи как есть (ничего не ломается).
_EMOJI_MAP_PATH = Path(__file__).resolve().parents[1] / "data" / "custom_emoji.json"
_emoji_map_cache: dict | None = None


def _custom_emoji_map() -> dict:
    """Лениво грузим карту кастом-эмодзи (один раз за процесс)."""
    global _emoji_map_cache
    if _emoji_map_cache is None:
        try:
            _emoji_map_cache = json.loads(_EMOJI_MAP_PATH.read_text(encoding="utf-8"))
        except Exception:
            _emoji_map_cache = {}
    return _emoji_map_cache


def to_telegram_html(text: str, *, custom_emoji: bool = False) -> str:
    """Перевести Markdown-ответ модели в безопасный для Telegram HTML.

    custom_emoji=True — подставлять кастомные эмодзи из карты (только агенты,
    которым это включено, напр. Криейтор). По умолчанию выключено.
    """
    stash: list[str] = []

    def keep(fragment: str) -> str:
        stash.append(fragment)
        return f"\x00{len(stash) - 1}\x00"  # плейсхолдер не трогается дальнейшими заменами

    # 1. Блоки кода ```...``` и инлайн `code` — прячем заранее, внутри ничего не форматируем
    text = re.sub(r"```[^\n]*\n(.*?)```", lambda m: keep(f"<pre>{html.escape(m.group(1))}</pre>"),
                  text, flags=re.S)
    text = re.sub(r"```(.+?)```", lambda m: keep(f"<pre>{html.escape(m.group(1))}</pre>"),
                  text, flags=re.S)
    text = re.sub(r"`([^`\n]+)`", lambda m: keep(f"<code>{html.escape(m.group(1))}</code>"), text)

    # 2. Остальной текст экранируем (< > & — иначе Telegram сочтёт это тегами)
    text = html.escape(text)

    # 3. Заголовки # .. ###### → жирная строка
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+(.*)$", r"<b>\1</b>", text)

    # 4. Жирный **x** и __x__ (в пределах строки — незакрытую `**` не «растягиваем»)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!_)__(.+?)__(?!_)", r"<b>\1</b>", text)

    # 5. Ссылки [текст](url)
    text = re.sub(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', text)

    # 6. Маркеры списков «- » / «* » в начале строки → «• »
    text = re.sub(r"(?m)^(\s*)[-*]\s+", r"\1• ", text)

    # 6.5 Кастомные эмодзи: известные дублёры оборачиваем в <tg-emoji emoji-id=…>.
    # Делаем ДО восстановления кода из stash — эмодзи внутри <pre>/<code> (сейчас они
    # плейсхолдеры \x00i\x00) не тронем. Только если агенту включено (custom_emoji=True)
    # и карта непуста — иначе шаг пропускается.
    if custom_emoji:
        for emoji, eid in _custom_emoji_map().items():
            if emoji and emoji in text:
                text = text.replace(emoji, f'<tg-emoji emoji-id="{eid}">{emoji}</tg-emoji>')

    # 7. Возвращаем спрятанный код
    for i, fragment in enumerate(stash):
        text = text.replace(f"\x00{i}\x00", fragment)
    return text


def strip_markdown(text: str) -> str:
    """Запасной вариант: убрать Markdown-разметку и вернуть чистый текст.

    Используется, если Telegram не смог распарсить HTML (кривая разметка от модели) —
    лучше отправить аккуратный plain-text, чем уронить ответ.
    """
    text = re.sub(r"```[^\n]*\n(.*?)```", r"\1", text, flags=re.S)
    text = re.sub(r"```(.+?)```", r"\1", text, flags=re.S)
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"(?m)^(\s*)[-*]\s+", r"\1• ", text)
    return text
