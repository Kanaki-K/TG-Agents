"""Откуда Threads-ветка берёт ИСХОДНЫЙ ТГ-пост: журнал вышедших или прямо выгрузка канала.

Два источника, оба — уже ОПУБЛИКОВАННЫЙ текст, никаких черновиков:

1. **Журнал вышедших** (`published_journal`) — штатный путь: `run_pipeline` пишет туда пост
   в момент постановки в отложку, с меткой формата. Так работает боевой прогон.
2. **Выгрузка канала** (`data/channel_posts.json` + разметка форматов `post_formats.json`) —
   путь ОБКАТКИ: взять СТАРЫЙ пост, который вышел до того, как журнал завели. Ради него и
   сделан модуль: прогнать Threads-ветку на живом материале канала, не дожидаясь новых постов.

Формат поста в выгрузке размечен Аналитиком («флагман» / «короткий» / «личный»…). Если разметки
для поста нет — падаем на длину (флагман длинный), это та же грубая эвристика, что в content_plan.
Наружу оба источника отдают ОДИНАКОВЫЙ словарь: date / kind / theme / text / origin — чтобы
дистиллятору было всё равно, откуда пришёл материал.
"""
from __future__ import annotations

from core import config, content_plan, io_safe, published_journal

POSTS_JSON = config.ROOT / "data" / "channel_posts.json"
FORMATS_JSON = config.ROOT / "data" / "post_formats.json"
TOPICS_JSON = config.ROOT / "data" / "post_topics.json"

# Разметку форматов ведёт Аналитик, и она ОТСТАЁТ (последняя правка — июнь): у свежих постов тега
# просто нет, а у старых он исторический. Поэтому тег используем только как ФИЛЬТР «наш ли это
# контент», а формат определяем ДЛИНОЙ — тем же порогом, что и весь завод (content_plan.infer_kind).
NOT_OUR_CONTENT = {"служебное", "медиа", "личный", "психология", "обучающий"}
MIN_CHARS = 300      # короче — футер-сообщение, анонс, реплика; исходником для треда быть не может


def _matches(post: dict, kind: str, tag_of: dict) -> bool:
    """Пост из выгрузки принадлежит формату? Тег отсеивает не-наш контент, длина решает формат."""
    text = (post.get("text") or "").strip()
    if len(text) < MIN_CHARS:
        return False
    if (tag_of.get(str(post.get("id"))) or "").strip().lower() in NOT_OUR_CONTENT:
        return False
    # infer_kind отвечает историческим именем формата ('short'), норма — через norm_kind: без этого
    # сравнение с 'scope' молча не совпадало НИКОГДА, и скоупы в выгрузке «не находились».
    return content_plan.norm_kind(content_plan.infer_kind(text)) == kind


def from_channel(kind: str = "flagship", back: int = 1) -> dict | None:
    """N-й С КОНЦА вышедший пост этого формата ИЗ ВЫГРУЗКИ канала (back=1 — самый свежий).

    Для обкатки на старых постах: `--old 3` = «возьми третий с конца скоуп канала»."""
    k = content_plan.norm_kind(kind)
    posts = [p for p in io_safe.load_json(POSTS_JSON, []) if (p.get("text") or "").strip()]
    posts.sort(key=lambda p: (p.get("date") or "", p.get("id") or 0))
    tag_of = io_safe.load_json(FORMATS_JSON, {})
    mine = [p for p in posts if _matches(p, k, tag_of)]
    if not mine or back < 1 or back > len(mine):
        return None
    post = mine[-back]
    topics = io_safe.load_json(TOPICS_JSON, {})
    t = topics.get(str(post.get("id"))) or {}
    theme = (t.get("title") or t.get("theme") or "").strip()
    return {"date": (post.get("date") or "")[:10], "kind": k, "theme": theme,
            "text": (post.get("text") or "").strip(),
            "origin": f"пост канала #{post.get('id')} (выгрузка, {back}-й с конца)"}


def resolve(kind: str = "flagship", back: int = 0) -> dict | None:
    """Материал для Threads-ветки: back=0 — последний из журнала вышедших; back≥1 — из выгрузки канала.

    Разделение намеренное: боевой прогон работает с журналом (он пишется тем же прогоном, что
    поставил пост в отложку), а обкатка — с историей канала, где лежат сотни живых постов."""
    if back and back > 0:
        return from_channel(kind, back)
    entry = published_journal.latest(kind)
    if entry:
        entry = dict(entry)
        entry.setdefault("origin", "журнал вышедших постов")
    return entry
