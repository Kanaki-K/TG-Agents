"""Выгрузка ОБЛОЖЕК опубликованных 🔭-скоупов — материал для критериев отбора картинки.

Зачем. Правила выбора обложки скоупа до сих пор писались из головы: запрещали то, что уже испортило
конкретный пост (ИИ-рендер 26.08, ИИ-инфографика 28.08). Владелец 28.08: «на канале очень много
скоупов, есть на что ориентироваться — проанализируй картинки, вот тебе и будут характеристики».
Это верный ход: критерий, выведенный из ПРИНЯТЫХ обложек, описывает, что брать, а не только что не
брать. Но картинок нет ни в выгрузке канала (там только `has_media: true`), ни на диске — они лежат
в Telegram. Забрать их может только машина владельца: у неё сессия MTProto и сеть.

Что делает: проходит по выгрузке `data/channel_posts.json`, отбирает похожие на скоуп посты
(короткие, с футером, не флагманы) с медиа и скачивает их фото в `data/published_covers/`.
Имя файла — `<id>_<дата>.jpg`, рядом `index.json` с id/датой/заголовком, чтобы кадр читался вместе
с его постом.

Запуск (там же, где обычный сбор канала):
    python -m connectors.telegram_export.dump_covers

Только ЧТЕНИЕ своего канала: ничего не публикует, ничего не удаляет, выгрузку постов не трогает.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from telethon.errors import FloodWaitError

from connectors.telegram_export.collect import _client, _find_channel

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
POSTS = DATA / "channel_posts.json"
OUT_DIR = DATA / "published_covers"

SCOPE_MAX_LEN = 1500          # скоуп короткий; флагман заметно длиннее (потолок формата 1350 + запас)
SCOPE_ERA = "2026-06"         # раньше формата 🔭 в нынешнем виде не было — старое только зашумит


def _flagship_ids() -> set[str]:
    """id постов-флагманов из журнала публикаций — их обложки мы рисовали сами, они не образец."""
    out: set[str] = set()
    p = DATA / "published_flagships.jsonl"
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(ln)
        except Exception:
            continue
        pid = row.get("post_id") or row.get("id")
        if pid:
            out.add(str(pid))
    return out


def _scope_like() -> list[dict]:
    """Посты, похожие на 🔭: короткие, с футером, с медиа, не флагманы, эры формата."""
    posts = json.loads(POSTS.read_text(encoding="utf-8"))
    flag = _flagship_ids()
    got = [p for p in posts
           if p.get("has_media")
           and "🖥" in (p.get("text") or "")                  # футер канала (ссылки выгрузка не отдаёт)
           and len(p.get("text") or "") <= SCOPE_MAX_LEN
           and str(p.get("id")) not in flag
           and (p.get("date") or "")[:7] >= SCOPE_ERA]
    return sorted(got, key=lambda p: p.get("date") or "")


async def dump() -> None:
    if not POSTS.exists():
        raise SystemExit("Нет data/channel_posts.json — сперва собери канал: "
                         "python -m connectors.telegram_export.collect collect")
    want = _scope_like()
    if not want:
        raise SystemExit("Подходящих постов не нашлось — проверь выгрузку канала.")
    by_id = {int(p["id"]): p for p in want}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Скачиваю обложки {len(by_id)} постов → {OUT_DIR}")

    client = _client()
    await client.start()
    channel = await _find_channel(client)
    index, saved = [], 0
    # Тянем сообщения ПАЧКОЙ по id — это один заход вместо перебора всей истории.
    for chunk_start in range(0, len(want), 100):
        ids = [int(p["id"]) for p in want[chunk_start:chunk_start + 100]]
        try:
            msgs = await client.get_messages(channel, ids=ids)
        except FloodWaitError as e:
            print(f"Telegram просит подождать {e.seconds}с — жду...")
            await asyncio.sleep(e.seconds + 1)
            msgs = await client.get_messages(channel, ids=ids)
        for m in msgs:
            if m is None or not getattr(m, "photo", None):
                continue
            src = by_id.get(m.id, {})
            day = (src.get("date") or "")[:10]
            path = OUT_DIR / f"{m.id}_{day}.jpg"
            try:
                await client.download_media(m, file=str(path))
            except Exception as e:  # noqa: BLE001 — одна битая картинка не должна ронять выгрузку
                print(f"  #{m.id}: не скачалась ({type(e).__name__})")
                continue
            title = next((l.strip().replace("**", "")
                          for l in (src.get("text") or "").splitlines() if l.strip()), "")
            index.append({"id": m.id, "date": day, "file": path.name, "title": title[:120]})
            saved += 1
            print(f"  ✓ #{m.id} {day} — {title[:60]}")
    (OUT_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2),
                                        encoding="utf-8", newline="\n")
    await client.disconnect()
    print(f"\nГотово: {saved} обложек в {OUT_DIR} (+ index.json с заголовками).")


if __name__ == "__main__":
    asyncio.run(dump())
