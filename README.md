# TG-Agents

Персональная мульти-агентная ИИ-команда («контент-завод») вокруг Telegram-канала и бренда владельца.
Каждый агент — отдельный Telegram-бот на общем «движке агента». Память — отдельный общий слой.

- **Зачем и куда идём:** [docs/PLAN.md](docs/PLAN.md)
- **Как устроено (инженеру):** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Контекст для Claude Code:** [CLAUDE.md](CLAUDE.md)

## Команда

| Агент | Роль | Запуск | Модель | README |
|---|---|---|---|---|
| Личный ассистент | ассистент по жизни + живой ТуДу | `python main.py` | Haiku 4.5 | [agents/personal-assistant](agents/personal-assistant/README.md) |
| Аналитик канала | судит контент по метрикам (внутрь) | `python run_analyst.py` | Haiku 4.5 | [agents/channel-analyst](agents/channel-analyst/README.md) |
| Разработчик | правит личности агентов через гейт | `python run_dev.py` | Opus 4.8 | [agents/developer](agents/developer/README.md) |
| Скаут | разведка трендов/источников (наружу) | `python run_scout.py` | Sonnet 4.6 | [agents/scout](agents/scout/README.md) |
| Криейтор | пишет посты + рисует обложку; `/schedule` ставит в отложку | `python run_creator.py` | Opus 4.8 | [agents/creator](agents/creator/README.md) |
| Публикация | вшита в Криейтора (`/schedule`): бёрнер постит ФАЙЛ фото+текст в отложку канала по MTProto | — | [agents/publisher](agents/publisher/SKILL.md) |
| **Вся цепь сразу** | Скаут → Криейтор → отложка, одной командой | `python run_pipeline.py` | — | [run_pipeline.py](run_pipeline.py) |

Рабочий контент-конвейер (работает end-to-end): **Скаут разведка → бриф → Криейтор `/post` (текст + обложка от ГПТ) → `/schedule` ставит ФАЙЛ фото+текст в нативные «Отложенные» канала на слот контент-плана + уведомляет владельца → владелец проверяет/одобряет в «Отложенных».**

Публикация — **файлом** (`send_file` фото+подпись), без хостинга/превью; одним сообщением, либо двумя, если текст не влез в подпись Telegram. Полную цепь запускает `python run_pipeline.py` (`--skip-scout` — взять последний бриф).

## Структура

```
core/         движок (agent_runtime, llm, config, tg_format) + общие слои (memory, analytics)
              + реализация агентов: <agent>_bot.py / <agent>_tools.py  (см. ARCHITECTURE)
agents/<name>/ данные агента: config.yaml + SKILL.md (личность) + README.md
connectors/   руки: telegram_export (MTProto-сбор), telegram_scan (чтение каналов), web_sources (RSS/веб)
memory/       общий слой: brand.md, post_standard.md, sources.md (канон); profile/tasks/journal (ассистент)
data/         собранные метрики канала (не в git)
docs/         PLAN.md (стратегия), ARCHITECTURE.md (карта кода)
run_*.py      точки входа (по одной на агента)
```

> Почему код агентов в `core/`, а не в `agents/<name>/`: папки агентов с дефисами — это данные
> (имя агента), а не Python-пакеты. Подробно — в [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Запуск

1. Зависимости:
   ```
   pip install -r requirements.txt
   ```
2. Завести бота в **@BotFather** на каждого агента, получить токены.
3. `cp .env.example .env` и заполнить:
   - `<AGENT>_BOT_TOKEN` — токены ботов (`SECRETARY_BOT_TOKEN`, `ANALYST_BOT_TOKEN`, `DEVELOPER_BOT_TOKEN`, `SCOUT_BOT_TOKEN`, `CREATOR_BOT_TOKEN`)
   - `ANTHROPIC_API_KEY` — общий ключ Claude (можно задать отдельные `<AGENT>_ANTHROPIC_KEY`)
   - для Скаута/Аналитика: `TELEGRAM_API_ID/HASH/SESSION` (MTProto, см. `connectors/telegram_export`)
4. Запустить нужного агента (см. таблицу) и написать его боту в Telegram.

## Принципы

- **Мозги vs руки:** LLM-логика дёшева и единообразна; сложное — коннекторы. Ядро отделено от коннекторов.
- **Память — общий внешний слой**, её можно открыть и проверить руками.
- **Секреты только в `.env`** (в git не попадает; образец — `.env.example`).
- **Новый агент** = папка в `agents/` (config+SKILL+README) + `core/<name>_bot.py`(+`_tools.py`) + `run_<name>.py`. Чеклист — в ARCHITECTURE.
