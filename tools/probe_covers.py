"""ЗАМЕР ОБЛОЖЕК — повторяемая проверка «подходят ли картинки», без боевого прогона.

Зачем. После каждой правки механизма вопрос один: стало лучше или нет. Смотреть кадры по одному
и спорить словами — дорого и ненадёжно. Этот инструмент берёт СВЕЖИЕ сюжеты дня, гоняет по ним
БОЕВУЮ функцию подбора (core.scope_writer._attach_media — ту самую, что работает в прогоне) и
складывает результат в один контактный лист. Владелец открывает лист и выносит вердикт глазами,
как он это делает с готовым постом.

Что НЕ делает: не пишет боевые файлы (SCOPE_COVER и журнал обложек уводятся во временные), не
публикует, не трогает драфты. Из платного — один vision-вызов на сюжет (~$0.03).

Запуск:
    python -m tools.probe_covers            # 6 сюжетов дня
    python -m tools.probe_covers 4          # столько сюжетов
    python -m tools.probe_covers published  # контактный лист 23 ОПУБЛИКОВАННЫХ обложек (эталон)

Смысл двух листов: свой прогон сравнивается не с ощущением, а с тем, что владелец реально
публиковал. Открыл два листа рядом — видно, тот же это канал или нет.
"""
from __future__ import annotations

import collections
import json
import logging
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from connectors.source_media import fetch                      # noqa: E402
from connectors.web_sources import feeds                       # noqa: E402
from core import config, creator_tools, scope_cover_log, scope_writer as sw  # noqa: E402

OUT = ROOT / "data" / "cover_probe"
FEEDS = ["https://www.coindesk.com/arc/outboundfeeds/rss/", "https://www.theblock.co/rss.xml",
         "https://cointelegraph.com/rss", "https://decrypt.co/feed", "https://cryptoslate.com/feed/",
         "https://crypto.news/feed/", "https://coingape.com/feed/", "https://thedefiant.io/api/feed"]
STOP = set("the a an of to in on for and with is are as at by from that this it its will has have "
           "after before over under new says say said not but crypto bitcoin btc price market".split())
TILE_W, COLS = 520, 3


def _headlines() -> list[tuple[str, str]]:
    out = []
    for f in FEEDS:
        got = feeds.fetch_bytes(f, max_bytes=900_000)
        if not got:
            continue
        xml = got[0].decode("utf-8", "replace")
        for ch in re.split(r"<item\b", xml, flags=re.I)[1:]:
            t = re.search(r"<title[^>]*>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</title>", ch, re.S | re.I)
            l = re.search(r"<link[^>]*>\s*(?:<!\[CDATA\[)?(https?://[^<\]\s]+)", ch, re.I)
            if t and l:
                out.append((re.sub(r"<[^>]+>", "", t.group(1)).strip(), l.group(1).strip()))
    return out


def _stories(items, want):
    """Сюжет = ОДНО событие, о котором пишут разные издания: так пул повторяет боевой (Скаут даёт
    3-4 статьи про ОДИН повод).

    Две попытки до этого мерили не механизм, а кластеризацию. Первая группировала по одному общему
    слову и слепила нефть с закрытием Router. Вторая требовала двух общих слов, но частые имена
    (Robinhood, Bitcoin — в каждом втором заголовке дня) склеивали «Ancient Bitcoin Wallet» с
    «AMC fight». Поэтому связываем только по РЕДКИМ словам: тем, что встречаются не чаще чем в
    четверти заголовков. Два общих редких слова — это уже одно событие."""
    def keys(t):
        return {w for w in re.findall(r"[a-z][a-z0-9']{3,}", t.lower()) if w not in STOP}

    df = collections.Counter()
    for t, _ in items:
        df.update(keys(t))
    rare_cap = max(2, len(items) // 4)

    def rare(t):
        return {w for w in keys(t) if df[w] <= rare_cap}

    stories, taken = [], set()
    for t0, l0 in items:
        if l0 in taken:
            continue
        r0 = rare(t0)
        if len(r0) < 2:
            continue
        group, hosts = [(t0, l0)], {l0.split("/")[2]}
        for t, l in items:
            if l in taken or l == l0 or l.split("/")[2] in hosts:
                continue
            if len(r0 & rare(t)) >= 2:
                group.append((t, l))
                hosts.add(l.split("/")[2])
        if len(group) >= 3:
            for _, l in group:
                taken.add(l)
            common = sorted(r0 & rare(group[1][0]))[:2]
            stories.append(("-".join(common) or "story", group[:4]))
        if len(stories) >= want:
            break
    return stories


def _sheet(pairs: list[tuple[pathlib.Path, str]], dest: pathlib.Path, title: str) -> None:
    """Контактный лист: кадры сеткой + подпись под каждым. Один файл — один взгляд."""
    from PIL import Image, ImageDraw
    if not pairs:
        print("нечего собирать в лист")
        return
    rows = (len(pairs) + COLS - 1) // COLS
    th = int(TILE_W * 9 / 16)
    sheet = Image.new("RGB", (TILE_W * COLS, (th + 34) * rows + 40), (24, 24, 27))
    d = ImageDraw.Draw(sheet)
    d.text((14, 14), title, fill=(240, 240, 240))
    for i, (path, cap) in enumerate(pairs):
        try:
            im = Image.open(path).convert("RGB")
        except Exception:
            continue
        im.thumbnail((TILE_W - 12, th - 12))
        x = (i % COLS) * TILE_W + 6
        y = (i // COLS) * (th + 34) + 40
        sheet.paste(im, (x, y))
        d.text((x, y + th - 6), cap[:66], fill=(200, 200, 205))
    sheet.save(dest, "JPEG", quality=88)
    print(f"\nЛИСТ: {dest}")


def published_sheet() -> None:
    """Эталон: 23 обложки, которые владелец реально опубликовал."""
    idx = json.loads((ROOT / "data" / "published_covers" / "index.json").read_text(encoding="utf-8"))
    pairs = [((ROOT / "data" / "published_covers" / r["file"]), f'#{r["id"]} {r["title"][:52]}')
             for r in idx]
    _sheet(pairs, OUT / "SHEET_published.jpg", "ЭТАЛОН — опубликованные обложки канала")


def probe(want: int = 6) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fetch.OUT_DIR = OUT
    # боевые файлы не трогаем
    creator_tools.SCOPE_COVER = OUT / "_probe_cover.txt"
    scope_cover_log.LOG = OUT / "_probe_cover_log.jsonl"
    key = config.agent_api_key(config.load_agent("creator"))
    pairs = []
    for w, links in _stories(_headlines(), want):
        print("=" * 76)
        print(f"СЮЖЕТ «{w}» — {len(links)} статьи:")
        for t, l in links:
            print(f"   · [{l.split('/')[2]}] {t[:66]}")
        out = sw._attach_media([l for _, l in links], "\n".join(t for t, _ in links)[:600], w, key)
        print("  пул:", sw.LAST_POOL_NOTE)
        if not out:
            print(f"  ИТОГ: ОБЛОЖКИ НЕТ | {sw.LAST_COVER_NOTE}")
            continue
        from PIL import Image
        dst = OUT / f"FINAL_{re.sub(r'[^a-z0-9]+', '-', w)[:18]}.jpg"
        shutil.copy(out, dst)
        wpx, hpx = Image.open(dst).size
        print(f"  ИТОГ: {dst.name} ({wpx}x{hpx}) | {sw.LAST_COVER_NOTE}")
        pairs.append((dst, f"{w} · {wpx}x{hpx}"))
    _sheet(pairs, OUT / "SHEET_probe.jpg", "ЗАМЕР — что механизм подобрал сегодня")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="  %(message)s")
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "published":
        published_sheet()
    else:
        probe(int(arg) if arg.isdigit() else 6)
