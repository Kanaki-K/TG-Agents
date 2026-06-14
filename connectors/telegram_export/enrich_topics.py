"""Обогащение постов: заголовок + тема + суть (через Claude).

Для каждого поста из data/channel_posts.json генерирует:
  - title   — короткий заголовок (о чём пост, 3-7 слов)
  - theme   — тема-тег (1-3 слова, единообразно — чтобы ловить повторы)
  - summary — суть одной фразой (для сравнения с будущим контентом)

Результат — data/post_topics.json (словарь id → {...}). Идемпотентно:
повторный запуск обрабатывает только НОВЫЕ посты (которых ещё нет в файле).
Так это дёшево гонять регулярно для свежих постов.

Запуск:
    python -m connectors.telegram_export.enrich_topics          # только новые
    python -m connectors.telegram_export.enrich_topics --all    # пересчитать всё
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from anthropic import Anthropic

from core import config

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
POSTS_JSON = DATA / "channel_posts.json"
OUT = DATA / "post_topics.json"

MODEL = "claude-haiku-4-5"   # классификация/заголовки — дёшево и достаточно
BATCH = 12                   # меньше батч → ответ не упирается в лимит токенов
MAX_TEXT = 600
OUT_TOKENS = 4096

PROMPT = """Ты — аналитик Telegram-канала про крипту (KANAKI CRYPTO).
Для КАЖДОГО поста ниже дай:
- "id": число (как во входе)
- "title": короткий заголовок поста, 3-7 слов, по-русски, по сути
- "theme": тема-тег, 1-3 слова, ЕДИНООБРАЗНО между постами (например: "DeFi", \
"Безопасность", "Личное", "Обучение", "Новости рынка", "Кошельки", "Биржи", "Психология"). \
Старайся переиспользовать одни и те же теги для похожих постов.
- "summary": суть поста одной короткой фразой.

Верни ТОЛЬКО валидный JSON-массив объектов, без пояснений и без markdown.
Посты:
{posts}"""


def _client() -> Anthropic:
    # ключ аналитика, если задан, иначе общий
    key = config.get_optional("ANALYST_ANTHROPIC_KEY") or config.get_secret("ANTHROPIC_API_KEY")
    return Anthropic(api_key=key)


def _load_posts() -> list[dict]:
    raw = json.loads(POSTS_JSON.read_text(encoding="utf-8"))
    return [p for p in raw if p.get("views") is not None]  # без служебных


def _parse_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _enrich_batch(client: Anthropic, batch: list[dict]) -> list[dict]:
    lines = []
    for p in batch:
        txt = (p.get("text") or "").strip().replace("\n", " ")[:MAX_TEXT]
        if not txt:
            txt = "(пост без текста, только медиа)"
        lines.append(f'- id={p["id"]}: {txt}')
    msg = client.messages.create(
        model=MODEL,
        max_tokens=OUT_TOKENS,
        messages=[{"role": "user", "content": PROMPT.format(posts="\n".join(lines))}],
    )
    out = "".join(b.text for b in msg.content if b.type == "text")
    return _parse_json(out)


def main() -> None:
    redo_all = "--all" in sys.argv
    posts = _load_posts()
    done = {} if redo_all else (json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {})
    todo = [p for p in posts if str(p["id"]) not in done]
    if not todo:
        print(f"Все {len(posts)} постов уже обогащены → {OUT}")
        return
    print(f"Обогащаю {len(todo)} постов (батчами по {BATCH}, модель {MODEL})...")
    client = _client()
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        try:
            for item in _enrich_batch(client, batch):
                done[str(item["id"])] = {
                    "title": item.get("title", "").strip(),
                    "theme": item.get("theme", "").strip(),
                    "summary": item.get("summary", "").strip(),
                }
        except Exception as e:  # noqa: BLE001 — не теряем уже сделанное
            print(f"  батч {i//BATCH+1}: ошибка {type(e).__name__}: {e}")
            continue
        OUT.write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  обработано {min(i+BATCH, len(todo))}/{len(todo)}")
    print(f"Готово. Тем/заголовков в файле: {len(done)} → {OUT}")


if __name__ == "__main__":
    main()
