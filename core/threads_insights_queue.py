"""Очередь постов, по которым ещё нет цифр из интерфейса. Мозг здесь, руки — в PowerShell.

ПОЧЕМУ ОЧЕРЕДЬ, А НЕ «ОБОЙТИ ВСЁ». Владелец просит цифры за 90 дней и одновременно требует
максимальной безопасности. Это не противоречие, если развести ОБЪЁМ и ТЕМП: объём набирается за
несколько недель короткими заходами, а не одним обходом 80 страниц подряд. Обход подряд — ровно
тот след, который отличает робота от человека.

ЧЕГО НЕ ДЕЛАЕМ: не листаем ленту. Общая страница Insights показывает лишь последние ~10 постов,
и чтобы добраться до старых, её пришлось бы прокручивать — то есть имитировать поведение
пользователя. Не нужно: код поста в адресе статистики (/insights/post/<код>) — тот же, что в его
постоянной ссылке, а постоянные ссылки всех постов у нас уже собраны официальным API. Мы просто
знаем адрес заранее.

ПОРЯДОК: свежие вперёд. Метрики поста растут первые дни, и пропустить окно у свежего поста
дороже, чем у трёхмесячного, который уже стоит на месте.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from core import config, io_safe, threads_app_metrics

THREADS_POSTS = config.ROOT / "data" / "threads_posts.json"
QUEUE = config.ROOT / "data" / "threads_insights_queue.txt"
DAYS = 90
_CODE = re.compile(r"/post/([A-Za-z0-9_-]+)")


def code_of(post: dict) -> str:
    """Код поста из постоянной ссылки — он же код в адресе статистики."""
    m = _CODE.search(post.get("permalink") or "")
    return m.group(1) if m else ""


MATURE_DAYS = 14       # после этого срока метрики поста практически не растут


def pending(days: int = DAYS) -> list[dict]:
    """Посты, которые нужно снять: сперва ни разу не меренные, затем меренные СЛИШКОМ РАНО.

    ПОЧЕМУ ДВА ЗАМЕРА, А НЕ ОДИН (владелец 09.09: «некоторые посты живут дольше четырёх дней»).
    Пост добирает просмотры и заходы в профиль примерно две недели. Снимок, сделанный на второй
    день, — это не итог, а промежуточный кадр, и сравнивать по нему посты между собой нельзя:
    свежий проиграет старому просто по возрасту. Поэтому каждый пост меряется дважды — рано (чтобы
    вообще иметь цифру) и после созревания (чтобы иметь ИТОГОВУЮ). Третий раз не нужен: снятый
    зрелым в очередь больше не попадает, и очередь не превращается в вечный круг.
    """
    have = threads_app_metrics.known()
    edge = date.today() - timedelta(days=days)
    fresh, stale = [], []
    for p in io_safe.load_json(THREADS_POSTS, []):
        try:
            d = date.fromisoformat((p.get("date") or "")[:10])
        except ValueError:
            continue
        if d < edge or not code_of(p):
            continue
        seen = have.get(str(p.get("id")))
        if not seen:
            fresh.append(p)
            continue
        age_at_snap = seen.get("age_days_at_snap")
        age_now = (date.today() - d).days
        if age_at_snap is not None and age_at_snap < MATURE_DAYS <= age_now:
            stale.append(p)                 # мерили молодым, а теперь он созрел — нужен итог
    newest = lambda rows: sorted(rows, key=lambda p: p.get("date") or "", reverse=True)
    return newest(fresh) + newest(stale)    # новое важнее: у свежего поста окно замера уходит


def write_queue(days: int = DAYS, limit: int = 400) -> str:
    """Записать очередь кодов для браузера. Возвращает строку отчёта.

    Файл читает tools/threads_insights.ps1 и берёт из него ровно столько, сколько разрешено за
    один заход. Порядок в файле = порядок обхода, поэтому решение «что важнее» принимается здесь,
    а не в скрипте: скрипту думать нечем и не нужно."""
    rows = pending(days)[:limit]
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text("\n".join(code_of(p) for p in rows) + ("\n" if rows else ""), encoding="ascii")
    if not rows:
        return f"Очередь пуста: цифры есть по всем постам за {days} дн."
    oldest = rows[-1].get("date", "")[:10]
    return (f"В очереди {len(rows)} пост(ов) за {days} дн (с {oldest}). Браузер берёт из неё по "
            f"нескольку за заход — файл {QUEUE.name}.")


def status(days: int = DAYS) -> str:
    have, left = len(threads_app_metrics.known()), len(pending(days))
    total = have + len([p for p in pending(days) if str(p.get("id")) not in threads_app_metrics.known()])
    if not total:
        return "Постов за период нет."
    pct = 100 * have / total
    return (f"📱 Цифры из интерфейса: {have} из {total} постов за {days} дн ({pct:.0f}%). "
            f"Осталось {left}.")


if __name__ == "__main__":
    print(write_queue())
    print(status())
