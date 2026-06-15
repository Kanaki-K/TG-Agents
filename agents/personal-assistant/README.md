# Агент: Личный ассистент (Секретарь)

Реальный ассистент по жизни + «живой ТуДу». Доступ через Telegram (текст). Первый агент команды —
на нём обкатан общий движок.

## Запуск
```
python main.py
```
(исторически через `main.py`, а не `run_*.py`.)

## Конфиг
- Модель: `claude-haiku-4-5` (дёшево на старте; поднимем при росте функционала).
- Бот-токен: `SECRETARY_BOT_TOKEN` в `.env`.
- Ключ Claude: общий `ANTHROPIC_API_KEY`.

## Инструменты (руки)
Память владельца — `core/tools.py` → `core/memory.py`: задачи (живой ТуДу), профиль (канон),
журнал сессий. Файлы лежат в `memory/` и читаются руками.

## Файлы
- Данные: `agents/personal-assistant/{config.yaml, SKILL.md}`
- Код: `core/bot.py`, `core/tools.py`, `core/memory.py`, точка входа `main.py`
- Память: `memory/profile.md`, `memory/tasks.json` / `tasks.md`, `memory/journal/`

## Границы
Текст (голос позже). Память — общий слой, не «внутри» агента.
