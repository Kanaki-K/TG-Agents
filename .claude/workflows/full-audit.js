export const meta = {
  name: 'full-audit',
  description: 'Полнейший аудит TG-Agents: 8 осей (архитектура/безопасность/качество/зрелость/мусор/отказоустойчивость/данные/продукт-фит) + синтез',
  whenToUse: 'Когда нужен глубокий пропорциональный аудит проекта: свежий скоринг, новые находки, что чистить/чинить. Многоразовый.',
  phases: [
    { title: 'Ревизия', detail: '8 независимых read-only ревизоров по осям' },
    { title: 'Синтез', detail: 'сводный скоринг + панч-лист + «мусор на удаление» + порядок под solo-профиль' },
  ],
}

// Профиль владельца (важен для КАЛИБРОВКИ, особенно оси продукт-фит):
// solo, не кодит сам, augmentation-не-автоматизация, бюджет-дисциплина, «не над-инженерить»,
// НЕ enterprise. Крипто-контент-завод (Telegram флагман + scope; Threads Фаза 2 не подключён).
const PROFILE = 'solo-владелец, не кодит, augmentation не автоматизация, бюджет-дисциплина, НЕ enterprise — калибруй находки под это; над-инженерию помечай как таковую'

const FINDING = {
  type: 'object',
  properties: {
    axis: { type: 'string' },
    score: { type: 'number', description: 'балл оси 1-10, откалибровано: 8+ зрелый прод, 6-7 хороший прототип, <6 сыро' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['P0', 'P1', 'P2'] },
          title: { type: 'string' },
          evidence: { type: 'string', description: 'file:line + что именно (факт, не догадка)' },
          fix: { type: 'string', description: 'конкретный минимальный фикс' },
          risk: { type: 'string', enum: ['низкий', 'средний', 'высокий'], description: 'риск ПРАВКИ для работающей системы' },
          is_new: { type: 'boolean', description: 'true — НЕ в docs/AUDIT.md (не закрыто и не известно)' },
        },
        required: ['severity', 'title', 'evidence', 'fix', 'risk', 'is_new'],
      },
    },
    strengths: { type: 'array', items: { type: 'string' }, description: 'что сделано правильно (не регрессировать)' },
  },
  required: ['axis', 'score', 'findings', 'strengths'],
}

const AXES = [
  { key: 'Архитектура', prompt: 'Слои (движок/руки/агенты/память), «мозги vs руки», DRY, coupling, расширяемость, изоляция scope↔флагман (проверь импорты памяти), согласованность docs/ARCHITECTURE.md с кодом. Читай core/*.py, agents/*, run_pipeline.py, docs/ARCHITECTURE.md.' },
  { key: 'Безопасность', prompt: 'ГЛУБОКО: секреты (grep хардкод-ключей во всём дереве + история намёков), авторизация ботов (OWNER_ID гейт), инъекции (prompt-injection из RSS/X/TG в контекст с tools-записи — есть ли core/untrusted.py и работает ли), telethon-сессии/twikit-куки/threads-токен/gpt-профиль, subprocess/eval/pickle. ЗАВИСИМОСТИ: прочти requirements*.txt/lock — устаревшие/рискованные пины, рекомендуй pip-audit. Модель угроз: кто и как может навредить. PII в коде/логах.' },
  { key: 'Качество кода', prompt: 'Обработка ошибок (Claude API/сеть/парсинг), async-корректность (блокировки event loop), дублирование, сложность, робастность JSON/CSV/MD, type hints, широкие except Exception. Читай core/*.py, connectors/*.' },
  { key: 'Инженерная зрелость', prompt: 'Тесты (что покрыто/НЕ покрыто — смотри tests/; какие core-модули без тестов), CI/линтеры (ruff/mypy/pyproject/pre-commit — есть?), lock-файл, воспроизводимость, наблюдаемость (request_id/контекст в логах — почему бот молчал в 14:05), онбординг. Читай tests/, requirements*, docs/.' },
  { key: 'Мусор и техдолг', prompt: 'ПРОЧЁСЫВАЮЩИЙ СВИП на «мусор»: мёртвый код (неиспользуемые функции/константы/импорты — grep использований), осиротевшие файлы (в data/ мусор рядом с критичным — analyze.mjs/result.json и пр.; .bat несимметрично для 1 из 5 агентов), закомментированные блоки, устаревшие докстроки/доки vs код, дублирующийся logging.basicConfig, TODO/FIXME. Дай СПИСОК на удаление с путями и «почему безопасно удалить / что проверить».' },
  { key: 'Отказоустойчивость', prompt: 'Что ЛОМАЕТСЯ, когда падает X? Единые точки отказа (один MTProto-аккаунт на export+scan+publish; X-куки; threads-токен 60-дн окно; ChatGPT-профиль обложек). Мягкая деградация (уходит ли пост текстом при отвале обложки/vision/verify). Ретраи/таймауты внешних вызовов. Восстановление после сбоя. Тихие отказы (бот молча мёртв — есть ли рестарт/health-check). Читай connectors/*, core/agent_runtime.py, core/llm.py, run_pipeline.py, docs/OPERATIONS.md.' },
  { key: 'Данные и целостность', prompt: 'Схемы JSON/CSV (согласованность, версионирование), обработка битого/пустого файла (core/io_safe уже есть — везде ли применён; остались ли голые json.loads/read_text в core И connectors), бэкап-покрытие невосстановимого (docs/OPERATIONS.md — всё ли перечислено), осиротевшие/огромные файлы в data/, файлы-шина без схемы (latest-по-mtime — риск постороннего файла). Читай core/{analytics,memory,io_safe}.py, connectors/*, data/ листинг, docs/OPERATIONS.md.' },
  { key: 'Продукт-фит и ROI', prompt: `КАЛИБРУЙ под профиль (${PROFILE}). Служит ли архитектура ЦЕЛИ (augmentation, реально используется владельцем)? Что построено, но НЕ подключено/не используется (Threads Фаза 2 не в боте; оркестратор отложен; агенты, которых не гоняют)? Где НАД-инженерия под solo-профиль, а где НЕДО-инженерия (реальные дыры)? Стоимость/ценность фич (cost-лог, дорогие пути). Не «красиво инженерно», а «служит ли делу». Честно: что бы выкинул, что достроил. Читай docs/PLAN.md, docs/AUDIT.md, все agents/*, run_pipeline.py.` },
]

phase('Ревизия')
const results = await parallel(AXES.map((a) => () =>
  agent(
    `Ось «${a.key}». ${a.prompt}\n\nСНАЧАЛА прочти docs/AUDIT.md (последний скоринг + панч-лист N-1…N-15 + changelog) и docs/ARCHITECTURE.md — НЕ дублируй уже ЗАКРЫТОЕ (☑) и помечай is_new=false для уже известного открытого. Профиль: ${PROFILE}.\n\nВыдай балл оси 1-10 (честно, без грейд-инфляции), находки с evidence (file:line), конкретным минимальным фиксом и риском ПРАВКИ, и сильные стороны. Только то, что реально в коде — не выдумывай.`,
    { label: `ось:${a.key}`, phase: 'Ревизия', schema: FINDING, agentType: 'Explore' }
  )
)).then((r) => r.filter(Boolean))

phase('Синтез')
const synthesis = await agent(
  `Ты — ведущий аудитор TG-Agents. Профиль владельца: ${PROFILE}. Прошлый скоринг (docs/AUDIT.md, 2026-07-09): Архитектура 8, Безопасность 8, Качество 7.5, Инж-зрелость 6, Общая 7.3 — за 4 оси; новые оси (мусор/отказоустойчивость/данные/продукт-фит) оцениваются впервые.\n\nТебе дают 8 осей (JSON ниже). Синтезируй ЧЕСТНО и КАЛИБРОВАННО:\n1) Балл по каждой из 8 осей + ОБЩАЯ (взвесь; объясни расхождения). Для 4 базовых — сравни с 7.3-набором.\n2) НОВЫЕ находки (is_new=true), дедуплицированы между осями, отсортированы P0>P1>P2: title, severity, evidence, fix, risk.\n3) МУСОР НА УДАЛЕНИЕ — отдельный список (путь + почему безопасно).\n4) Рекомендованный порядок фиксов под профиль владельца (дёшево+низкий риск+реальная боль вперёд; над-инженерию — в конец/выкинуть, ЯВНО помечая).\n5) Сильные стороны, подтверждённые (не регрессировать).\n6) Вердикт продукт-фита: что построено-но-не-используется, где над/недо-инженерия.\n7) summary: 3-4 фразы — где проект сейчас и главное.\nБез инфляции. Пойдёт в docs/AUDIT.md.\n\n8 ОСЕЙ:\n${JSON.stringify(results, null, 1)}`,
  {
    label: 'синтез',
    phase: 'Синтез',
    schema: {
      type: 'object',
      properties: {
        scores: {
          type: 'object',
          properties: {
            architecture: { type: 'number' }, security: { type: 'number' }, code_quality: { type: 'number' },
            eng_maturity: { type: 'number' }, junk_techdebt: { type: 'number' }, resilience: { type: 'number' },
            data_integrity: { type: 'number' }, product_fit: { type: 'number' }, overall: { type: 'number' },
          },
          required: ['architecture', 'security', 'code_quality', 'eng_maturity', 'junk_techdebt', 'resilience', 'data_integrity', 'product_fit', 'overall'],
        },
        score_note: { type: 'string' },
        new_findings: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              severity: { type: 'string', enum: ['P0', 'P1', 'P2'] },
              title: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' }, risk: { type: 'string' },
            },
            required: ['severity', 'title', 'evidence', 'fix', 'risk'],
          },
        },
        junk_to_remove: {
          type: 'array',
          items: {
            type: 'object',
            properties: { path: { type: 'string' }, why_safe: { type: 'string' } },
            required: ['path', 'why_safe'],
          },
        },
        recommended_order: { type: 'array', items: { type: 'string' } },
        confirmed_strengths: { type: 'array', items: { type: 'string' } },
        product_fit_verdict: { type: 'string' },
        summary: { type: 'string' },
      },
      required: ['scores', 'score_note', 'new_findings', 'junk_to_remove', 'recommended_order', 'confirmed_strengths', 'product_fit_verdict', 'summary'],
    },
  }
)

return { axes: results.map((r) => ({ axis: r.axis, score: r.score })), synthesis }
