"""Цифры из ПРИЛОЖЕНИЯ Threads, которых нет в API: заходы в профиль, зрители, новые читатели.

ПОЧЕМУ ЭТОТ МОДУЛЬ ВООБЩЕ НУЖЕН. Владелец 09.09.2026: «если на каждый пост наводить, то можно
смотреть, там ещё важный параметр — посещения профиля». Он прав, и это ломает наше прежнее
«подписок на пост не существует»: они существуют, их не отдаёт API. Проверено запросами в тот же
день — Meta перечисляет допустимые метрики поста явно (clicks, likes, quotes, replies, reposts,
shares, views) и на уровне аккаунта тоже (плюс followers_count и демография). Ни подписок на пост,
ни заходов в профиль, ни уникальных зрителей там нет. В приложении они есть.

ЧТО ЭТО ДАЁТ. Полную воронку поста, а не её половину:
    зрители (уникальные) → заходы в профиль → новые читатели
Это ровно та цепочка, которой владелец меряет качество: «просмотры растут, лайки больше, комменты
чаще, подписки на финале». Заходы в профиль — недостающее звено между «увидел» и «подписался»: пост
может не собрать ни одного коммента и при этом гнать людей в профиль, и наоборот.

КАК ПОПАДАЮТ ДАННЫЕ. Владелец наводит на пост в приложении и присылает блок как есть — вместе с
текстом поста. Пост опознаём ПО ТЕКСТУ (id в приложении не показывается), поэтому вставлять надо
вместе с текстом. Разбор терпим к языку интерфейса: украинский, русский, английский.

ЧЕСТНОСТЬ. Цифры ручные, поэтому каждая запись помечена источником и датой снятия: метрики поста
растут, и «4 захода в профиль» на второй день жизни поста — не то же самое, что на тридцатый.
Сравнивать посты между собой можно только с оглядкой на возраст на момент снятия.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from core import config, content_plan, io_safe, text_match

STORE = config.ROOT / "data" / "threads_app_metrics.json"
THREADS_POSTS = config.ROOT / "data" / "threads_posts.json"

# Метка «конец текста, дальше цифры»: в приложении это заголовок сводки.
_SUMMARY = re.compile(r"^\s*(Зведення|Сводка|Обзор|Overview|Insights|Статистика)\s*$", re.I | re.M)

# Названия метрик на трёх языках интерфейса → наше поле. Порядок важен: «Відвідування профілю»
# должно проверяться раньше «Перегляди», иначе короткое имя съест длинное.
_LABELS: tuple[tuple[str, str], ...] = (
    ("profile_visits", r"(Відвідування профілю|Посещени[яй] профил[яи]|Profile visits)"),
    ("viewers",        r"(Глядачі|Зрители|Viewers)"),
    ("new_followers",  r"(Нові читачі|Новые (?:читатели|подписчики)|New followers)"),
    ("views",          r"(Перегляди|Просмотры|Views)"),
    ("likes",          r"(Вподобайки|Лайки|Likes)"),
    ("replies",        r"(Відповіді|Ответы|Replies)"),
    ("reposts",        r"(Репости|Репосты|Reposts)"),
)


def _num(s: str) -> int | None:
    """«1 234» / «1,234» / «309» → int. Иначе None (строка сравнения вроде «Як зазвичай»)."""
    t = (s or "").strip().replace(" ", "").replace(" ", "").replace(",", "").replace(".", "")
    return int(t) if t.isdigit() else None


def parse_block(raw: str) -> dict:
    """Один блок из приложения → {текст поста, метрики}. Пустые поля просто отсутствуют.

    В приложении метрика идёт тремя строками: название, число, сравнение («Як зазвичай», «Вище»).
    Поэтому число ищем в ближайших строках ПОСЛЕ названия, а не на той же строке."""
    lines = [ln.strip() for ln in (raw or "").splitlines()]
    cut = _SUMMARY.search(raw or "")
    text = (raw[:cut.start()] if cut else raw or "").strip()
    # шапка приложения: ник и возраст поста («22 год», «3 дн», «2 h») — в текст поста не входят
    tl = [ln for ln in text.splitlines() if ln.strip()]
    while tl and (re.fullmatch(r"[\w.]+", tl[0]) and "." in tl[0]
                  or re.fullmatch(r"\d+\s*(год|годин|дн|день|дня|ч|hours?|h|d|m|хв)\.?", tl[0], re.I)):
        tl.pop(0)
    out: dict = {"text": "\n".join(tl).strip()}
    for field, pattern in _LABELS:
        rx = re.compile(rf"^\s*{pattern}\s*:?\s*(\d[\d\s,.]*)?\s*$", re.I)
        for i, ln in enumerate(lines):
            m = rx.match(ln)
            if not m:
                continue
            v = _num(m.group(2) or "")
            if v is None:                       # число на следующей строке (как в приложении)
                for nxt in lines[i + 1:i + 3]:
                    v = _num(nxt)
                    if v is not None:
                        break
            if v is not None:
                out[field] = v
            break
    return out


# Строки сравнения, которыми приложение подписывает каждую цифру («як зазвичай», «вище»).
_COMPARE = re.compile(r"^\s*(Як зазвичай|Вище|Нижче|Как обычно|Выше|Ниже|Типово|Typical|"
                      r"Above average|Below average|Higher|Lower)\s*$", re.I)


def _is_stats_line(line: str) -> bool:
    """Строка принадлежит блоку цифр (название метрики / число / сравнение), а не тексту поста."""
    t = (line or "").strip()
    if not t or _num(t) is not None or _COMPARE.match(t):
        return True
    return any(re.fullmatch(rf"{pat}\s*:?\s*(\d[\d\s,.]*)?", t, re.I) for _, pat in _LABELS)


def parse(raw: str) -> list[dict]:
    """Несколько блоков, вставленных подряд → список разборов.

    Граница блоков — не метка сводки, а КОНЕЦ её цифр: сразу за ними начинается текст следующего
    поста (в приложении это строка с ником). Делить по самой метке нельзя — тогда текст второго
    поста уезжает в первый блок, а второй остаётся без текста и его не опознать."""
    marks = [m.start() for m in _SUMMARY.finditer(raw or "")]
    if not marks:
        return [parse_block(raw)]
    blocks, text_start = [], 0
    for i, pos in enumerate(marks):
        text = (raw or "")[text_start:pos]
        seg = (raw or "")[pos:(marks[i + 1] if i + 1 < len(marks) else len(raw))]
        lines = seg.splitlines()
        j = 1
        while j < len(lines) and _is_stats_line(lines[j]):
            j += 1
        stats = "\n".join(lines[:j])
        blocks.append(parse_block(text + "\n" + stats))
        text_start = pos + len(stats) + 1
    return blocks


def match_post(text: str, min_coverage: float = 0.5) -> dict | None:
    """Найти пост Threads по тексту из приложения. None — не опознан (лучше молчать, чем угадать)."""
    best, best_cov = None, 0.0
    for p in io_safe.load_json(THREADS_POSTS, []):
        cov = text_match.coverage(text, p.get("text") or "")
        if cov > best_cov:
            best, best_cov = p, cov
    return best if (best and best_cov >= min_coverage) else None


def save(post_id: str, metrics: dict, post_date: str = "") -> None:
    """Записать ручные метрики поста. Возраст на момент снятия фиксируем — цифры растут со временем."""
    store = io_safe.load_json(STORE, {})
    row = {k: v for k, v in metrics.items() if k != "text"}
    row["snapped_at"] = datetime.now(content_plan.tz()).isoformat(timespec="seconds")
    row["source"] = "приложение (руками)"
    if post_date:
        try:
            age = (datetime.now(content_plan.tz()).date()
                   - datetime.fromisoformat(post_date[:10]).date()).days
            row["age_days_at_snap"] = age
        except ValueError:
            pass
    store[str(post_id)] = row
    STORE.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def ingest(raw: str) -> str:
    """Разобрать вставку из приложения, привязать к постам и сохранить. Возвращает отчёт для чата."""
    lines = []
    for block in parse(raw):
        nums = {k: v for k, v in block.items() if k != "text"}
        if not nums:
            continue
        post = match_post(block.get("text", ""))
        if not post:
            lines.append(f"❓ Не опознал пост: «{' '.join(block.get('text','').split())[:50]}» — "
                         "нужен текст поста вместе с цифрами")
            continue
        save(post["id"], nums, post.get("date", ""))
        head = " ".join((post.get("text") or "").split())[:44]
        lines.append(f"✅ {post.get('date','')[:10]} «{head}» ← " +
                     " · ".join(f"{k} {v}" for k, v in nums.items()))
    return "\n".join(lines) or "Ничего не разобрал: нужен блок из приложения вместе с текстом поста."


def known() -> dict[str, dict]:
    return io_safe.load_json(STORE, {})


def funnel_report() -> str:
    """Воронка по постам, для которых цифры из приложения уже есть."""
    data = known()
    if not data:
        return ("📱 Ручных метрик из приложения пока нет. Наведи на пост в Threads → пришли блок "
                "«Зведення» вместе с текстом поста, я разберу и привяжу.")
    posts = {str(p["id"]): p for p in io_safe.load_json(THREADS_POSTS, [])}
    rows = []
    for pid, m in data.items():
        p = posts.get(pid, {})
        rows.append((p.get("date", "")[:10], m, p))
    rows.sort(key=lambda r: r[0])
    out = [f"📱 Воронка из приложения: {len(rows)} пост(ов) с ручными цифрами",
           "   дата       зрители  профиль  подписки  из зрителей в профиль  из профиля в подписку"]
    for d, m, p in rows:
        vw, pv, nf = m.get("viewers"), m.get("profile_visits"), m.get("new_followers")
        r1 = f"{100 * pv / vw:.1f}%" if (vw and pv is not None) else "—"
        r2 = f"{100 * nf / pv:.0f}%" if (pv and nf is not None) else "—"
        out.append(f"   {d}  {str(vw or '—'):>7}  {str(pv or '—'):>7}  {str(nf or '—'):>8}  "
                   f"{r1:>21}  {r2:>21}")
    return "\n".join(out)


if __name__ == "__main__":
    import sys

    raw = sys.stdin.read()
    print(ingest(raw) if raw.strip() else funnel_report())
