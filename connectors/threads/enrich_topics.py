"""Обогащение постов Threads: заголовок + тема + суть (через Claude).

Полный аналог telegram_export/enrich_topics.py, но по data/threads_posts.json →
data/threads_topics.json. Даёт аналитику колонки «Заголовок / Тема / Суть», без которых
не сгруппировать «что заходит» по темам, как в ТГ.

Идемпотентно: обрабатывает только НОВЫЕ посты (которых ещё нет в файле) — дёшево гонять
для свежих. Модель — Haiku (классификация/заголовки дёшевы и достаточны).

Запуск:
    python -m connectors.threads.enrich_topics          # только новые
    python -m connectors.threads.enrich_topics --all    # пересчитать всё
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from anthropic import Anthropic

from core import config

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
POSTS_JSON = DATA / "threads_posts.json"
OUT = DATA / "threads_topics.json"

MODEL = "claude-haiku-4-5"
BATCH = 12
MAX_TEXT = 600
OUT_TOKENS = 4096

PROMPT = """Ты — аналитик Threads-аккаунта про крипту (@kanaki.crypto).
Для КАЖДОГО поста ниже дай:
- "id": строка (как во входе, дословно)
- "title": короткий заголовок поста, 3-7 слов, по-русски, по сути
- "theme": тема-тег, 1-3 слова, ЕДИНООБРАЗНО между постами (например: "DeFi", \
"Безопасность", "Личное", "Обучение", "Новости рынка", "Кошельки", "Биржи", "Психология"). \
Старайся переиспользовать одни и те же теги для похожих постов.
- "summary": суть поста одной короткой фразой.

Верни ТОЛЬКО валидный JSON-массив объектов, без пояснений и без markdown.
Посты:
{posts}"""


def _client() -> Anthropic:
    key = config.get_optional("ANALYST_ANTHROPIC_KEY") or config.get_secret("ANTHROPIC_API_KEY")
    return Anthropic(api_key=key)


def _load_posts() -> list[dict]:
    if not POSTS_JSON.exists():
        raise SystemExit("Нет data/threads_posts.json — сначала: python -m connectors.threads.collect")
    return json.loads(POSTS_JSON.read_text(encoding="utf-8"))


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
    print(f"Обогащаю {len(todo)} постов Threads (батчами по {BATCH}, модель {MODEL})...")
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
