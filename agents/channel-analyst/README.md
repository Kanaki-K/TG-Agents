# Агент: Аналитик канала

Смотрит **внутрь** канала: судит о контенте **по метрикам** Telegram и подсказывает, что усиливать.
Не ищет внешний мир (это Скаут) — знает прошлое канала.

## Запуск
```
python run_analyst.py
```

## Конфиг
- Модель: `claude-haiku-4-5` (цифры считают инструменты, модель оркеструет).
- Бот-токен: `ANALYST_BOT_TOKEN`. Ключ: `ANALYST_ANTHROPIC_KEY` (или общий `ANTHROPIC_API_KEY`).

## Инструменты (руки) — `core/analyst_tools.py` → `core/analytics.py`
`channel_summary`, `themes_overview`, `top_posts`/`bottom_posts`, `by_theme`, `by_dimension`,
`find_posts`, `post_details`, `audience`, `update_metrics`, `save_playbook`.
Команды: `/report`, `/themes`, `/best`, `/timing`, `/playbook`, `/update`.

## Плейбук форматов (`/playbook`) — консультация для Криейтора
Аналитик ведёт `memory/format_playbook.md`: меню форматов поста с эффективностью (ER/репосты) и
рекомендациями, что усиливать и что попробовать **помимо длинного флагмана**. Криейтор читает этот
файл при выборе формата — так Аналитик «консультирует» через общий слой памяти (живого диалога
ботов пока нет, PLAN §11). Деление: «что заходит» — Аналитик; «как написать» — Криейтор.

## Данные
Читает `data/` (собрано коннектором `telegram_export`): `channel_posts.json`, `post_topics.json`,
`posts_analytics.*`, `channel_stats.json`.

## Файлы
- Данные: `agents/channel-analyst/{config.yaml, SKILL.md}`
- Код: `core/analyst_bot.py`, `core/analyst_tools.py`, `core/analytics.py`

## Заметки
Метрики — из последнего сбора (`telegram_export`); live-данных/Metricool пока нет. Его «руки»
(`themes_overview`, `find_posts`, `by_theme`) переиспользует Скаут для дедупа и ранжирования.
