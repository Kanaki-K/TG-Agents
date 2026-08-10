# Архитектура TG-Agents

Карта проекта для инженера: что где лежит, как устроен агент, как течёт пост от идеи до канала,
как добавить агента/коннектор и что НЕЛЬЗЯ трогать не подумав.
Полное «зачем» и стратегия — в [PLAN.md](PLAN.md). Контекст для Claude Code — в [../CLAUDE.md](../CLAUDE.md).
Зрелость и панч-лист фиксов — в [AUDIT.md](AUDIT.md).

> Статус на 2026-07-15: завод работает end-to-end (Скаут→Криейтор→Публикация). **3 бота** — Скаут,
> Криейтор, Аналитик (ассистент/developer/publisher удалены 12.07 ради фокуса) + CLI-конвейеры.
> Общая зрелость 7.2/10 ([AUDIT.md](AUDIT.md)).
> **Фаза 2 (Threads): аналитика ПОДКЛЮЧЕНА** — Аналитик читает площадку инструментами
> `threads_report`/`threads_find` (с 12.07); контентная ветка «мини-флагман» — код готов и
> запускается (`/run_threads` / `run_threads_pipeline.py`, с 14.07), но полный ЗАПИСАННЫЙ цикл в проде
> ещё не прошёл (журнал дистилляций пуст) — ветка изолирована, само-обучение на Threads дормант (см. §4.2).
> НЕ подключена живая публикация В САМ Threads (веха 2.3/E) — отложку владелец ставит руками. [PLAN.md](PLAN.md).

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
connectors/   РУКИ к внешнему миру (Telegram MTProto, RSS/веб, X, ChatGPT-картинки, og:image-обложки, Threads API)
memory/       ОБЩИЙ СЛОЙ ПАМЯТИ (канон бренда, стандарт, уроки, плейбук, брифы, драфты)
data/         РАНТАЙМ-артефакты (вне git: сессии, выгрузки, обложки, cost-лог, режим)
docs/         документация (PLAN, ARCHITECTURE, AUDIT)
run_*.py      точки входа (по одной на агента) + run_pipeline.py (вся цепь) + run_cost_report.py
```

---

## 3. Точки входа (что запускает кого)

| Файл | Поднимает | Токен (.env) | Ключ Claude | Модель |
|---|---|---|---|---|
| `run_scout.py` | Скаут | `SCOUT_BOT_TOKEN` | `SCOUT_ANTHROPIC_KEY`→общий | sonnet-4-6 |
| `run_creator.py` | Криейтор | `CREATOR_BOT_TOKEN` | `CREATOR_ANTHROPIC_KEY`→общий | opus-4-8 |
| `run_analyst.py` | Аналитик | `ANALYST_BOT_TOKEN` | `ANALYST_ANTHROPIC_KEY`→общий | haiku-4-5 |
| `run_pipeline.py` | НЕ бот — вся цепь Скаут→Криейтор→2FA→отложка одной командой; `--scope` → короткая ветка 🔭 (см. [scope.md](scope.md)); вышедший флагман пишет в журнал (`flagship_journal`) | ключи агентов | — | через runmode |
| `run_threads_pipeline.py` | НЕ бот — 🧵 мини-флагман Threads: дистилляция последнего ВЫШЕДШЕГО флагмана в серию 1-4 постов → отложка ТГ-канала на ревью (`THREADS_TEST_CHANNEL`, иначе общий `PUBLISH_CHANNEL` завода — сейчас у владельца это ТЕСТОВЫЙ канал); то же — команда `/run_threads` у Криейтора | ключ Криейтора | — | sonnet через runmode |
| `refresh.py` / `refresh_threads.py` | НЕ боты — обновление аналитики ТГ / Threads одной командой (сбор→обогащение→таблица); Threads-сбор идёт под защитой `_guard` | MTProto / Threads-токен | — | — |
| `run_cost_report.py` | НЕ бот — отчёт по `data/cost_log.jsonl` (прогоны/дни/цена/кэш) | — | — | — |

**Публикация** — НЕ отдельная роль: команда `/schedule` внутри Криейтора (детерминированная, без LLM,
`creator_tools._publish_now`) + коннектор `telegram_publish`. Прежний каталог-оболочка `agents/publisher/`
удалён (12.07.2026) — это был ghost-роль без раннера; сам механизм публикации не тронут.

> **⚠️ Построено vs подключено** (аудит — чтобы не читалось как рабочие фичи):
> - **Threads-аналитика ПОДКЛЮЧЕНА; мини-флагман — код готов, но записанного прод-цикла ещё не было** (см. статус вверху).
> - **Публикация/ответы в сам Threads (`threads/publish.py`) — ПОСТРОЕНЫ (15.07), но за двумя
>   стоп-кранами и к ботам НЕ подключены**: обкатка руками через CLI (веха E), автоматизация —
>   только после неё. Ответ под чужим постом технически готов; банк целей и мозг-комментатор
>   (шаг 4) — не начаты.
> - **`threads_dedup` + `orientation_digest`** — построены и покрыты тестами, но НИКЕМ не вызываются:
>   осознанный задел «Формата 2» (Threads-контент со своей разведкой). Не достраивать вперёд нужды.
> - **Публикатор** — ghost-роль: код в `creator_tools._publish_now`, отдельного бота/входа нет (см. выше).

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
- `analytics.py` — метрики канала (читает `data/`); используют Аналитик, Скаут, Криейтор.
- `content_plan.py` — слоты ритма недели для публикации (Вт/Чт флагман, Пн/Ср/Пт короткий).
- `verify.py` — независимый 2FA-фактчек поста (Sonnet + web_search + `market_price`) перед постановкой.
- `dedup.py` — анти-повтор темы: гейт свежести выгрузки канала (старше 12ч → тянет свежие посты) +
  независимая сверка направлений брифа со сводкой тем `analytics.topics_digest()` (🆕/⚠️/🔁) ДО письма.
- `analytics_tools.py` / `market_tools.py` — общие dispatch-слои инструментов: read-only аналитика и
  живая цена `market_price` (→ `connectors/market`). Переиспользуют Скаут/Криейтор/Аналитик/2FA одинаково.
- `flagship_journal.py` — журнал ВЫШЕДШИХ флагманов (`data/published_flagships.jsonl`, append-only,
  в бэкапе): пишет `run_pipeline` ПОСЛЕ постановки отложки, читает `threads_creator` (вход дистилляции).
- `io_safe.py` — чтение JSON, которое никогда не бросает (битый файл → default + INFO-лог); горячий
  путь аналитики и шин.
- `tg_scoring.py` — честный скоринг постов ТГ (зрелость+rate+тиры) → инструмент Аналитика `honest_ranking`.
- `untrusted.py` — обёртка недоверенного внешнего текста (RSS/X/чужие каналы) против prompt-injection.

**Реализация агентов (бот + «руки» каждого):**
| Агент | Бот | Инструменты (`*_tools.py`) → бэкенд |
|---|---|---|
| channel-analyst | `analyst_bot.py` | `analyst_tools.py` → `analytics.py` |
| scout | `scout_bot.py` | `scout_tools.py` → `connectors/*` + `analytics.py` |
| creator | `creator_bot.py` | `creator_tools.py` (~17 инстр.: `make_image`, `publish_now`, `save_draft`, `read_brief`, линтер `_lint`, `record_lesson`…) → `connectors/gpt_image`, `telegram_publish`, `content_plan`, `analytics` |

> ⚠️ Криейтор НЕ «чистое письмо» — у него самый богатый набор рук (рисует обложку, ставит отложку,
> учится на правках). Старая версия этого документа врала «без инструментов».

**Ветка `scope_writer.py` (🔭 «Под прицелом», НЕ отдельный агент):** короткий аналитический пост. Свой
лёгкий `_system()` (персона Криейтера + `memory/scope_manual.md` + `voice_core.md` + brand + `scope_lessons.md`,
БЕЗ флагман-мануала и плейбука), своя модель (`SCOPE_MODEL`=opus-4-8 с 10.08 — было sonnet; мышление ВЫКЛ,
`SCOPE_THINKING=None`),
руки Криейтера минус `make_image`/правку стандарта/аналитику, встроенный 2FA. Своя петля обучения:
`record_scope_lesson` → `memory/scope_lessons.md` (даётся ТОЛЬКО в `write_feedback`, отдельно от флагман-уроков).
**Обложка — НЕ рисуется, а тянется из ПЕРВОИСТОЧНИКА:** модель отдаёт в мете `[[MEDIA_SRC]]` (3-4 URL статей) +
`[[MEDIA_SUBJECT]]` (сущности-якорь) → `connectors/source_media.fetch_source_image` тянет og:image с каждой →
vision-выбор (`_vision_pick`, `VISION_MODEL`=haiku) берёт подходящую по смыслу → путь в `SCOPE_COVER`
(`data/scope_last_cover.txt`); нет годной → пост уходит текстом. Переиспользует персону/руки Криейтера,
токена/бота своего нет. Запуск: `run_pipeline.py --scope` или команда-действие `/scope`. Подробно — [scope.md](scope.md).

**Ветка `threads_creator.py` (🧵 мини-флагман Threads, НЕ отдельный агент):** дистиллирует последний
ВЫШЕДШИЙ ТГ-флагман (вход — `flagship_journal.latest()`) в серию 1-4 коротких постов Threads. Свой
`_system()` (`threads_manual.md` + `threads_flagman_anchors.md` + `threads_lessons.md` + `brand.md` —
ТГ-мануалы НЕ грузит: голос Threads ≠ голос ТГ, доказано данными 434 постов). Без Скаута/анти-повтора/
2FA/обложки — флагман прошёл все гейты ДО публикации, мы его лишь режем. Петля обучения:
`/run_threads_feedback <финал>` → `write_feedback` → урок в `threads_lessons.md` (анти-дубль). Серия
идёт в отложку ТГ-канала НА РЕВЬЮ (это обкатка, не публикация); в сам Threads — руками (веха E).

---

## 4.1 Контентные ветки на одном ядре (флагман ↔ scope ↔ 🧵threads)

**Не три архитектуры, а ОДНО ядро → N контентных инструментов.** Флагман и scope — первые два,
мини-флагман Threads — третий (добавлен 14.07 по тому же паттерну, ядро не тронуто); Twitter по
роадмапу = №4 (та же инверсия зависимостей, §1). Разделение проходит по слою **ремесла/контента**,
и держится оно тем, **какие файлы памяти грузит каждая ветка** — а НЕ дублированием кода. Правка
одной ветки не трогает другую именно потому, что её файлы вторая не читает.

**Раздельно (ветки НЕ грузят файлы друг друга; страж — `tests/test_isolation_scope_flagship.py`):**
| | Флагман (`creator_bot`/`_run_creator`) | Scope (`scope_writer`/`_run_scope`) | 🧵 Threads (`threads_creator`) |
|---|---|---|---|
| Мануал | `content_manual.md` | `scope_manual.md` | `threads_manual.md` |
| Уроки | `post_lessons.md` (`record_lesson`) | `scope_lessons.md` (`record_scope_lesson`) | `threads_lessons.md` (`/run_threads_feedback`) |
| Голос | копия правил в `content_manual §5/§7` | `voice_core.md` | эталоны в `threads_flagman_anchors.md` |
| Выбор темы | банк+якорь (`_pick_timely_theme`, сентимент→банк) | горячий повод из брифа + гейт свежести | НЕ выбирает — дистиллирует последний вышедший флагман (`flagship_journal`) |
| Эталоны | `anchor_posts.md`, `flagship_topics.md` | `headline_bank.md` | `threads_flagman_anchors.md` |
| Обложка | GPT `make_image` (`connectors/gpt_image`) | og:image первоисточника (`connectors/source_media`) | нет (текстовая серия) |
| Модель/мышление | opus / adaptive | sonnet / бюджет (`SCOPE_THINKING`) | sonnet / без мышления |

**Общее (одно ядро — «нейтральная сантехника»):** движок (`llm`, `agent_runtime`, `config`, `cost`,
`runmode`); руки (`creator_tools` — scope переиспользует их минус `make_image`; линтер `_lint` с параметром
`kind`); **Скаут** (общий инструмент разведки: scope им живёт, флагман минимально — у него банк+сентимент,
🧵 threads НЕ пользуется вовсе); `verify` (2FA); `dedup` (модуль общий, функции ветко-специфичны);
`brand.md` (грузят все ТРИ ветки — правка бьёт по всем); Публикатор; выгрузка канала; `market_price`.

**⚠️ Где изоляция РВЁТСЯ — общие МУТАБЕЛЬНЫЕ поверхности.** Изоляция держится на договорённости, не на
коде — ничто технически не мешает протечь. Правка этих файлов бьёт по ОБЕИМ веткам (или молча по «не той»):
- `voice_core.md` — грузит **ТОЛЬКО scope** (флагман — своя копия в `content_manual §5/§7`). Урок из
  scope-правки писать в `scope_lessons.md`, **НЕ сюда** (иначе формат-специфика течёт в канон голоса).
- `verify.py`, `brand.md`, `_lint` (правило без `kind`-гарда), `dedup.py` (правь именно ветко-функцию:
  `_hits_paused` — scope-only), глобальные `llm.MAX_TOKENS` / `llm.resolve_thinking`.
- **Правила гигиены:** модель/мышление менять **per-agent через `config.yaml`**, не глобально в `llm`;
  универсальное правило голоса — в ОБЕ копии осознанно; формат-специфику (урок/подача/обложка) — только
  в файл своей ветки. (Урок сессии 09.07: правка `voice_core` из scope-разбора чуть не протекла флагману.)

---

## 4.2 Петля само-обучения на ТЕМЫ (выбор темы флагмана) — ПОДКЛЮЧЕНА для ТГ 17.07

Замыкает «скоринг → выбор темы»: мерит, какой **РАЗРЯД тем** заходит, и мягко смещает выбор темы
флагмана туда. **Влияет ТОЛЬКО на выбор темы, НЕ на подачу** (голос/формулировки залочены — метрика-нудж
на текст откатывали 13.07, Goodhart). Гейты честности: зрелость 14 дн, empirical-Bayes усадка +
уверенность вместо жёсткого MIN_N, «лучший из 1-3 постов», окно рецентности (180 дн), влияние ±30% +
бонус разведки.

**⚠️ Боевой сигнал — ТОЛЬКО ТГ, НЕ Threads.** Площадки ИНВЕРТИРОВАНЫ (находка 17.07: Рынок — дно на
Threads / топ на ТГ). Флагман живёт в ТГ → учится на ТГ (`self_learn.tg_datapoints` ставит
`threads_best=None`). Поэтому блендинг `W_THREADS=0.65` в проде **НЕ срабатывает** — это дормант-
возможность под будущий Threads-контент, а не текущее поведение.

**Подключено (боевой путь пикера флагмана):**
| Модуль | Что делает |
|---|---|
| `core/topic_category` | тема → 1 из 7 категорий (кэш банка по mtime; лог при битом банке) |
| `core/post_angle` | таксономия угла/подачи (второй объектив, диагностика) |
| `core/category_scoring` | усадка/уверенность/разведка → веса категорий (`picker_weights`) |
| `core/self_learn` | `tg_category_weights` (ТГ-датапоинты→веса) + `weighted_sample`; зовётся из `run_pipeline._pick_timely_theme` (мост, коммит cc05d8f) |

**Дормант (только `self_learn_check` + классификатор, 0 датапоинтов в проде — Threads-половина):**
`threads_distill_journal`, `text_match`, `threads_flagship_link`, `topic_datapoints` — рассчитаны на
Threads-дистилляции, которых в проде пока нет (`data/threads_distillations.jsonl` не наполнен). Не
удалять (изолировано, fail-open), **заморожено до реальных данных** — не достраивать без валидации.

Диагностика: `python -m core.self_learn_check` — рейтинг ТГ vs Threads по категориям, наклон пикера,
второй объектив. Проверено на живых данных 17.07 (площадки инвертированы, банк не ребалансим).

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

### 6.0 ДВА РЕПОЗИТОРИЯ — куда коммитить, откуда рантайм, как проверять (важно для правок)

`/workspace` — это **9p-маунт диска владельца** (`C:\Users\lodk9\PycharmProjects\PythonProject1`): правки в контейнере = его файлы на Windows сразу, без `git pull`. Версионирование разделено на ДВА репо:

| | Репо | Что | Пуш |
|---|---|---|---|
| **Код** | `github.com/Kanaki-K/TG-Agents` (**публичный**) | `core/ agents/ connectors/ tests/ docs/ run_pipeline.py` и пр. | владелец с Windows |
| **Память** | `github.com/Kanaki-K/tg-agents-memory` (**ПРИВАТНЫЙ**, вложенный `.git` в `memory/`) | крафт: `memory/*.md` + `*.json` (голос/эталоны/уроки/банки/стандарты, scope И флагман) | владелец с Windows |

**КУДА КОММИТИТЬ:**
- Правка КОДА → коммит в `/workspace` (публичный TG-Agents).
- Правка ПАМЯТИ/крафта (`memory/…`) → коммит в `/workspace/memory` (приватный tg-agents-memory). Публичный репо игнорит `memory/**` (кроме `README.md` + `journal/.gitkeep`) — крафт туда НЕ попадает.

**ОТКУДА РАНТАЙМ БЕРЁТ ИНФУ:** прогоны читают память с **ЛОКАЛЬНОГО ДИСКА** (`memory/` файлы), GitHub в прогонах НЕ участвует. Git-репо = только **бэкап + история/откат**, не источник для пайплайна.

**КАК ПРОВЕРЯТЬ (перед/после правок):**
```
git -C /workspace status                       # репо кода
git -C /workspace/memory status                # репо памяти
git -C /workspace/memory remote get-url origin # ДОЛЖЕН быть tg-agents-memory (⚠️ НЕ TG-Agents!)
git -C /workspace ls-files memory/             # публичный трекает ТОЛЬКО README.md + journal/.gitkeep
```
**⚠️ КРАСНАЯ ЛИНИЯ:** origin памяти — ТОЛЬКО приватный. Привяжешь к публичному TG-Agents → пуш сольёт весь IP (голос/эталоны) в открытый доступ. Детальный операционный мануал приватного репо — `memory/MEMORY_REPO.md` (сам приватный).

**memory/ (в ПРИВАТНОМ репо tg-agents-memory, кроме pending/briefs/drafts — см. §6.0):**
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
| `threads_manual.md` (мануал мини-флагмана 🧵: правила дистилляции/нарезки) | владелец | `threads_creator` (`_system`) |
| `threads_flagman_anchors.md` (эталоны голоса и нарезки Threads) | владелец | `threads_creator` (`_system`) |
| `threads_lessons.md` (уроки из правок серий, отдельно от ТГ) | Криейтор `/run_threads_feedback` (анти-дубль) | `threads_creator` (`_system`) |
| `threads_drafts/*.md` ★ (gitignore, архив серий) | `threads_creator` | владелец (ревью) |
| `agents/<name>/SKILL.md` (личность) | владелец вручную | этот агент `_system` |

**data/ (вне git — рантайм):**
| Файл | Писатель | Читатель |
|---|---|---|
| `channel_posts.json` / `channel_stats.json` / `post_topics.json` / `post_formats.json` | `telegram_export/*` + Аналитик | `analytics.py` |
| `threads_posts.json` / `threads_stats.json` / `threads_topics.json` / `threads_analytics.{csv,xlsx}` | `connectors/threads/*` (`refresh_threads.py`) | **Аналитик** (`threads_report`/`threads_find`, с 12.07); `threads_dedup` (задел Формата 2) |
| `threads_token.json` (авто-refresh, невосстановим без OAuth-бутстрапа; в бэкапе) | `threads/auth.py` | весь `connectors/threads/*` |
| `published_flagships.jsonl` ★ журнал ВЫШЕДШИХ флагманов (append-only, датированная история; в бэкапе) | `flagship_journal.record` (из `run_pipeline` после отложки) | `threads_creator` (вход дистилляции), линкер §4.2 |
| `threads_distillations.jsonl` ★ журнал дистилляций (флагман→серия+категория; вход петли само-обучения §4.2) | `threads_distill_journal.record` (из `threads_creator`) | `topic_datapoints`, `self_learn_check` |
| `threads_unlocked` (стоп-кран: НЕТ файла = сеть Threads ЗАКРЫТА) / `threads_cooldown` / `threads_api_log.jsonl` (журнал каждого запроса) | владелец (unlock) / `threads/_guard` | `_guard` перед КАЖДЫМ запросом; см. OPERATIONS.md |
| `threads_my_replies.json` (корпус живого голоса, 4966 реплик) + `psychotype_notes.md` / `threads_psychotype.md` (выжимка/аватар; всё в бэкапе) | разовый дамп 14.07 / ручная LLM-выжимка | владелец, будущие голосовые работы |
| `custom_emoji.json` | `telegram_emoji/collect_ids.py` | `tg_format`, `creator_tools._lint` |
| `creator_last_cover.txt` ★ / `creator_pending_media.txt` ★ | `creator_tools.make_image` | `_publish_now` (обложку цепляет, ТОЛЬКО если она свежее драфта — иначе чужая «из резерва») / `agent_runtime` |
| `scope_last_cover.txt` ★ (`SCOPE_COVER`) + `source_media/scope_*.jpg` | `scope_writer._attach_media` (og:image + vision-выбор) | `_publish_now` (обложка 🔭 из первоисточника; пусто → scope уходит текстом) |
| `creator_last_kind.txt` ★ (формат драфта: флагман/scope) | `creator_tools.save_draft` | `_publish_now` (флагман → GPT-обложка, scope → обложка из первоисточника) |
| `cost_log.jsonl` | `cost.py` | `run_cost_report.py` |
| `run_mode.txt` | `runmode.set_*` (любой бот) | `runmode.resolve` (все, каждый ход) |
| `<agent>_owner.txt` | `agent_runtime._write_owner` | `_periodic_loop` (проактивные отчёты) |
| `mtproto.session` (MTProto, **невосстановима**) | `telegram_export/login.py` | весь MTProto (export/scan/publish) |
| `gpt_profile/` / `gpt_images/*.png` | `gpt_image/login.py` / `generate.py` | `gpt_image/generate` / `telegram_publish` |

---

## 7. Коннекторы (руки): что / креды / кто зовёт

| Коннектор | Что | Креды | Зовёт |
|---|---|---|---|
| `telegram_export/` | сбор постов+статистики своего канала, разметка тем | MTProto (`TELEGRAM_API_ID/HASH/PHONE/SESSION`, `data/mtproto.session`) | CLI; `_client` импортируют scan+publish |
| `telegram_scan/` | чтение чужих каналов (Тир-3); `channels.yaml` | та же MTProto-сессия | `scout_tools` |
| `web_sources/` | RSS/Atom (Тир-2, `sources.yaml`) + `fetch_page` | публичные URL | `scout_tools` |
| `x_scan/` | твиты X-лидеров (`leaders.yaml`); монки-патч `_twikit_patch` | бёрнер-куки (`X_AUTH_TOKEN/CT0` или `data/x_cookies.json`) | `scout_tools` |
| `gpt_image/` | обложка через веб-ChatGPT (playwright) | бёрнер-профиль `data/gpt_profile/` | `creator_tools.make_image` (флагман) |
| `source_media/` | og:image со СТАТЕЙ-первоисточников → фото Telegram-размера (Pillow); живая обложка новости для 🔭 (не рисуем) | публичные URL | `scope_writer._attach_media` (обложка scope) |
| `market/` | живая цена/капа (CoinMarketCap, `quotes/latest`) для точной сверки чисел | `COINMARKETCAP_API_KEY` | `market_tools` → Скаут, Криейтор, `verify` (2FA) |
| `telegram_publish/` | нативная отложка в канал (userbot) | та же MTProto-сессия (`PUBLISH_CHANNEL/NOTIFY`) | `creator_tools._publish_now` |
| `telegram_emoji/` | сбор id кастом-эмодзи | `EMOJI_BOT_TOKEN`→`CREATOR_BOT_TOKEN` | CLI → `data/custom_emoji.json` |
| `threads/` ⚠️ **Фаза 2, аналитика подключена к Аналитику; публикация — нет** | Threads Graph API (Meta): OAuth+авто-refresh токена (`auth`), сбор постов+метрик (`collect`/`insights`), комменты живые vs self (`replies`), темы (`enrich_topics`), оценка (`scoring`), таблица (`build_table`) зеркалит ТГ, отчёт (`report`). Сбор в одну команду — `refresh_threads.py`. Публикация (веха 2.3) впереди | Threads-токен (seed в `.env` → авто-обновление в `data/threads_token.json`) | `report.build_report`/`find_posts` → инструменты Аналитика `threads_report`/`threads_find` (12.07); публикация ещё нет |

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
   футер-эмодзи/якорный жирный (ловит линтер `_lint` регэкспами), а для 🔭 — `[[MEDIA_SRC]]` /
   `[[MEDIA_SUBJECT]]` (парсит `scope_writer` регэкспом ДО 2FA-фикса, т.к. фикс мету срезает: сменишь
   формулировку маркера в `scope_writer.TASK` — обложка scope перестанет цепляться).
5. **Имя папки агента = имя везде** (`config.load_agent`, `data/<name>_owner.txt`, `.history`).
   Переименование = каскад поломок.
6. **Публикация — ФАЙЛОМ, без URL/хостинга** (выстрадано 20.06): хостинги обложек выкинуты, ломали.
   Не возвращать telegra.ph/превью-ссылки.
7. **Prompt-caching завязан на байт-стабильность системного промпта** (`llm.py`, TTL=1h). Если
   `_system()` меняется внутри серии прогонов — кэш протухает, цена растёт (`run_cost_report` кричит при
   кэш-хите <40%).
8. **Threads-токен — окно refresh 60 дней** (`threads/auth.py`): долгоживущий токен обновляется в окне
   «старше 24ч и младше 60д». Пропустил окно — доступ отваливается, нужен повторный OAuth-бутстрап.
   `data/threads_token.json` без бэкапа. (Актуально, когда коннектор подключат к боту — веха 2.3.)
9. **Изоляция веток флагман/scope/threads — статический тест + договорённость** (§4.1;
   `tests/test_isolation_scope_flagship.py` ловит протечку `_read`-ов). Правка общего МУТАБЕЛЬНОГО
   файла (`voice_core.md` — scope-only!, `verify.py`, `brand.md` — грузят все ТРИ ветки, `_lint`,
   `dedup.py`, глоб. `llm.MAX_TOKENS`/`resolve_thinking`) бьёт по всем веткам или молча по «не той».
   Модель/мышление — per-agent через `config.yaml`, не глобально. Урок/подача — в файл СВОЕЙ ветки.
10. **`flagship_journal` — продюсер-шина Threads-ветки**: `run_pipeline` пишет вышедший флагман в
    `data/published_flagships.jsonl` ПОСЛЕ постановки отложки (fail-open: сбой записи публикацию не
    роняет, но мини-флагман молча останется без свежего входа). Формат записи менять синхронно с
    `threads_creator`.
11. **Threads: сеть закрыта ПО УМОЛЧАНИЮ, запись — за ВТОРЫМ ключом** (`threads/_guard` —
    единственный вход перед сетью, обойти нельзя): нет `data/threads_unlocked` → любой запрос =
    отказ; нет `data/threads_write_unlocked` → любой ПОСТ/ОТВЕТ = отказ даже при открытом чтении.
    Бюджеты чтения И записи, темп, квота `x-app-usage` + `threads_publishing_limit`, стоп на первом
    признаке лимита + cooldown. «Threads молчит» → сначала сюда (рунбук — OPERATIONS.md), потом в код.

---

## 10. Как устроен один агент (5 частей)
1. `agents/<name>/config.yaml` — модель, `token_env`, опц. `api_key_env`, флаги (`custom_emoji`, `thinking`).
2. `agents/<name>/SKILL.md` — личность (системный промпт: роль, тон, правила).
3. `agents/<name>/README.md` — человекочитаемое описание.
4. `core/<name>_bot.py` — обвязка: собирает `tools_schema`+`dispatch`+`_system()` и зовёт `agent_runtime.run(...)`.
5. `core/<name>_tools.py` — «руки» (схемы инструментов + dispatch).

### Почему код агентов в core/, а не в agents/<name>/
Папки агентов с дефисами (`channel-analyst`) = **имя агента** (`config.load_agent`, `.history`).
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
