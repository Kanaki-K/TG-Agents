"""Откуда Threads-ветка берёт ИСХОДНЫЙ ТГ-пост: журнал вышедших или прямо выгрузка канала.

Два источника, оба — уже ОПУБЛИКОВАННЫЙ текст, никаких черновиков:

1. **Журнал вышедших** (`published_journal`) — штатный путь: `run_pipeline` пишет туда пост
   в момент постановки в отложку, с меткой формата. Так работает боевой прогон.
2. **Выгрузка канала** (`data/channel_posts.json` + разметка форматов `post_formats.json`) —
   путь ОБКАТКИ: взять СТАРЫЙ пост, который вышел до того, как журнал завели. Ради него и
   сделан модуль: прогнать Threads-ветку на живом материале канала, не дожидаясь новых постов.

ЖУРНАЛ СВЕРЯЕТСЯ С КАНАЛОМ (решение владельца 11.09.2026). Журнал пишется при постановке в отложку и
о дальнейшем не знает: ТГ-скоуп прогнали дважды — в журнале два поста, а в отложке админ оставил один.
Раньше Threads брал просто последнюю запись, и удалённый пост уехал бы в Threads. Теперь запись идёт в
работу, только если её пост ЕСТЬ в канале (в отложке или уже в ленте); удалённый пропускается с
объяснением, берётся следующий. Узнаём пост тремя способами:
  • по НОМЕРУ сообщения в отложке — он сохраняется при постановке, правка текста его не меняет. Но номер
    засчитываем не вслепую: канал должен быть тот же, а пост — стоять на назначенном времени ИЛИ совпадать
    по тексту хотя бы на TIME_MATCH (номера живут внутри канала; сменил PUBLISH_CHANNEL — №12 уже чужой);
  • по ТЕКСТУ — доля слов записи, найденных в сообщении. Замер 11.09 на двух скоупах про ETF: правка
    пяти слов даёт 97%, близнец на ту же тему — 25-27%. Каждое сообщение отдаём ОДНОЙ, самой похожей
    записи, иначе удалённый пост «узнал бы себя» в оставшемся близнеце;
  • по ВРЕМЕНИ — вышедшему посту Telegram даёт новый номер, но выходит он в назначенное время.
Пост, переписанный до неузнаваемости, не угадываем: это уже вне завода — админ делает Threads-версию
руками или прогоняет ТГ-формат заново. Канал не прочитался (нет сети/сессии) — берём последнюю запись,
как раньше, и прямо об этом говорим.

Формат поста в выгрузке размечен Аналитиком («флагман» / «короткий» / «личный»…). Если разметки
для поста нет — падаем на длину (флагман длинный), это та же грубая эвристика, что в content_plan.
Наружу оба источника отдают ОДИНАКОВЫЙ словарь: date / kind / theme / text / origin — чтобы
дистиллятору было всё равно, откуда пришёл материал.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from core import config, content_plan, io_safe, published_journal, threads_distill_journal

POSTS_JSON = config.ROOT / "data" / "channel_posts.json"
FORMATS_JSON = config.ROOT / "data" / "post_formats.json"
TOPICS_JSON = config.ROOT / "data" / "post_topics.json"

# Разметку форматов ведёт Аналитик, и она ОТСТАЁТ (последняя правка — июнь): у свежих постов тега
# просто нет, а у старых он исторический. Поэтому тег используем только как ФИЛЬТР «наш ли это
# контент», а формат определяем ДЛИНОЙ — тем же порогом, что и весь завод (content_plan.infer_kind).
NOT_OUR_CONTENT = {"служебное", "медиа", "личный", "психология", "обучающий"}
MIN_CHARS = 300      # короче — футер-сообщение, анонс, реплика; исходником для треда быть не может

LOOKBACK = 10                        # сколько последних записей формата сверяем с каналом
TEXT_MATCH = 0.6                     # доля слов записи в сообщении, чтобы узнать пост по тексту
# Порог мягче, когда сообщение вышло ровно в назначенное время. Не ниже 0.5: слот фиксирован (16:00 дня
# плана), и в освободившийся слот встаёт ЗАМЕНА удалённого поста на ту же тему — совпадение 35-55%
# (ревью 11.09.2026). Разные посты журнала между собой — не выше 28%.
TIME_MATCH = 0.5
TIME_WINDOW = timedelta(minutes=15)
RECENT_POSTS = 60                    # сколько вышедших постов ленты смотрим
_LABEL = {"scope": "скоуп", "flagship": "флагман"}


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


def _words(text: str) -> set[str]:
    """Слова для сравнения журнала с каналом. В Telegram нет ни **жирного**, ни [подписи](ссылки) — только
    видимый текст, поэтому разметку снимаем, а короткие служебные слова не считаем."""
    t = (text or "").lower().replace("ё", "е")
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", " ", t)
    return {w for w in re.findall(r"[a-zа-я0-9]+", t) if len(w) >= 4 or w.isdigit()}


def _overlap(entry_words: set[str], msg_words: set[str]) -> float:
    return len(entry_words & msg_words) / len(entry_words) if entry_words else 0.0


def _moment(iso: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _title(entry: dict) -> str:
    """Имя записи для отчёта — строка заголовка. Тема не годится: у близнецов она одна и та же."""
    lines = [ln.strip() for ln in (entry.get("text") or "").splitlines() if ln.strip()]
    head = next((ln for ln in lines if ln.startswith("**")), lines[0] if lines else "")
    head = head.strip("*").strip()
    return f"«{head[:70]}»" if head else "«(без заголовка)»"


def _clean(text: str) -> str:
    """Срезать реплику модели перед заголовком поста. Запись 11.09 начинается с «Линтер чистый. Выдаю.»:
    журнал тогда писал ответ модели, а не отправленный текст. С 11.09 пишется отправленный, но старые
    записи остаются — чистим при чтении. Режем ТОЛЬКО короткий кусок перед первой строкой-заголовком
    **…** в начале: остальные 21 запись журнала с такой строки и начинаются, так что пост не пострадает."""
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines[:6]):
        if ln.strip().startswith("**"):
            head = "\n".join(lines[:i]).strip()
            return "\n".join(lines[i:]).strip() if head and len(head) <= 200 else (text or "")
    return text or ""


def _id_trusted(entry: dict, msg: dict, score: float, channel: str) -> bool:
    """Засчитать совпадение номера сообщения? Номера отложки живут внутри канала, поэтому канал обязан
    совпасть, а пост — подтвердиться ещё чем-то: стоит на назначенном времени (правили текст, но не
    переносили) или текст совпал хотя бы на TIME_MATCH (перенесли, но правили умеренно)."""
    ch = (entry.get("tg_channel") or "").strip()
    if ch and channel and ch != channel:
        return False
    at, t = _moment(entry.get("tg_scheduled_at") or ""), _moment(msg.get("date") or "")
    return bool(at and t and abs(t - at) <= TIME_WINDOW) or score >= TIME_MATCH


def pick_live(entries: list[dict], snap: dict, channel: str = "") -> tuple[dict | None, str, list[dict]]:
    """Первая (самая свежая) запись журнала, чей пост есть в канале.

    entries — свежие первыми; snap — {'scheduled': [...], 'recent': [...]} из channel_snapshot; channel —
    канал, из которого снят snap (для сверки с tg_channel записи).
    Возвращает (запись или None, как её узнали, пропущенные записи — те, что свежее найденной)."""
    msgs = ([dict(m, where="в отложке") for m in snap.get("scheduled") or []]
            + [dict(m, where="в ленте") for m in snap.get("recent") or []])
    ew = [_words(e.get("text")) for e in entries]
    by_id: dict = {}
    for j, e in enumerate(entries):
        if e.get("tg_msg_id") is not None:
            by_id.setdefault(e["tg_msg_id"], j)       # номер повторился — он у самой свежей записи
    owner: dict[int, tuple[int, float, bool]] = {}    # сообщение → (запись, сходство, узнано по номеру)
    for i, m in enumerate(msgs):
        mw = _words(m.get("text"))
        scores = [_overlap(w, mw) for w in ew]
        j = by_id.get(m.get("id")) if m["where"] == "в отложке" else None
        if j is not None and _id_trusted(entries[j], m, scores[j], channel):
            owner[i] = (j, scores[j], True)           # подтверждённый номер сильнее любого сходства слов
            continue
        if scores:
            best = max(range(len(scores)), key=scores.__getitem__)
            owner[i] = (best, scores[best], False)
    skipped: list[dict] = []
    for j, e in enumerate(entries):
        mine = [(msgs[i], s) for i, (k, s, _) in owner.items() if k == j]
        if any(k == j and by_num for k, _, by_num in owner.values()):
            return e, "в отложке канала, узнал по номеру сообщения", skipped
        best = max(mine, key=lambda x: x[1], default=None)
        if best and best[1] >= TEXT_MATCH:
            return e, f"{best[0]['where']} канала, узнал по тексту (совпало {best[1]:.0%} слов)", skipped
        at = _moment(e.get("tg_scheduled_at") or "")
        for m, s in mine:
            t = _moment(m.get("date") or "")
            if at and t and m["where"] == "в ленте" and abs(t - at) <= TIME_WINDOW and s >= TIME_MATCH:
                return e, f"вышел в канал в назначенное время (текст совпал на {s:.0%})", skipped
        skipped.append(e)
    return None, "", skipped


def _absent_reason(entry: dict, snap: dict) -> str:
    """Почему запись пропущена. Лента читается не вся (RECENT_POSTS): пост старше окна мог выйти и лежать
    глубже — называть его «удалённым» было бы враньём (ревью 11.09.2026)."""
    recent = snap.get("recent") or []
    dates = sorted((m.get("date") or "")[:10] for m in recent if m.get("date"))
    if len(recent) >= RECENT_POSTS and dates and (entry.get("date") or "") < dates[0]:
        return f"старше последних {RECENT_POSTS} сообщений канала, проверить не могу"
    return "в канале нет (удалён или переписан до неузнаваемости)"


def _distilled_on(entry: dict) -> str:
    """Когда этот ТГ-пост уже перерабатывали в Threads ('' — не перерабатывали). Ключ — дата и тема записи,
    так их пишет threads_distill_journal (с 11.09.2026 — только серии, поставленные в отложку)."""
    for d in reversed(threads_distill_journal.entries()):
        if d.get("flagship_date") == entry.get("date") and (d.get("theme") or "") == (entry.get("theme") or ""):
            return d.get("created") or "?"
    return ""


def _snapshot(channel: str) -> dict:
    """Отложка + лента канала. Импорт внутри: модулю не нужен Telethon, пока в канал не идём."""
    try:
        from connectors.telegram_publish import publish as tg_publish
    except Exception as e:  # noqa: BLE001 — нет Telethon = канал не прочитан, а не падение прогона
        return {"ok": False, "error": f"коннектор публикации не загрузился: {e}"}
    return tg_publish.channel_snapshot(channel, recent=RECENT_POSTS)


def resolve(kind: str = "flagship", back: int = 0) -> dict | None:
    """Материал для Threads-ветки: back=0 — журнал вышедших, сверенный с каналом; back≥1 — из выгрузки канала.

    Разделение намеренное: боевой прогон работает с журналом (он пишется тем же прогоном, что
    поставил пост в отложку), а обкатка — с историей канала, где лежат сотни живых постов.
    Пустой text + why — брать нечего и почему; skipped — какие записи отброшены сверкой (для отчёта)."""
    if back and back > 0:
        return from_channel(kind, back)
    k = content_plan.norm_kind(kind)
    rows = [dict(e, text=_clean(e.get("text") or "")) for e in published_journal.entries(k)[-LOOKBACK:][::-1]]
    if not rows:
        return None
    channel = (config.get_optional("PUBLISH_CHANNEL") or "").strip()
    snap = _snapshot(channel) if channel else {"ok": False, "error": "PUBLISH_CHANNEL не задан"}
    if not snap.get("ok"):
        entry = dict(rows[0])
        entry["unverified"] = snap.get("error") or "?"
        entry["origin"] = (f"журнал вышедших постов — ⚠️ канал не проверил ({entry['unverified']}), "
                           "взял последний пост журнала")
        return entry
    picked, how, skipped = pick_live(rows, snap, channel)
    notes = [f"{_title(e)} от {e.get('date', '?')} — {_absent_reason(e, snap)}" for e in skipped]
    label = _LABEL.get(k, k)
    done = _distilled_on(picked) if picked else ""
    if done and skipped:
        # Свежие удалены, а следующий по старшинству уже переработан: взять его — выпустить в Threads второй
        # тред на старую тему. Откат по журналу существует ради «админ удалил лишний», а не ради повторов.
        return {"text": "", "skipped": notes,
                "why": (f"свежих постов формата «{label}» в канале нет, а оставшийся {_title(picked)} от "
                        f"{picked.get('date', '?')} уже перерабатывали в Threads {done}. Повтор не делаю: "
                        f"прогони ТГ-{label} заново за новым постом.")}
    if not picked:
        return {"text": "", "skipped": notes,
                "why": (f"ни один из последних {len(rows)} постов формата «{label}» из журнала не нашёлся в "
                        f"ТГ-канале — перерабатывать нечего. Это вне завода: сделай Threads-версию руками "
                        f"или прогони ТГ-{label} заново за новым постом.")}
    entry = dict(picked)
    entry["origin"] = f"журнал вышедших постов, {how}"
    entry["skipped"] = notes
    entry["repeat"] = done          # непусто — этот пост уже перерабатывали: пайплайн предупредит
    return entry
