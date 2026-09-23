"""🧵 Threads-ветка Криейтора: вышедший ТГ-пост → пост(ы) для площадки.

ЧЕТЫРЕ СВОДА ПРАВИЛ, площадка × формат, и они НЕ смешиваются (принцип владельца 09.09.2026):
    ТГ-флагман      → memory/content_manual.md            (core/creator_bot)
    ТГ-скоуп        → memory/scope_manual.md              (core/scope_writer)
    Threads-флагман → memory/threads_flagship_manual.md   (этот модуль, kind='flagship')
    Threads-скоуп   → memory/threads_scope_manual.md      (этот модуль, kind='scope')
Каждый формат грузит ТОЛЬКО свой мануал, свои эталоны голоса и свои уроки. Изоляцию стережёт
tests/test_isolation_formats.py — она статическая: сосед протечёт → тест покраснеет.

ОТДЕЛЬНАЯ ветка (как scope отделён от флагмана): свой лёгкий контекст, своя модель, БЕЗ Скаута /
web_search / 2FA / GPT-обложки.

Почему без 2FA: факты берутся из УЖЕ вышедшего ТГ-поста — он прошёл фактчек при своей публикации.
Переработка не вводит новых цифр, поэтому заново не верифицируем (дёшево + не тянем ТГ-обвязку).
Медиа опционально: пока владелец ставит пост в Threads руками и картинку цепляет сам.

Вход — последняя запись СВОЕГО формата в `core.published_journal` (журнал вышедших ТГ-постов).
Выход — текст: посты, разделённые строкой POST_SEP. Изоляция: свои драфты в memory/threads_drafts/
(ТГ-публикатор их НЕ видит — не перепутает с флагман/scope-драфтом).
"""
import logging
import re
from datetime import date

from core import config, content_plan, cost, llm, runmode, threads_distill_journal, threads_source

AGENT_NAME = "creator"                    # голос автора тот же — переиспользуем персону Криейтера
THREADS_MODEL = "claude-sonnet-5"        # короткий формат — Opus избыточен (как у scope); /test → Haiku
THREADS_THINKING = None                   # короткому дистилляту глубокое мышление не нужно (дёшево)

THREADS_DRAFTS_DIR = config.ROOT / "memory" / "threads_drafts"  # ОТДЕЛЬНО от ТГ-драфтов (изоляция)
POST_SEP = "[[POST]]"                      # разделитель постов серии в выводе модели
GUIDE_SEP = "[[КОММЕНТЫ]]"                 # после постов — блок ДЛЯ ВЛАДЕЛЬЦА (в канал/Threads не идёт)
MAX_LEN = 499                              # потолок площадки 500; целимся 440-499 (метод владельца, Шаг 5/7)

# Пока эта строка стоит в мануале — свод НЕ написан, и ветка отказывается работать. Генерировать
# по пустым правилам хуже, чем не генерировать: модель добрала бы недостающее из соседнего формата,
# и мы получили бы «мини-флагман под видом мини-скоупа» — ровно то, чего принцип четырёх сводов не хочет.
MANUAL_PLACEHOLDER = "(ПРАВИЛА ЕЩЁ НЕ ЗАДАНЫ)"

TASK_FLAGSHIP = (
    "Сделай МИНИ-ФЛАГМАН для Threads из вышедшего ТГ-флагмана (ниже). Правила формата — ТОЛЬКО из мануала "
    "(memory/threads_flagship_manual.md в контексте: узлы-кандидаты → отбор по трём критериям → "
    "непересечение по трём слоям → сборка → голос → длина) и эталонов голоса. Правила ТГ-форматов и "
    "мини-скоупа к тебе НЕ применяются.\n"
    "Работу по шагам веди молча — наружу выдаёшь только результат:\n"
    "1) ПОСТЫ (1-4, дефолт 2), каждый ≤" + str(MAX_LEN) + " знаков, разделённые ОТДЕЛЬНОЙ строкой «"
    + POST_SEP + "», В ПОРЯДКЕ ПУБЛИКАЦИИ, без нумерации и преамбулы.\n"
    "2) Затем ОТДЕЛЬНОЙ строкой «" + GUIDE_SEP + "» и под ней коротко для владельца (это НЕ публикуется): "
    "что осталось в ТГ (термины/цифры/honest-блок), почему такой порядок постов, какой спор пойдёт в "
    "ответах и что честно отвечать — особенно чтобы тред не прочитали как сигнал «покупай».\n\n"
    "ВЫШЕДШИЙ ФЛАГМАН (источник для переработки):\n{source}"
)

# У мини-скоупа задача НАМЕРЕННО тонкая: правила живут в его мануале, а не в этом промпте. Иначе
# получится два хозяина у одного правила — грабли, на которых ТГ-ветки уже стояли (над-инженерия
# промпта ломает качество, память scope-golden-baseline-locked).
TASK_SCOPE = (
    "Сделай МИНИ-СКОУП для Threads из вышедшего ТГ-скоупа (ниже). Правила формата — ТОЛЬКО из мануала "
    "(memory/threads_scope_manual.md в контексте: найти живущий узел → разделить два слоя → скелет → "
    "голос → длина → непересечение) и эталонов голоса. Правила ТГ-форматов и мини-флагмана к тебе НЕ "
    "применяются.\n"
    "Работу по шагам веди молча — наружу выдаёшь только результат:\n"
    "1) ОДИН пост ≤" + str(MAX_LEN) + " знаков, без нумерации и преамбулы.\n"
    "2) Затем ОТДЕЛЬНОЙ строкой «" + GUIDE_SEP + "» и под ней коротко для владельца (это НЕ публикуется): "
    "что осталось в ТГ, какой спор пойдёт в ответах и что честно отвечать — особенно чтобы тред не "
    "прочитали как сигнал «покупай».\n\n"
    "ВЫШЕДШИЙ СКОУП (источник для переработки):\n{source}"
)

FORMATS = {
    "flagship": {
        "label": "мини-флагман",
        "source_label": "флагман",
        "manual": "memory/threads_flagship_manual.md",
        "anchors": "memory/threads_flagship_anchors.md",
        "lessons": "memory/threads_flagship_lessons.md",
        "task": TASK_FLAGSHIP,
        "intro": ("## 🧵 ТЫ ДЕЛАЕШЬ МИНИ-ФЛАГМАН ДЛЯ THREADS\n"
                  "ОТДЕЛЬНЫЙ формат. Правила ТГ-флагмана (антитеза на весь пост, 2800–4096 знаков, разделы "
                  "💡/💭, обложка), ТГ-скоупа и мини-скоупа к тебе НЕ применяются. Ты берёшь УЖЕ ВЫШЕДШИЙ "
                  "ТГ-флагман и дистиллируешь его в 1–4 самостоятельных Threads-поста. Не репост и не "
                  "пересказ — новая нарезка под площадку.\n\n"),
    },
    "scope": {
        "label": "мини-скоуп",
        "source_label": "скоуп",
        "manual": "memory/threads_scope_manual.md",
        "anchors": "memory/threads_scope_anchors.md",
        "lessons": "memory/threads_scope_lessons.md",
        "task": TASK_SCOPE,
        "intro": ("## 🧵 ТЫ ДЕЛАЕШЬ МИНИ-СКОУП ДЛЯ THREADS\n"
                  "ОТДЕЛЬНЫЙ формат. Правила ТГ-скоупа, ТГ-флагмана и мини-флагмана к тебе НЕ применяются: "
                  "у мини-скоупа СВОЙ свод (ниже). Ты берёшь УЖЕ ВЫШЕДШИЙ ТГ-скоуп и делаешь из него пост "
                  "для площадки. Не репост и не пересказ.\n\n"),
    },
}


def spec(kind: str = "flagship") -> dict:
    """Свод правил формата Threads: 'flagship' | 'scope'. Имена формата — общие с ТГ (content_plan)."""
    return FORMATS[content_plan.norm_kind(kind)]


def _read(rel: str) -> str:
    p = config.ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def manual_missing(kind: str) -> bool:
    """Свод формата пуст или помечен заглушкой → работать нельзя (см. MANUAL_PLACEHOLDER)."""
    text = _read(spec(kind)["manual"]).strip()
    return not text or MANUAL_PLACEHOLDER in text


def _system(kind: str = "flagship") -> str:
    """Лёгкий контекст формата: персона + ЕГО мануал + ЕГО эталоны + красные линии бренда.
    БЕЗ ТГ-мануалов (content_manual/scope_manual/voice_core) и БЕЗ мануала соседнего Threads-формата:
    у каждого из четырёх форматов свой свод, голос переносится эталонами, а не чужими мозгами."""
    fmt = spec(kind)
    persona = config.load_agent(AGENT_NAME)["persona"]
    anchors = _read(fmt["anchors"]) or "(эталонов пока нет — держись мануала)"
    lessons = _read(fmt["lessons"]) or "(пока пусто — учусь на твоих правках)"
    ctx = (
        fmt["intro"]
        + f"## 📕 МАНУАЛ ФОРМАТА «{fmt['label'].upper()}» (правила механики) — следуй строго ({fmt['manual']})\n"
        f"{_read(fmt['manual'])}\n\n"
        f"## 🎯 ЭТАЛОНЫ ГОЛОСА — пиши В ЭТОМ голосе ({fmt['anchors']})\n"
        "Полный текст принятых владельцем постов. Голос и приём переноси ОТСЮДА (как флагман с "
        "anchor_posts): payoff первой строкой, строки-биты, лишнее за борт.\n"
        "⚠️ РЕГИСТР ИЗ ЭТАЛОНОВ НЕ БЕРИ. Они написаны при старом правиле («ты»), которое v2 отменила: "
        "обращение теперь на «Вы» или безлично, а в заголовке обращения нет вовсе. Замер: посты с «ты» "
        "брали втрое меньше охвата — дело не в местоимении, а в назидательном жанре, в котором оно жило. "
        "Из эталонов бери ГОЛОС и ПРИЁМ, регистр — по своду формата.\n"
        f"{anchors}\n\n"
        "## Канон бренда — аудитория и КРАСНЫЕ ЛИНИИ (memory/brand.md)\n"
        "Соблюдай красные линии: BTC не проигравший, без политоты/России/торговых сигналов.\n"
        f"{_read('memory/brand.md')}\n\n"
        f"## Уроки из ТВОИХ правок этого формата — ПРИМЕНЯЙ ({fmt['lessons']})\n"
        f"{lessons}\n"
    )
    return llm.build_system(persona, ctx)


def _save(series: str, src: dict, kind: str) -> None:
    """Сохранить результат в свой архив (memory/threads_drafts/). Не критично — сбой не роняет выдачу."""
    try:
        THREADS_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        raw = (src.get("theme") or "post").lower()
        slug = re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")[:40] or "post"
        fname = f"{date.today().isoformat()}-{content_plan.norm_kind(kind)}-{slug}-threads.md"
        (THREADS_DRAFTS_DIR / fname).write_text(series, encoding="utf-8", newline="\n")
    except Exception:
        logging.exception("threads_creator: не смог сохранить результат (не критично, выдаю в чат)")


FIX_LENGTH = (
    "Твои посты ниже переросли потолок площадки. Верни ВСЕ посты заново, в том же порядке и том же "
    "голосе, но каждый помеченный ❌ сожми до ≤{max} знаков — в пометке сказано, СКОЛЬКО знаков убрать. "
    "Слова внутри фраз столько не дадут: убирай ЦЕЛЫЕ предложения, которые пересказывают соседнее или "
    "объясняют то, что читатель поймёт сам; потом уточнения в скобках. "
    "Мысль, заголовок и финал сохрани. Посты без пометки не трогай.\n"
    "ВЫВОД: только посты, разделённые ОТДЕЛЬНОЙ строкой «" + POST_SEP + "», без нумерации и комментариев.\n\n"
    "{posts}"
)

LAST_LENGTH_NOTE = ""   # что случилось с длиной в последнем прогоне — для панели пайплайна
MIN_POST = 120          # короче — обрывок, а не пост (у опубликованных минимум 463)
LENGTH_ROUNDS = 3       # кругов сжатия максимум (следующий — только если прошлый не дотянул; 23.09: 564 после двух)

# ЯЗЫК v3 — ОДИН КРУГ ПРАВКИ (23.09.2026). Раньше линтер Threads только показывал претензии владельцу
# («правки НЕ вносил — решает автор»), и мини-скоуп 23.09 ушёл в ревью с антитезой в заголовке, середине
# и финале. ТГ-скоуп в v3 чинит такое кругом АВТОРА: правит тот, кто писал, и только названное — голос
# остаётся его (урок 31.07: судьи-переписчики стачивали голос). Здесь так же: один круг, перепроверка
# кодом, остаток — в отчёт владельцу.
FIX_LANGUAGE = (
    "Проверка языка (правила канала v3) нашла в постах ниже дефекты — они под каждым постом после "
    "«⛔ ДЕФЕКТЫ». Верни ВСЕ посты заново, в том же порядке и в том же голосе, исправив ТОЛЬКО названное.\n"
    "Антитезу («это не X. Это Y», «не X, а Y», «Y, а не X», «не по X - по Y», «вопрос не в X. Вопрос в Y») "
    "чинят МЕХАНИЧЕСКИ: отрицаемую половину удаляешь ЦЕЛИКОМ вместе с «не»/«а не», оставшаяся половина и "
    "есть фраза. Правки владельца: «Stripe купил не модель, а рубильник» → «Stripe купил рубильник»; "
    "«ИИ находит человека по манере мыслить, а не по словам» → «ИИ находит человека по манере мыслить»; "
    "«Вопрос не в том, знают ли имя. Вопрос в том, сколько связок осталось» → «До Вашего имени осталось "
    "несколько связок». Переставить половины или заменить «а не» на тире — НЕ починка, это та же фигура. "
    "Заголовок — одно утверждение со ставкой. Финал — простое следствие обычными словами, без перевёртыша "
    "и без образа.\n"
    "Мысль, факты, цифры и имена не меняй и не добавляй. Посты без дефектов не трогай. Длина ≤{max} знаков.\n"
    "ВЫВОД: только посты, разделённые ОТДЕЛЬНОЙ строкой «" + POST_SEP + "», без пометок, нумерации и "
    "комментариев.\n\n{posts}"
)
LAST_LANGUAGE_NOTE = ""   # что сделал круг языка — для отчёта пайплайна
LANGUAGE_ROUNDS = 2       # кругов правки языка максимум (второй — только если первый не дочистил)


# «Вы» С ЗАГЛАВНОЙ — КОДОМ, БЕЗ МОДЕЛИ (23.09.2026). Живой прогон мини-скоупа: «выдаёт вас», «против вас
# самих», «о вас уже знают». Канал: за последние 30 постов (с 11.08) обращение строчными — 0 раз, с
# заглавной — 55. Правка механическая и однозначная, модель тут не нужна (как тире и кавычки у ТГ-линтера).
_VY_LOWER = re.compile(r"\b(вы|вас|вам|вами|ваш|ваша|ваше|ваши|вашего|вашей|вашему|вашим|ваших|вашими|вашу)\b")


def _capital_vy(post: str) -> str:
    return _VY_LOWER.sub(lambda m: m.group(1)[0].upper() + m.group(1)[1:], post or "")


# СТРОКИ-БИТЫ И БЕЗ ТОЧЕК — КОДОМ (23.09.2026). Владелец переделал мини-скоуп 23.09 ровно в двух местах:
# «структуру и точки в конце предложения». Завод собрал пост в три абзаца (48 / 259 / 147 знаков), владелец
# поставил каждое предложение отдельной строкой и снял точки. Замер его постов в Threads (203 поста, 1034
# абзаца): медиана абзаца — ОДНО предложение и 66 знаков, 90-й перцентиль 150; опубликованные заводские
# посты — точка в конце строки 0 из 332 абзацев (канон канала, у ТГ его ставит линтер). Порог 140: абзац
# из 2+ предложений длиннее него режется на предложения — у владельца такие 9% абзацев, у черновика 23.09
# оба длинных, и разрез даёт ровно его правку.
BEAT_MAX = 140
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[А-ЯЁA-Z«\"0-9])")


def _typo(post: str) -> str:
    """Типографика Threads по 62 опубликованным заводским постам (замер 23.09.2026): кавычки прямые
    ("…" в 24%, «ёлочки» — 0 из 62), тире короткое с пробелами («-» в 97%, длинное «—» — 0 из 62),
    эмодзи в начале заголовка снимается (÷1.6 охвата по замеру Threads — читается как рубрика)."""
    t = re.sub(r"[«»“”„]", '"', post or "")
    t = re.sub(r"[ \t]*[—–][ \t]*", " - ", t)
    return re.sub(r"^[\s\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]+(?=\w)", "", t)


def _beats(post: str) -> str:
    out = []
    # Одиночный перенос = тоже бит (23.09: после правила «предложение — строка» писатель начал ставить
    # одиночные переносы внутри абзаца; у опубликованных постов их 0 из последних 20). Каждая строка —
    # свой абзац через пустую строку, как публикует владелец.
    for para in [q.strip() for q in re.split(r"\n+", post or "") if q.strip()]:
        parts = _SENT_SPLIT.split(para) if len(para) > BEAT_MAX else [para]
        out += [q.strip() for q in parts if q.strip()]
    # точка в конце строки — снять; многоточие, «?» и «!» — оставить
    out = [re.sub(r"(?<![.…])\.$", "", q) for q in out]
    return "\n\n".join(out)


def _enforce_language(posts: list[str], kind: str, key: str, model: str) -> list[str]:
    """Дефекты языка v3 → круг автора → перепроверка кодом, до LANGUAGE_ROUNDS кругов. Сбой/не тот
    ответ → последние целые посты. Живой прогон 23.09: антитеза в финале пережила один круг (1 → 1),
    второй круг стоит копейки (Sonnet, 500 знаков) — дешевле, чем брак в ревью."""
    global LAST_LANGUAGE_NOTE
    from core import threads_lint
    LAST_LANGUAGE_NOTE = ""
    marks = [threads_lint.language(p) for p in posts]
    before = sum(len(m) for m in marks)
    if not before:
        return posts
    cur, rounds = posts, 0
    while rounds < LANGUAGE_ROUNDS and any(marks):
        rounds += 1
        block = [p + (("\n⛔ ДЕФЕКТЫ:\n" + "\n".join(f"  • {x}" for x in m)) if m else "")
                 for p, m in zip(cur, marks)]
        user = FIX_LANGUAGE.format(max=MAX_LEN, posts=("\n" + POST_SEP + "\n").join(block))
        try:
            cost.set_context("threads-language")
            text, _ = llm.reply(model, _system(kind), [], user, [], lambda _n, _a: "", key, THREADS_THINKING,
                                cache_system=False)
            fixed = [_unmark(x).split("⛔ ДЕФЕКТЫ")[0].strip() for x in split_output(text)[0]]
        except Exception:
            logging.exception("threads: круг языка упал — оставляю последние целые посты")
            LAST_LANGUAGE_NOTE = "⚠ круг правки языка упал — дефекты ниже остались"
            return cur
        if len(fixed) != len(cur) or not all(fixed):
            LAST_LANGUAGE_NOTE = ("⚠ круг правки языка вернул не те посты — оставил "
                                  + ("исходные" if cur is posts else "итог прошлого круга") + ", дефекты ниже")
            return cur
        cur = fixed
        marks = [threads_lint.language(p) for p in cur]
    after = sum(len(m) for m in marks)
    LAST_LANGUAGE_NOTE = f"язык v3: замечаний {before} → {after} за {rounds} круг(а) автора"
    return cur


def split_output(text: str) -> tuple[list[str], str]:
    """Разобрать вывод модели: список постов + блок для ВЛАДЕЛЬЦА (что осталось в ТГ, комменты).

    Блок после GUIDE_SEP никуда не публикуется — он идёт в отчёт прогона."""
    raw = (text or "").strip()
    guide = ""
    if GUIDE_SEP in raw:
        raw, _, guide = raw.partition(GUIDE_SEP)
        guide = guide.strip()
    posts = [p.strip() for p in raw.split(POST_SEP) if p.strip()]
    return posts, guide


def _unmark(post: str) -> str:
    """Снять служебную пометку «❌ [480 знаков]», если модель вернула её эхом в сжатом посте.

    Круг сжатия отдаёт модели посты с такой приставкой (по ней она видит, что резать). Эхо никто не срезал:
    пометка уезжала в ревью-копию, а оттуда в Threads (аудит 11.09.2026)."""
    s = (post or "").lstrip()
    if s.startswith("❌"):
        s = s[1:].lstrip()
    head = s[:60]   # пометка с числом «[703 знаков — убрать минимум 224]» длиннее прежней (23.09)
    if s.startswith("[") and "]" in head and "знак" in head:
        s = s[s.index("]") + 1:].lstrip()
    return s


def _enforce_length(posts: list[str], kind: str, key: str, model: str) -> list[str]:
    """Метод владельца, Шаг «считаю знаки реально»: перебор ≤MAX_LEN лечим ОДНИМ кругом сжатия.

    Почему кодом, а не надеждой на промпт: Threads-публикатор режет пост >500 жёстко (линт охвата),
    и «на глаз» модель промахивается регулярно. Один круг — потолок цены; не помогло — отдаём как есть
    с пометкой, владелец видит перебор в отчёте и решает сам (пост не теряем)."""
    global LAST_LENGTH_NOTE
    # ДВА КРУГА С ЧИСЛОМ (23.09.2026). Был один круг «режь воду»: живой мини-скоуп 703 знака → 654, всё
    # ещё за потолком. Модель не знала, СКОЛЬКО резать, и ужимала слова. Теперь пометка называет число,
    # промпт разрешает целые предложения, и второй круг есть, если первого не хватило.
    first_over = [i for i, p in enumerate(posts) if len(p) > MAX_LEN]
    if not first_over:
        LAST_LENGTH_NOTE = ""
        return posts
    cur = posts
    for _round in range(LENGTH_ROUNDS):
        over = [i for i, p in enumerate(cur) if len(p) > MAX_LEN]
        if not over:
            break
        marked = ("\n" + POST_SEP + "\n").join(
            (f"❌ [{len(p)} знаков — убрать минимум {len(p) - MAX_LEN + 20}] " if i in over else f"[{len(p)} знаков] ")
            + p for i, p in enumerate(cur))
        try:
            text, _ = llm.reply(model, _system(kind), [], FIX_LENGTH.format(max=MAX_LEN, posts=marked),
                                [], lambda _n, _a: "", key, THREADS_THINKING, cache_system=False)
            fixed, _ = split_output(text)
            fixed = [_unmark(p) for p in fixed]
        except Exception:
            logging.exception("threads_creator: круг сжатия по длине упал — отдаю посты как есть")
            fixed = []
        if len(fixed) != len(cur):    # модель потеряла/склеила пост — своим версиям верим больше
            LAST_LENGTH_NOTE = (f"перебор в {len(first_over)} посте(ах), круг сжатия вернул не тот состав — "
                                + ("оставил исходные" if cur is posts else "оставил итог прошлого круга"))
            return cur
        cur = fixed
    still = [i for i, p in enumerate(cur) if len(p) > MAX_LEN]
    LAST_LENGTH_NOTE = (f"перебор в {len(first_over)} посте(ах) → сжал; всё ещё длинны: {len(still)}"
                        if still else f"перебор в {len(first_over)} посте(ах) → сжал в норму")
    return cur


def write(kind: str = "flagship", hint: str = "", back: int = 0, src: dict | None = None,
          record: bool = True) -> str:
    """Переработать вышедший ТГ-пост своего формата в пост(ы) Threads.

    src — готовый исходник от вызывающего (пайплайн уже его достал и показал владельцу). Передавать
    ЕГО, а не доставать заново: 09.09 пайплайн печатал один пост, а писатель молча брал из журнала
    другой — в отчёте был скоуп про SEC, а на выходе тред про Дорси. Один источник на прогон.
    back — если src не передан: 0 = последний из журнала, N≥1 = N-й с конца пост канала (обкатка).
    record — писать ли серию в журнал переработок здесь же. Пайплайн передаёт False и пишет сам ПОСЛЕ
    постановки в отложку: иначе --review-only и упавшая постановка копили в журнале версии, которые никуда
    не вышли, и сверщик потом связывал посты Threads с ними (аудит 11.09.2026).
    Возвращает текст (посты через POST_SEP) или сообщение об отказе (нет материала / нет свода правил)."""
    k = content_plan.norm_kind(kind)
    fmt = spec(k)
    if manual_missing(k):
        return (f"⚠️ Свод правил формата «{fmt['label']}» ещё не написан ({fmt['manual']}). "
                "Пока он пуст, я не пишу: взял бы правила соседнего формата — а они не про этот. "
                "Положи правила в файл и убери строку-заглушку.")
    src = src or threads_source.resolve(k, back)
    if not src or not src.get("text"):
        return (f"⚠️ В журнале вышедших ТГ-постов нет ни одного формата «{fmt['source_label']}» — "
                f"перерабатывать нечего. Опубликуй {fmt['source_label']} в ТГ (он запишется в журнал), "
                "потом запускай.")
    cfg = config.load_agent(AGENT_NAME)
    key = config.agent_api_key(cfg)
    model = runmode.resolve(THREADS_MODEL, ceiling=THREADS_MODEL)
    task = fmt["task"].format(source=src["text"])
    # УЗЕЛ, ПОМЕЧЕННЫЙ АВТОРОМ ТГ-ПОСТА (v2, 10.09.2026). Автор дистилляций просил прямо: «если бы
    # завод сам помечал — вот это мысль, вот это цифры — дистилляция шла бы вдвое быстрее». Отдаём
    # пометку как ПОДСКАЗКУ, а не приказ: право взять узел сильнее остаётся у писателя, и расхождение
    # «что считали узлом» против «что сработало» мы через месяц померим.
    nodes = [n for n in (src.get("nodes") or []) if str(n).strip()]
    if nodes:
        task += ("\n\nУЗЛЫ, ПОМЕЧЕННЫЕ АВТОРОМ ТГ-ПОСТА (что он считал живущим само):\n"
                 + "\n".join(f"- {n}" for n in nodes)
                 + "\nНачни с них. Видишь узел сильнее — бери свой и скажи об этом в блоке для владельца.")
    if hint:
        task += f"\n\nПОЖЕЛАНИЕ ВЛАДЕЛЬЦА: {hint}"
    cost.set_context("threads")  # иначе расход пишется who='?' — аудит 15.07 не смог его атрибутировать
    # one-shot без инструментов → кэш системы не окупается (запись 1h = 2× без перечтений)
    text, _ = llm.reply(model, _system(k), [], task, [], lambda _n, _a: "", key, THREADS_THINKING,
                        cache_system=False)
    posts, guide = split_output(text)
    # ОБРЫВОК ВМЕСТО ПОСТА (23.09.2026): мини-флагман выдал первым «постом» строку «Я нашёл его нужную
    # сумму денег» (30 знаков), и круги правки отказывались работать — «вернул не те посты». У 62
    # опубликованных самый короткий — 463 знака. Обрывок короче MIN_POST в серии из нескольких постов
    # выбрасываем и говорим об этом; единственный пост не трогаем — пусть владелец увидит.
    if len(posts) > 1 and any(len(p) < MIN_POST for p in posts):
        logging.warning("threads: выброшен обрывок вместо поста: %s", [p for p in posts if len(p) < MIN_POST])
        posts = [p for p in posts if len(p) >= MIN_POST] or posts
    if not posts:
        return (text or "").strip()          # модель ничего не выдала — отдаём сырое, пайплайн покажет
    posts = _enforce_language(posts, k, key, model)   # до длины: правка может удлинить пост
    posts = _enforce_length(posts, k, key, model)
    posts = [_beats(_typo(_capital_vy(p))) for p in posts]   # последним: круги правок пишут это заново
    if any(len(p) > MAX_LEN for p in posts):            # разрез добавляет переносы — перебор возможен
        posts = [_beats(_typo(_capital_vy(p))) for p in _enforce_length(posts, k, key, model)]
    # ФИНАЛЬНАЯ ПЕРЕПРОВЕРКА ЯЗЫКА (23.09.2026): круг сжатия длины идёт ПОСЛЕ круга языка и переписывает
    # текст — живой прогон вернул так антитезу в заголовок («никогда не была про имя» / «Она была про…»).
    # Нашлось — ещё один круг языка по итоговому тексту; отчёт пайплайна скажет, что осталось.
    from core import threads_lint
    if any(threads_lint.language(p) for p in posts):
        _note = LAST_LANGUAGE_NOTE
        posts = [_beats(_typo(_capital_vy(p))) for p in _enforce_language(posts, k, key, model)]
        globals()["LAST_LANGUAGE_NOTE"] = (_note + "; после сжатия — " + LAST_LANGUAGE_NOTE).strip("; ")
        if any(len(p) > MAX_LEN for p in posts):        # правка языка могла удлинить (живой прогон: 502)
            posts = [_beats(_typo(_capital_vy(p))) for p in _enforce_length(posts, k, key, model)]
    body = ("\n" + POST_SEP + "\n").join(posts)
    _save(body + (f"\n\n{GUIDE_SEP}\n{guide}" if guide else ""), src, k)
    # Журнал переработок: связь «ТГ-пост → его Threads-версия» + категория (вход петли само-обучения).
    # Пишем ТОЛЬКО посты: блок для владельца в Threads не выходит и связь бы только зашумил.
    if record:
        threads_distill_journal.record(src, body, POST_SEP)
    return body + (f"\n\n{GUIDE_SEP}\n{guide}" if guide else "")


# --- Петля обучения на ПРАВКАХ владельца (token-независимо: учимся на редактуре, не на метриках) ---
RECORD_THREADS_LESSON_TOOL = {
    "name": "record_threads_lesson",
    "description": "Усвоить УРОК из правки владельца — добавить в файл уроков ЭТОГО формата Threads "
                   "(он грузится тебе к каждому прогону формата; уроки соседних форматов и ТГ живут "
                   "отдельно). Только устойчивые переносимые правила, не разовую косметику; один вызов "
                   "— один урок. ПЕРЕД записью сверься: правило уже в мануале/эталонах/уроках — НЕ "
                   "дублируй. После записи отчитайся.",
    "input_schema": {
        "type": "object",
        "properties": {
            "lesson": {"type": "string", "description": "устойчивое правило на будущее, одной фразой"},
            "evidence": {"type": "string", "description": "что в правке навело (коротко, необязательно)"},
        },
        "required": ["lesson"],
    },
}


def _record_lesson(kind: str, lesson: str, evidence: str = "") -> str:
    """Дописать урок в файл уроков СВОЕГО формата с простым анти-дублем (не пишем, если уже есть)."""
    lesson = (lesson or "").strip()
    if not lesson:
        return "пустой урок — не записал"
    path = config.ROOT / spec(kind)["lessons"]
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if lesson.lower() in existing.lower():
            return "похоже, такой урок уже есть — не дублирую"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(f"- {lesson}" + (f"  _(повод: {evidence.strip()})_" if evidence.strip() else "") + "\n")
        return f"усвоил: {lesson}"
    except Exception:
        logging.exception("threads_creator: не смог записать урок")
        return "не смог записать урок (см. лог)"


def _dispatcher(kind: str):
    """Диспетчер инструментов, знающий СВОЙ формат — чтобы урок лёг в файл своего свода, не соседнего."""
    def _dispatch(name: str, args: dict) -> str:
        if name == "record_threads_lesson":
            return _record_lesson(kind, args.get("lesson", ""), args.get("evidence", ""))
        return ""
    return _dispatch


def _latest_threads_draft(kind: str) -> str:
    """Текст самого свежего Threads-драфта СВОЕГО формата (для сравнения с финалом владельца)."""
    try:
        k = content_plan.norm_kind(kind)
        files = sorted(THREADS_DRAFTS_DIR.glob(f"*-{k}-*.md"), key=lambda p: -p.stat().st_mtime)
        if not files and k == "flagship":
            # до 09.09.2026 имя файла формат не содержало — это были дистилляции флагмана
            files = sorted((p for p in THREADS_DRAFTS_DIR.glob("*.md") if "-scope-" not in p.name),
                           key=lambda p: -p.stat().st_mtime)
        return files[0].read_text(encoding="utf-8") if files else ""
    except Exception:
        logging.warning("Не смог прочитать последний Threads-драфт для сравнения", exc_info=True)
        return ""


FEEDBACK = (
    "ОБУЧЕНИЕ НА ПРАВКЕ (Threads · {label}). Владелец прислал свой ФИНАЛЬНЫЙ отредактированный "
    "вариант. 1) Сравни свой драфт ↔ финал: что владелец вырезал/добавил/переформулировал, "
    "как сдвинул нарезку/длину/тон/крючок/концовку/число постов. 2) Выдели УСТОЙЧИВЫЕ переносимые правила "
    "(а не разовую косметику под эту тему) и запиши КАЖДОЕ через record_threads_lesson (один вызов — один "
    "урок), при возможности с коротким evidence. Правило, которое уже в мануале/эталонах — НЕ дублируй. "
    "3) Отчитайся 2-4 строки «усвоил: …» — что изменю в будущих постах этого формата. Правок мало / "
    "косметика — так и скажи, урок не плоди ради записи.\n\nТВОЙ ДРАФТ:\n{draft}\n\nФИНАЛ ВЛАДЕЛЬЦА:\n{final}"
)


def write_feedback(final_text: str, kind: str = "flagship") -> str:
    """Петля обучения формата: сравнить свой вариант с финалом владельца → устойчивые уроки в файл
    уроков ЭТОГО формата. Учимся на ПРАВКАХ (не на метриках) — работает независимо от сбора данных.
    Метрики-петля — отдельно; заводится прогоном refresh_threads (токен Threads живой, не блокер)."""
    final_text = (final_text or "").strip()
    if not final_text:
        return "Пришли отредактированный финал в том же сообщении после команды."
    k = content_plan.norm_kind(kind)
    cfg = config.load_agent(AGENT_NAME)
    key = config.agent_api_key(cfg)
    model = runmode.resolve(THREADS_MODEL, ceiling=THREADS_MODEL)
    draft = _latest_threads_draft(k) or "(своего драфта не нашёл — опирайся на эталоны/мануал при сравнении)"
    cost.set_context("threads")
    # здесь кэш ОСТАВЛЕН: есть инструмент (запись урока) → несколько API-раундов перечитывают систему
    text, _ = llm.reply(model, _system(k), [],
                        FEEDBACK.format(label=spec(k)["label"], draft=draft, final=final_text),
                        [RECORD_THREADS_LESSON_TOOL], _dispatcher(k), key, THREADS_THINKING)
    return text or "(пусто)"
