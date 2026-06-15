# Агент: Разработчик

Делает **других агентов лучше** — правит их личность (`SKILL.md`) через безопасный гейт.
Код ядра НЕ трогает.

## Запуск
```
python run_dev.py
```

## Конфиг
- Модель: `claude-opus-4-8` (правит других, запускается редко — цена оправдана).
- Бот-токен: `DEVELOPER_BOT_TOKEN`. Ключ: `DEVELOPER_ANTHROPIC_KEY` (или общий).

## Инструменты (руки) — `core/dev_tools.py` → `core/workshop.py`
`list_agents`, `read_agent`, `propose_improvement`, `show_proposal`, `apply_improvement`,
`discard_proposal`, `rollback_agent`. Команды: `/agents`, `/pending`.

## Гейт безопасности (железно)
`propose` (пишет `SKILL.proposed.md`, живой файл не трогает, возвращает diff) → владелец видит diff
и говорит «ок» → `apply` (бэкап старой версии в `agents/<name>/.history/`, затем замена). Откат —
`rollback_agent`. Применить можно только то, что прошло через propose.

## Файлы
- Данные: `agents/developer/{config.yaml, SKILL.md}`
- Код: `core/dev_bot.py`, `core/dev_tools.py`, `core/workshop.py`

## Границы и будущее
Сейчас правит только `SKILL.md`. Лестница автономии + проактивный «улучшатель» с гейтом ценности —
см. [PLAN.md](../../docs/PLAN.md) §10.
