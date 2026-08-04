"""Разнообразие обложек флагмана — анти-повтор КАДРА (не текста).

Боль (04.08): четыре обложки подряд вышли одним кадром — мужчина по центру спиной, развилка
лево/право, золотые монеты, город на закате. Две причины:
  1) сам шаблон стиля (memory/image_prompt.md) описывал ровно этот кадр в разделах КОМПОЗИЦИЯ
     и ОБЪЕКТЫ — GPT честно исполнял;
  2) у обложек НЕ БЫЛО ПАМЯТИ: каждый вызов уходил в ChatGPT с чистого листа, и модель каждый
     раз сваливалась в свой любимый штамп.

Лечим тем же приёмом, что и повтор тем, — КОДОМ, а не просьбой «будь разнообразнее» в промпте
(урок scope-golden-baseline: над-инженерия промпта ломает качество, чек живёт в коде):
  • банк кадров memory/cover_shots.md — 11 разных схем композиции;
  • журнал data/cover_log.jsonl — что реально было на последних обложках;
  • ротация с вето: предлагаем схемы, которых не было в последние SHOT_WINDOW обложек, и Криейтор
    берёт из них подходящую по смыслу (разнообразие даёт код, уместность — модель);
  • запрет-блок: признаки, залипшие в последних обложках («человек-со-спины», «город-скайлайн»),
    уходят в промпт явным «в этот раз НЕЛЬЗЯ»;
  • обратная связь: после рендера дешёвый Haiku-vision смотрит на ГОТОВУЮ картинку и пишет в
    журнал, что там вышло на самом деле. Без этого шага журнал знал бы только наши намерения —
    и штамп протёк бы снова (GPT мог нарисовать спину даже там, где мы её не просили).

Всё мягко деградирует: нет банка / битый журнал / vision недоступен → обложка всё равно
рисуется, просто без анти-повтора. Картинка — бонус, ронять из-за неё пост нельзя.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from collections import Counter
from datetime import date
from pathlib import Path

from core import config

SHOTS_FILE = config.ROOT / "memory" / "cover_shots.md"      # банк кадров (правит владелец)
LOG_FILE = config.ROOT / "data" / "cover_log.jsonl"          # журнал обложек (data/ = вне git)

SHOT_WINDOW = 3     # ВЕТО: схемы, лежавшие на столе в последние 3 обложки, не предлагаем вовсе
OFFER = 2           # сколько схем-кандидатов даём модели на выбор по смыслу
# Банк обязан быть ≥ OFFER*(SHOT_WINDOW+1) схем, иначе вето некому исполнять и мы скатываемся в
# LRU-добор (см. pick_shots) — то есть в мягкий повтор. Сторож на это стоит в tests/test_cover_variety.
TRAIT_WINDOW = 3    # в каких последних обложках ищем залипшие признаки
TRAIT_HITS = 2      # признак, встретившийся ≥2 раз в этом окне, — залип, идём в запрет
# Кап запрета: если вывалить в промпт всё залипшее разом (на 04.08 это 8 признаков — монеты,
# графики, город, закат…), кадру просто нечем станет говорить о рынке. Берём самое въевшееся,
# штампы вперёд; остальное отвалится само, когда следующие обложки перестанут это повторять.
MAX_FORBID = 6
LOG_KEEP = 60       # больше в журнале не храним (обрезаем при записи) — файл не растёт вечно

VISION_MODEL = "claude-haiku-4-5"   # разбор готовой обложки — самый дешёвый тир, одна картинка
_MAX_VISION_BYTES = 4_000_000       # больше Anthropic режет (см. scope_writer) — тогда просто пропускаем
_IMG_MEDIA_TYPE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}

# ЗАКРЫТЫЙ словарь признаков. Закрытый — чтобы записи разных дней сравнивались между собой:
# свободный текст от vision («парень со спины» / «мужчина сзади») не сматчился бы сам с собой.
TRAITS = {
    # фигура человека
    "человек-со-спины": "человек снят СО СПИНЫ (затылок, спина к зрителю)",
    "человек-лицом": "человек лицом или в три четверти к зрителю",
    "человек-силуэт": "человек тёмным силуэтом против света",
    "только-руки": "в кадре только кисти рук",
    "толпа": "много людей / обезличенная масса",
    "без-людей": "людей в кадре нет вовсе",
    # план и ракурс
    "крупный-план": "макро/крупный план одного предмета",
    "средний-план": "средний план — фигура или предмет по пояс, есть фон",
    "общий-план": "широкий общий план, панорама",
    "вид-сверху": "камера сверху, раскладка на плоскости",
    "изометрия": "изометрия/диорама под углом, как модель",
    # сцена
    "город-скайлайн": "город/небоскрёбы на фоне",
    "природа": "природа: горы, море, поле, небо",
    "интерьер": "сцена внутри помещения",
    "студия-абстракция": "нейтральный фон/студия/абстракция без узнаваемого места",
    "развилка-две-стороны": "композиция «две стороны»: слева одно, справа противоположное",
    # предметы
    "монеты-крипта": "криптомонеты BTC/ETH и стопки монет",
    "золото-слитки": "золотые слитки, драгметалл",
    "деньги-купюры": "бумажные деньги, пачки купюр",
    "графики-стрелки": "графики, свечи, стрелки роста/падения",
    "часы-время": "часы, песочные часы, календарь",
    "весы-баланс": "весы, рычаг, противовес, точка опоры",
    "механизм": "шестерни, трубы, машина, конвейер",
    "экран-интерфейс": "экран, монитор, интерфейс, панель данных",
    "документы": "бумаги, документ, печать, штамп",
    "здание-институция": "здание с колоннами, банк, суд, институция",
    "замок-сейф": "замок, сейф, хранилище, ключ",
    # свет
    "золотой-час": "тёплый закат/рассвет, золотое свечение",
    "дневной-свет": "ровный дневной свет",
    "ночь-неон": "ночь, неон, холодная подсветка",
}

# Признаки-штампы: эти залипают чаще всего, поэтому в запрет идут уже с ОДНОГО повторения
# в окне (не с двух). Проверено на 4 обложках подряд — все четыре несли ровно этот набор.
_STAMP_TRAITS = {"человек-со-спины", "развилка-две-стороны"}


# ---------- банк кадров ----------

_SHOT_HEAD = re.compile(r"^##\s+([a-z0-9\-]+)\s+—\s+(.+?)\s*$", re.M)


def load_shots(path: Path | None = None) -> list[dict]:
    """Разобрать банк кадров в [{slug, title, body}]. Нет файла/битый → пустой список (без анти-повтора)."""
    p = Path(path) if path else SHOTS_FILE
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        logging.info("[cover] банк кадров %s недоступен (%s) — кадр не навязываю", p, type(e).__name__)
        return []
    heads = list(_SHOT_HEAD.finditer(text))
    shots = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[m.end():end].strip()
        if body:
            shots.append({"slug": m.group(1), "title": m.group(2).strip(), "body": body})
    return shots


# ---------- журнал ----------

def recent(n: int = max(SHOT_WINDOW, TRAIT_WINDOW), path: Path | None = None) -> list[dict]:
    """Последние n записей журнала, свежие ПЕРВЫМИ. Битые строки пропускаем молча (файл правят руками)."""
    p = Path(path) if path else LOG_FILE
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
        if len(out) >= n:
            break
    return out


def shots_of(rec: dict) -> list[str]:
    """Схемы записи журнала. Пишем список ПРЕДЛОЖЕННЫХ схем: какую из трёх ChatGPT реально взял,
    мы не знаем (он отвечает картинкой, не текстом), поэтому «отдохнувшими» считаем только те,
    что на столе не лежали. Строгий, но честный критерий — и разнообразие от этого только растёт.
    Старый формат {"shot": "..."} читаем тоже — журнал переживает смену схемы."""
    got = rec.get("shots")
    if isinstance(got, list):
        return [s for s in got if isinstance(s, str) and s]
    one = rec.get("shot")
    return [one] if isinstance(one, str) and one else []


def log_cover(shots: list[str], traits: list[str], title: str = "", path: Path | None = None) -> None:
    """Дописать запись об обложке. Ошибку глотаем: журнал — удобство, а не условие публикации."""
    p = Path(path) if path else LOG_FILE
    rec = {"date": date.today().isoformat(), "shots": list(shots),
           "traits": [t for t in traits if t in TRAITS], "title": title[:120]}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        old = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
        old = [l for l in old if l.strip()][-(LOG_KEEP - 1):]      # не даём файлу расти вечно
        p.write_text("\n".join(old + [json.dumps(rec, ensure_ascii=False)]) + "\n", encoding="utf-8")
    except OSError as e:
        logging.info("[cover] журнал %s не записался (%s)", p, type(e).__name__)


# ---------- ротация и запреты ----------

def pick_shots(shots: list[dict], history: list[dict], offer: int = OFFER,
               window: int = SHOT_WINDOW) -> list[dict]:
    """Выбрать схемы-кандидаты: ВЕТО на всё, что было в последние `window` обложек.

    history — записи журнала, свежие первыми. Сначала жёстко выкидываем схемы из окна (ровно
    твоё «как не в прошлые 3-4 раза»), из остатка берём сперва ни разу не использованные, затем
    самые давние. Если банк мал и после вето не набирается offer — добираем по давности, но
    повтор в этом случае неизбежен: чините банк, а не код (сторож на размер банка есть в тестах).
    Детерминированно, без random — воспроизводимо в тестах и предсказуемо для владельца.
    """
    if not shots:
        return []
    # чем меньше индекс в history, тем свежее использование; не встречался → бесконечно давно
    age = {}
    for i, rec in enumerate(history):
        for slug in shots_of(rec):
            age.setdefault(slug, i)
    order = {s["slug"]: i for i, s in enumerate(shots)}
    by_age = sorted(shots, key=lambda s: (-age.get(s["slug"], 10 ** 6), order[s["slug"]]))
    offer = max(1, offer)
    fresh = [s for s in by_age if age.get(s["slug"], 10 ** 6) >= window]   # вето окна
    if len(fresh) >= offer:
        return fresh[:offer]
    logging.info("[cover] банк кадров мал: после вето осталось %d из %d — добираю по давности",
                 len(fresh), len(shots))
    return (fresh + [s for s in by_age if s not in fresh])[:offer]


def stuck_traits(history: list[dict], window: int = TRAIT_WINDOW, hits: int = TRAIT_HITS,
                 cap: int = MAX_FORBID) -> list[str]:
    """Признаки, залипшие в последних обложках: встретились ≥hits раз в окне (штампы — с одного раза).

    Отдаём не более cap штук, штампы первыми: длинный запрет обедняет кадр сильнее, чем помогает.
    """
    counter: Counter = Counter()
    for rec in history[:window]:
        for t in set(rec.get("traits") or []):
            if t in TRAITS:
                counter[t] += 1
    stuck = [t for t, c in counter.items() if c >= hits or (t in _STAMP_TRAITS and c >= 1)]
    stuck.sort(key=lambda t: (t not in _STAMP_TRAITS, -counter[t], t))
    return stuck[:max(1, cap)] if stuck else []


def build_blocks(shots: list[dict], history: list[dict]) -> tuple[str, str, list[str]]:
    """Собрать два блока для промпта картинки + список slug'ов-кандидатов.

    Возвращает (блок «КАДР В ЭТОТ РАЗ», блок «НЕ ПОВТОРЯТЬ», [slug кандидатов]).
    Пустой банк → пустые блоки: промпт остаётся ровно таким, каким был до этой механики.
    """
    picked = pick_shots(shots, history)
    if not picked:
        return "", "", []
    lines = ["КАДР В ЭТОТ РАЗ (обязательно — это анти-повтор, кадр задаём мы, не ты):",
             f"Ниже {len(picked)} схемы композиции. Выбери ОДНУ — ту, что ближе к смыслу поста, — и построй "
             "кадр строго по ней. Другие схемы не смешивай. Если схема запрещает людей или ракурс — запрет сильнее "
             "любых привычных решений."]
    for s in picked:
        lines.append(f"\n[{s['slug']}] {s['title']}\n{s['body']}")
    shot_block = "\n".join(lines)

    stuck = stuck_traits(history)
    forbid = ""
    if stuck:
        human = "; ".join(TRAITS[t] for t in stuck)
        forbid = ("НЕ ПОВТОРЯТЬ (это уже было на последних обложках — читатель видит один и тот же кадр "
                  f"раз за разом):\n{human}.\nНичего из перечисленного в кадре быть не должно, даже если "
                  "кажется, что теме это идёт. Найди другой способ показать ту же мысль.")
    return shot_block, forbid, [s["slug"] for s in picked]


# ---------- обратная связь: что вышло НА САМОМ ДЕЛЕ ----------

_TRAIT_LIST_FOR_PROMPT = "\n".join(f"- {k}: {v}" for k, v in TRAITS.items())


def describe(image_path, api_key: str = "") -> list[str]:
    """Haiku-vision: какие признаки РЕАЛЬНО на готовой обложке. Любая проблема → [] (журнал переживёт).

    Один маленький вызов на пост (max_tokens 200) — копейки, но без него анти-повтор слепой:
    мы знали бы только что ПРОСИЛИ, а не что ChatGPT нарисовал.
    """
    p = Path(image_path)
    try:
        from anthropic import Anthropic, APIError
    except ImportError:
        return []
    try:
        if not p.exists() or p.stat().st_size > _MAX_VISION_BYTES:
            return []
        key = api_key or _api_key()
        if not key:
            return []
        from core import cost, runmode
        media_type = _IMG_MEDIA_TYPE.get(p.suffix.lower(), "image/png")
        b64 = base64.standard_b64encode(p.read_bytes()).decode()
        model = runmode.resolve(VISION_MODEL, ceiling=VISION_MODEL)
        resp = Anthropic(api_key=key).messages.create(
            model=model, max_tokens=200,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text":
                    "Это обложка Telegram-поста. Опиши ЕЁ КАДР метками из списка ниже — что действительно "
                    "видно на картинке (заголовок сверху игнорируй, он есть всегда).\n\n"
                    f"{_TRAIT_LIST_FOR_PROMPT}\n\n"
                    "Ответь СТРОГО метками через запятую, без пояснений и без своих формулировок. "
                    "Бери только те, что явно видны (обычно 4–8 штук)."},
            ]}],
        )
        cost.record(model, resp.usage)  # cost-дисциплина: считаем и этот вызов
        ans = "".join(b.text for b in resp.content if b.type == "text")
        got = [t.strip().lower() for t in re.split(r"[,\n]", ans)]
        return [t for t in dict.fromkeys(got) if t in TRAITS]
    except APIError as e:      # транзиентно (429/5xx/таймаут) — без трейсбека
        logging.warning("[cover] vision-разбор недоступен (%s) — запишу обложку без признаков", type(e).__name__)
        return []
    except (OSError, ValueError) as e:
        logging.warning("[cover] vision-разбор: картинка/ответ битые (%s)", type(e).__name__)
        return []
    except Exception:          # неожиданное = вероятный баг: громко, но пост не роняем
        logging.exception("[cover] vision-разбор: неожиданная ошибка")
        return []


def _api_key() -> str:
    """Ключ Криейтора (свой или общий). Нет ключа — не беда: vision просто не поедет."""
    try:
        return config.agent_api_key(config.load_agent("creator"))
    except Exception:
        try:
            return config.get_optional("ANTHROPIC_API_KEY")
        except Exception:
            return ""
