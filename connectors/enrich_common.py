"""Общий каркас обогащения постов (заголовок/тема/КАТЕГОРИЯ/угол/суть через Haiku).

ОДИН код для Telegram-канала и Threads — чтобы не дрейфовать (N-49: две почти одинаковые копии
уже разошлись — guard в одной, голый json.loads в другой). Специфика площадки — параметрами:
своя преамбула промпта, свой список постов (площадка фильтрует по-своему), свой out-файл.
Таксономия (7 категорий + углы) — из topic_category/post_angle, единый источник.
"""
from __future__ import annotations

import json

from anthropic import Anthropic

from core import config, io_safe, post_angle, topic_category

MODEL = "claude-haiku-4-5"   # классификация/заголовки — дёшево и достаточно
BATCH = 12                   # меньше батч → ответ не упирается в лимит токенов
MAX_TEXT = 600
OUT_TOKENS = 4096

_CATS = "\n".join(f'    "{s}" — {topic_category.label(s)}' for s in topic_category.all_slugs())
_ANGLES = "\n".join(f'    "{s}" — {post_angle.label(s)}' for s in post_angle.all_slugs())

# Тело промпта (после преамбулы площадки). id «дословно» — работает и для int (ТГ), и для str (Threads).
_FIELDS = """Для КАЖДОГО поста ниже дай:
- "id": как во входе, дословно
- "title": короткий заголовок поста, 3-7 слов, по-русски, по сути
- "theme": тема-тег, 1-3 слова, ЕДИНООБРАЗНО между постами (например: "DeFi", "Безопасность", \
"Личное", "Обучение", "Новости рынка", "Кошельки", "Биржи", "Психология"). Переиспользуй одни теги.
- "category": РОВНО один slug-разряд из списка (для само-обучения канала):
{cats}
  Личное/бытовое/не про крипту → "личное". Крипта, но ни в один разряд → "прочее".
- "angle": РОВНО один slug ПОДАЧИ (как подано, не про что):
{angles}
  Ни один явно → "прочее".
- "summary": суть поста одной короткой фразой.

Верни ТОЛЬКО валидный JSON-массив объектов, без пояснений и без markdown.
Посты:
{posts}"""


def _client() -> Anthropic:
    key = config.get_optional("ANALYST_ANTHROPIC_KEY") or config.get_secret("ANTHROPIC_API_KEY")
    return Anthropic(api_key=key)


def _parse_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _enrich_batch(client: Anthropic, batch: list[dict], preamble: str) -> list[dict]:
    lines = []
    for p in batch:
        txt = (p.get("text") or "").strip().replace("\n", " ")[:MAX_TEXT] or "(пост без текста, только медиа)"
        lines.append(f'- id={p["id"]}: {txt}')
    content = preamble + "\n" + _FIELDS.format(cats=_CATS, angles=_ANGLES, posts="\n".join(lines))
    msg = client.messages.create(model=MODEL, max_tokens=OUT_TOKENS,
                                 messages=[{"role": "user", "content": content}])
    out = "".join(b.text for b in msg.content if b.type == "text")
    return _parse_json(out)


def run(posts: list[dict], out_path, preamble: str, redo_all: bool) -> None:
    """Обогатить posts → out_path (id → {title/theme/category/angle/summary}). Идемпотентно:
    без --all трогает только новые. preamble — «Ты — аналитик <площадки>…». posts грузит вызывающий."""
    done = {} if redo_all else io_safe.load_json(out_path, {})
    todo = [p for p in posts if str(p["id"]) not in done]
    if not todo:
        print(f"Все {len(posts)} постов уже обогащены → {out_path}")
        return
    print(f"Обогащаю {len(todo)} постов (батчами по {BATCH}, модель {MODEL})...")
    client = _client()
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        try:
            for item in _enrich_batch(client, batch, preamble):
                done[str(item["id"])] = {
                    "title": item.get("title", "").strip(),
                    "theme": item.get("theme", "").strip(),
                    "category": item.get("category", "").strip(),   # разряд банка (общий с обеими площадками)
                    "angle": item.get("angle", "").strip(),          # подача (второй объектив)
                    "summary": item.get("summary", "").strip(),
                }
        except Exception as e:  # noqa: BLE001 — не теряем уже сделанное
            print(f"  батч {i // BATCH + 1}: ошибка {type(e).__name__}: {e}")
            continue
        out_path.write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  обработано {min(i + BATCH, len(todo))}/{len(todo)}")
    print(f"Готово. Тем/заголовков в файле: {len(done)} → {out_path}")
