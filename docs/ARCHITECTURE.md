# Архитектура TG-Agents

Карта проекта для инженера: что где лежит, как устроен агент, как течёт пост от идеи до канала,
как добавить агента/коннектор и что НЕЛЬЗЯ трогать не подумав.
Полное «зачем» и стратегия — в [PLAN.md](PLAN.md). Контекст для Claude Code — в [../CLAUDE.md](../CLAUDE.md).
Зрелость и панч-лист фиксов — в [AUDIT.md](AUDIT.md).

> Статус на 2026-06-23: завод работает end-to-end (Скаут→Криейтор→Публикатор). 5 ботов + 1 «бот-без-бота»
> (Публикатор). Общая зрелость 7/10.

---

## 1. Принцип

**Мозги vs руки.** LLM-логика (рассуждения агента) дёшева и единообразна — её крутит общий
движок `core/agent_runtime.py`. Дорогое и хрупкое — это **руки**: коннекторы к внешнему миру
(`connectors/`). Ядро отделено от коннекторов, чтобы переносить систему и на другие продукты.

**Данные vs суждение** (PLAN §11): чтение данных — через общий слой (прямой вызов), обмен суждениями
между агентами — пока через ФАЙЛЫ-шину (брифы/драфты), оркестратор позже. Память — **отдельный общий
слой, ничей**.

**Инверсия зависимостей** (главный архитектурный актив): `agent_runtime.run()` полностью
параметризован (`tools_schema`/`dispatch`/`system_builder`) — движок НЕ знает про агентов; агенты
импортируют движок, не наоборот. Добавить агента = заполнить параметры, ядро не трогать.

---

## 2. Слои (дерево)

```
core/         ДВИЖОК + реализация агентов (код, импортируемый)
agents/       ОПРЕДЕЛЕНИЯ агентов (данные: config.yaml + SKILL.md + README) — папки с дефисами, НЕ пакеты
connectors/   РУКИ к внешнему миру (Telegram MTProto, RSS/веб, X, ChatGPT-картинки)
memory/       ОБЩИЙ СЛОЙ ПАМЯТИ (канон бренда, стандарт, уроки, брифы, драфты, профиль, задачи)
data/         РАНТАЙМ-артефакты (вне git: сессии, выгрузки, обложки, cost-лог, режим)
docs/         документация (PLAN, ARCHITECTURE, AUDIT)
run_*.py      точки входа (по одной на агента) + run_pipeline.py (вся цепь) + run_cost_report.py
main.py       точка входа Личного ассистента (исторически, не run_assistant.py)
```

---

## 3. Точки входа (что запускает кого)

| Файл | Поднимает | Токен (.env) | Ключ Claude | Модель |
|---|---|---|---|---|
| `main.py` | Личный ассистент | `SECRETARY_BOT_TOKEN` | `ANTHROPIC_API_KEY` | haiku-4-5 |
| `run_scout.py` | Скаут | `SCOUT_BOT_TOKEN` | `SCOUT_ANTHROPIC_KEY`→общий | sonnet-4-6 |
| `run_creator.py` | Криейтор | `CREATOR_BOT_TOKEN` | `CREATOR_ANTHROPIC_KEY`→общий | opus-4-8 |
| `run_analyst.py` | Аналитик | `ANALYST_BOT_TOKEN` | `ANALYST_ANTHROPIC_KEY`→общий | haiku-4-5 |
| `run_dev.py` | Разработчик | `DEVELOPER_BOT_TOKEN` | `DEVELOPER_ANTHROPIC_KEY`→общий | opus-4-8 |
| `run_pipeline.py` | НЕ бот — вся цепь Скаут→Криейтор→2FA→отложка одной командой; `--scope` → короткая ветка 🔭 (см. [scope.md](scope.md)) | ключи агентов | — | через runmode |
| `run_cost_report.py` | НЕ бот — отчёт по `data/cost_log.jsonl` (прогоны/дни/цена/кэш) | — | — | — |

**Публикатор** (`agents/publisher/`) — НЕ бот: точки входа и токена нет. Это команда `/schedule` внутри
Криейтора (детерминированная, без LLM) + коннектор `telegram_publish`. `config.yaml` оставлен как
документация роли.

---

## 4. core/ — что движок, а что код агента

Per-agent файлы лежат в `core/` вынужденно (см. §8 «Почему»). Таксономия:

**Движок (генерик, переиспользуется всеми):**
- `agent_runtime.py` — aiogram-бот + ход: приём → `llm.reply` → ответ. Здесь же общее: **авторизация
  OWNER_ID** (outer-middleware), подрезка истории, замок «занят», разбивка длинных ответов по `[[SPLIT]]`,
  доставка обложки+текста, периодические задачи, команды-пресеты/действия/post-hooks.
- `llm.py` — обёртка над Claude API: агентный цикл инструментов (tool_use), prompt-caching, дата в
  системный промпт, per-tool try/except.
- `config.py` — `.env` (секреты), `owner_ids()`, `agents/<name>/{config.yaml,SKILL.md}`, ключ агента.
- `runmode.py` — выбор модели: `/test` (дёшево) / `/main` (бой) / `MODEL_OVERRIDE`; глобально через
  `data/run_mode.txt`.
- `cost.py` — учёт токенов/цены каждого вызова → `data/cost_log.jsonl`.
- `tg_format.py` — Markdown ответа → Telegram-HTML (жирный/код/ссылки/списки + кастом-эмодзи).

**Общие слои данных:**
- `memory.py` — память Личного ассистента (профиль/задачи/журнал).
- `analytics.py` — метрики канала (читает `data/`); используют Аналитик, Скаут, Криейтор.
- `workshop.py` — propose→apply правок SKILL.md (только Разработчик; гейт + бэкап + анти-traversal).
- `content_plan.py` — слоты ритма недели для публикации (Вт/Чт флагман, Пн/Ср/Пт короткий).
- `verify.py` — независимый 2FA-фактчек поста (Sonnet + web_search + `market_price`) перед постановкой.
- `dedup.py` — анти-повтор темы: гейт свежести выгрузки канала (старше 12ч → тянет свежие посты) +
  независимая сверка направлений брифа со сводкой тем `analytics.topics_digest()` (🆕/⚠️/🔁) ДО письма.
- `analytics_tools.py` / `market_tools.py` — общие dispatch-слои инструментов: read-only аналитика и
  живая цена `market_price` (→ `connectors/market`). Переиспользуют Скаут/Криейтор/Аналитик/2FA одинаково.

**Реализация агентов (бот + «руки» каждого):**
| Агент | Бот | Инструменты (`*_tools.py`) → бэкенд |
|---|---|---|
| personal-assistant | `bot.py` | `tools.py` → `memory.py` |
| channel-analyst | `analyst_bot.py` | `analyst_tools.py` → `analytics.py` |
| developer | `dev_bot.py` | `dev_tools.py` → `workshop.py` |
| scout | `scout_bot.py` | `scout_tools.py` → `connectors/*` + `analytics.py` |
| creator | `creator_bot.py` | `creator_tools.py` (~17 инстр.: `make_image`, `publish_now`, `save_draft`, `read_brief`, линтер `_lint`, `record_lesson`…) → `connectors/gpt_image`, `telegram_publish`, `content_plan`, `analytics` |

> ⚠️ Криейтор НЕ «чистое письмо» — у него самый богатый набор рук (рисует обложку, ставит отложку,
> учится на правках). Старая версия этого документа врала «без инструментов».

**Ветка `scope_writer.py` (🔭 «Под прицелом», НЕ отдельный агент):** короткий аналитический пост. Свой
лёгкий `_system()` (персона Криейтера + `memory/scope_manual.md` + brand + уроки, БЕЗ флагман-мануала и
обложки), своя модель (`SCOPE_MODEL`=sonnet), руки Криейтера минус `make_image`, встроенный 2FA.
Переиспользует персону/руки Криейтера, токена/бота своего нет. Запуск: `run_pipeline.py --scope` или
команда-действие `/scope`. Подробно — [scope.md](scope.md).

---

## 5. Сквозной конвейер: как пост доходит до канала

Шаги развязаны **через ФАЙЛЫ-шину** (не через память процесса) — поэтому каждый можно гонять отдельно,
а `run_pipeline.py` просто связывает их в один прогон.

```
СКАУТ /scan
  читает: web_sources(RSS) + telegram_scan(чужие каналы) + x_scan(X-лидеры) + web_search + analytics(дедуп)
  ПИШЕТ → memory/briefs/<дата>-<slug>.md                                    ★ШИНА★
        │
        ▼
АНТИ-ПОВТОР  core/dedup  (только run_pipeline, флагман; до письма)
  [0] АКТУАЛЬНОСТЬ: выгрузка канала старше 12ч → collect+enrich_topics (свежие посты в data/)
  СВЕРКА: направления брифа ↔ analytics.topics_digest() → 🆕/⚠️/🔁; ВСЕ 🔁 → пост НЕ делается (стоп)
        │  утверждённая НЕ-повторная тема → Криейтору
        ▼
КРИЕЙТОР /post
  читает: memory/briefs/ (read_brief 'latest') + 5 файлов памяти в системный промпт + analytics(что зашло)
  рисует обложку: make_image → connectors/gpt_image → PNG в data/gpt_images/
                  путь → data/creator_last_cover.txt                        ★ШИНА★ (для /schedule)
  ПИШЕТ → memory/drafts/<дата>-<slug>.md (save_draft + код-линтер _lint)    ★ШИНА★
  АВТО-2FA (post-hook): verify.verify_post(latest_draft, latest_brief) — независимый Sonnet; правки→_fix_facts
        │
        ▼
ПУБЛИКАТОР /schedule  (command_action — БЕЗ LLM, детерминированно, $0)
  creator_tools._publish_now(): берёт последний draft + cover-файл
    → БОЙ: авто-гейт 2FA (есть замечания → НЕ публикует) + авто-2FA-код
    → content_plan.next_slot(kind) — слот по ритму недели
    → telegram_publish.publish() — MTProto userbot ставит нативную ОТЛОЖКУ в канал
    → notify(PUBLISH_NOTIFY) — ЛС владельцу «запланировано на …»
        │
        ▼
  Владелец видит/правит/одобряет в нативных «Отложенных» канала → Telegram отправляет по слоту.
```

`run_pipeline.py` гоняет всю цепь в одном процессе (тоже через те же файлы); `--skip-scout` берёт
последний бриф. Каждый шаг — в отдельном потоке (playwright/make_image требует свой event loop).

---

## 6. Память и данные: кто пишет, кто читает

`★` = шина конвейера. Источник правды для задач/форматов — JSON; `.md` генерируется.

**memory/ (в git, кроме pending/briefs/drafts):**
| Файл | Писатель | Читатель |
|---|---|---|
| `brand.md` (канон: ниша/голос/линза ценности) | владелец | Скаут, Криейтор (`_system`) |
| `content_manual.md` («библия», самый жирный вход) | владелец | Криейтор |
| `scope_manual.md` (правила рубрики 🔭, отдельно от флагмана) | владелец | `scope_writer` (`_system`) |
| `post_standard.md` (стандарт+форматы) | Криейтор `apply_standard` (бэкап `.history/`) | Скаут, Криейтор; зеркалит `content_plan.py` |
| `format_playbook.md` («что заходит») | **Аналитик** `save_playbook` | **Криейтор** `_system` |
| `post_lessons.md` (уроки из правок) | Криейтор `record_lesson` (анти-дубль) | Криейтор `_system` |
| `sources.md` / `sources.pending.md` | владелец / Скаут `propose_source` | Скаут / владелец |
| `x_authors.json` ★ леджер X (gitignore) | `x_scan.update_author` | `x_scan`, `read_x_ledger` |
| `briefs/*.md` ★ (gitignore) | Скаут `save_brief` | Криейтор, verify |
| `drafts/*.md` ★ (gitignore) | Криейтор `save_draft` | Криейтор, `_publish_now`, verify |
| `image_prompt.md` (стиль обложки) | владелец | Криейтор `_build_image_prompt` |
| `profile.md` / `tasks.json` ★ / `journal/` | Личный ассистент | он же / люди |
| `agents/<name>/SKILL.md` (личность) | **Разработчик** `workshop.apply` (бэкап `.history/`) | этот агент `_system` |

**data/ (вне git — рантайм):**
| Файл | Писатель | Читатель |
|---|---|---|
| `channel_posts.json` / `channel_stats.json` / `post_topics.json` / `post_formats.json` | `telegram_export/*` + Аналитик | `analytics.py` |
| `custom_emoji.json` | `telegram_emoji/collect_ids.py` | `tg_format`, `creator_tools._lint` |
| `creator_last_cover.txt` ★ / `creator_pending_media.txt` ★ | `creator_tools.make_image` | `_publish_now` (обложку цепляет, ТОЛЬКО если она свежее драфта — иначе чужая «из резерва») / `agent_runtime` |
| `creator_last_kind.txt` ★ (формат драфта: флагман/scope) | `creator_tools.save_draft` | `_publish_now` (обложка — только флагману, scope — текстом) |
| `cost_log.jsonl` | `cost.py` | `run_cost_report.py` |
| `run_mode.txt` | `runmode.set_*` (любой бот) | `runmode.resolve` (все, каждый ход) |
| `<agent>_owner.txt` | `agent_runtime._write_owner` | `_periodic_loop` (проактивные отчёты) |
| `evgeniyp.session` (MTProto, **невосстановима**) | `telegram_export/login.py` | весь MTProto (export/scan/publish) |
| `gpt_profile/` / `gpt_images/*.png` | `gpt_image/login.py` / `generate.py` | `gpt_image/generate` / `telegram_publish` |

---

## 7. Коннекторы (руки): что / креды / кто зовёт

| Коннектор | Что | Креды | Зовёт |
|---|---|---|---|
| `telegram_export/` | сбор постов+статистики своего канала, разметка тем | MTProto (`TELEGRAM_API_ID/HASH/PHONE/SESSION`, `data/evgeniyp.session`) | CLI; `_client` импортируют scan+publish |
| `telegram_scan/` | чтение чужих каналов (Тир-3); `channels.yaml` | та же MTProto-сессия | `scout_tools` |
| `web_sources/` | RSS/Atom (Тир-2, `sources.yaml`) + `fetch_page` | публичные URL | `scout_tools` |
| `x_scan/` | твиты X-лидеров (`leaders.yaml`); монки-патч `_twikit_patch` | бёрнер-куки (`X_AUTH_TOKEN/CT0` или `data/x_cookies.json`) | `scout_tools` |
| `gpt_image/` | обложка через веб-ChatGPT (playwright) | бёрнер-профиль `data/gpt_profile/` | `creator_tools.make_image` |
| `market/` | живая цена/капа (CoinMarketCap, `quotes/latest`) для точной сверки чисел | `COINMARKETCAP_API_KEY` | `market_tools` → Скаут, Криейтор, `verify` (2FA) |
| `telegram_publish/` | нативная отложка в канал (userbot) | та же MTProto-сессия (`PUBLISH_CHANNEL/NOTIFY`) | `creator_tools._publish_now` |
| `telegram_emoji/` | сбор id кастом-эмодзи | `EMOJI_BOT_TOKEN`→`CREATOR_BOT_TOKEN` | CLI → `data/custom_emoji.json` |

---

## 8. Авторизация и режимы

- **OWNER_ID** (`config.owner_ids()`): один outer-middleware `_owner_only` в `agent_runtime` гейтит ВСЕХ
  по `OWNER_ID` (список через запятую в `.env`). Пусто = открыт всем + громкий warning на старте. Узнать
  свой id — `/whoami`. CLI-входы (`run_pipeline`) гейт не проходят — они доверенные (запускает владелец).
- **Режим test/main** (`/test`, `/main`) — глобально для ВСЕХ ботов через `data/run_mode.txt`. `/test`
  подменяет модель на дешёвую (не публиковать в прод).

---

## 9. ⚠️ Точки хрупкости — что НЕ трогать не подумав

Перед изменением проверь, не зацепишь ли:
1. **Один MTProto-аккаунт на 3 коннектора** (`telegram_export._client` ← scan, publish). Протухла
   сессия / сменил логику клиента → разом легли аналитика, разведка ТГ И публикация.
2. **Файлы-шина без схемы** — `_publish_now` берёт САМЫЙ СВЕЖИЙ `.md` из `drafts/` по mtime. Любой
   посторонний файл в папке станет «постом». Бриф↔драфт↔verify связаны только «latest», не id.
3. **`content_plan.py` — ручное зеркало** `post_standard.md` (дни/время захардкожены). Меняешь стандарт
   текстом — план в коде НЕ обновится сам.
4. **Маркеры-протоколы модель↔код:** `[[SPLIT]]` (разбивка), `СТАТУС: ЧИСТО`/`СТАТУС: ПРАВКИ`
   (вердикт 2FA — смена формулировки в `verify` ломает авто-гейт `/schedule`), `[ПРОВЕРИТЬ]`,
   футер-эмодзи/якорный жирный (ловит линтер `_lint` регэкспами).
5. **Имя папки агента = имя везде** (`config.load_agent`, `data/<name>_owner.txt`, `.history`, workshop).
   Переименование = каскад поломок.
6. **Публикация — ФАЙЛОМ, без URL/хостинга** (выстрадано 20.06): хостинги обложек выкинуты, ломали.
   Не возвращать telegra.ph/превью-ссылки.
7. **Prompt-caching завязан на байт-стабильность системного промпта** (`llm.py`, TTL=1h). Если
   `_system()` меняется внутри серии прогонов — кэш протухает, цена растёт (`run_cost_report` кричит при
   кэш-хите <40%).

---

## 10. Как устроен один агент (5 частей)
1. `agents/<name>/config.yaml` — модель, `token_env`, опц. `api_key_env`, флаги (`custom_emoji`, `thinking`).
2. `agents/<name>/SKILL.md` — личность (системный промпт: роль, тон, правила).
3. `agents/<name>/README.md` — человекочитаемое описание.
4. `core/<name>_bot.py` — обвязка: собирает `tools_schema`+`dispatch`+`_system()` и зовёт `agent_runtime.run(...)`.
5. `core/<name>_tools.py` — «руки» (схемы инструментов + dispatch).

### Почему код агентов в core/, а не в agents/<name>/
Папки агентов с дефисами (`channel-analyst`) = **имя агента** (`config.load_agent`, `.history`, workshop).
Дефис недопустим в имени Python-пакета — `import agents.channel-analyst` невозможен. Поэтому
импортируемый код живёт в `core/` по конвенции **`core/<agent>_bot.py` + `core/<agent>_tools.py`**, а в
`agents/<name>/` — только данные. Решение 15.06.2026: для живого 5-агентного проекта стабильность важнее
структурной чистоты; «пакет-на-агента» = рефактор без выигрыша. Пересмотреть при сильном росте/команде.

---

## 11. Как добавить нового агента (чеклист)
1. `agents/<name>/` → `config.yaml` (модель, `token_env`, опц. `api_key_env`) + `SKILL.md` + `README.md`.
2. `core/<name>_tools.py` — `TOOLS` (схемы) + `dispatch(name, args)` (если нужны «руки»).
3. `core/<name>_bot.py` — `_system()` (персона + нужный контекст из памяти), `WELCOME`, `COMMANDS`, `main()`
   → `agent_runtime.run(...)`.
4. `run_<name>.py` — `asyncio.run(main())`.
5. `.env.example` + `.env` — `<NAME>_BOT_TOKEN` (+ опц. `<NAME>_ANTHROPIC_KEY`).
6. Завести бота в @BotFather, вписать токен. Если агент должен встать в конвейер — добавить шаг в
   `run_pipeline.py`. Запуск: `python run_<name>.py`.
7. `OWNER_ID` уже покрывает нового бота автоматически (гейт общий).

## 12. Как добавить новый коннектор (руку)
1. `connectors/<name>/` — модуль с публичными функциями (напр. `recent()`, `fetch()`), креды через
   `config.get_secret(...)`/`get_optional(...)` (НЕ хардкодить — см. AUDIT P0-16).
2. Внешние списки/конфиг — рядом в `<name>/*.yaml`.
3. Подключить к нужному агенту: добавить инструмент в его `*_tools.py` (схема + ветка dispatch),
   вызывающую коннектор.
4. Секреты — в `.env` + `.env.example` (пустыми). Сессии/куки/профили — в `data/` (он в .gitignore).
