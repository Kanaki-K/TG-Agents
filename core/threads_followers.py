"""Дневной счётчик подписчиков Threads — единственный способ связать посты с подписками.

ПОЧЕМУ ТАК, А НЕ ПРОЩЕ. Владелец просил «подписки к постам». Meta их не отдаёт: у поста есть
views/likes/replies/reposts/quotes/shares — и всё, метрики «пришло N подписчиков» не существует ни
в каком виде. На уровне аккаунта есть followers_count, но только как ТЕКУЩЕЕ число: временного ряда
у него нет, и задним числом историю не восстановить. Значит единственный честный способ увидеть,
какие посты приводят людей, — снимать счётчик КАЖДЫЙ ДЕНЬ самим и складывать в журнал. Начали
09.09.2026; всё, что было раньше, потеряно навсегда — поэтому снимок и повешен на автопилот, а не
на «когда вспомним».

ЧЕСТНОСТЬ ЗАМЕРА — три правила, без которых журнал будет врать:

1. **Прирост принадлежит ДНЮ, а не посту.** Если в день вышло два поста, вклад между ними не
   делится. Делить поровну — выдумывать: это ровно та арифметика, из-за которой мы уже получали
   уверенные неверные выводы. Поэтому прирост кладётся к посту, только когда пост в этом дне ОДИН,
   а дни с несколькими постами помечаются неразделимыми.
2. **Окно снимка — сутки МЕЖДУ снимками.** Прирост между снимком дня D и снимком дня D+1 накрывает
   посты, вышедшие в день D (они выходят в 16:00, снимок делает автопилот в течение дня). Поэтому
   `growth()` относит дельту к ДНЮ РАННЕГО снимка, а не позднего.
3. **Разрыв в снимках не склеиваем.** Пропустили день — дельта за два дня к одному дню не
   приписывается: такая пара помечается разрывом и в атрибуцию не идёт (в средние тоже).

Подписчики уходят так же, как приходят, поэтому дельта бывает отрицательной — это не ошибка сбора.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

from core import config, content_plan

JOURNAL = config.ROOT / "data" / "threads_followers.jsonl"


def _today() -> str:
    return datetime.now(content_plan.tz()).date().isoformat()


def entries() -> list[dict]:
    """Журнал снимков, по одному на дату, отсортирован по дате. Битые строки пропускаем."""
    rows: list[dict] = []
    if JOURNAL.exists():
        for ln in JOURNAL.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue                      # битая строка не отменяет весь ряд
            if isinstance(r, dict) and r.get("date") and isinstance(r.get("followers"), int):
                rows.append(r)
    by_day: dict[str, dict] = {}
    for r in rows:                       # позже записанный снимок дня побеждает: это дозапись, не дубль
        by_day[str(r["date"])[:10]] = r
    return [by_day[d] for d in sorted(by_day)]


def snapshot(count: int | None = None, when: str = "") -> dict:
    """Снять счётчик и дописать в журнал (один снимок на дату). Возвращает записанную строку.

    count=None → сходить в API. Повторный вызов в тот же день перезаписывает снимок дня, а не
    плодит строки: `entries()` берёт последний. Так дневной прогон можно запускать сколько угодно
    раз, и журнал от этого не портится."""
    if count is None:
        from connectors.threads import insights
        count = insights.followers_count()
    if count is None:
        raise RuntimeError("Meta не отдала followers_count — снимок не записан")
    row = {"date": (when or _today())[:10], "followers": int(count),
           "at": datetime.now(content_plan.tz()).isoformat(timespec="seconds")}
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def snapshot_quiet() -> dict | None:
    """Снимок для фоновой гигиены: любой сбой глотаем — счётчик не имеет права уронить прогон."""
    try:
        if any(r["date"] == _today() for r in entries()):   # сегодня уже сняли — в API не ходим
            return None
        return snapshot()
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("не смог снять счётчик подписчиков Threads", exc_info=True)
        return None


def growth() -> dict[str, int]:
    """{дата: прирост за сутки ПОСЛЕ снимка этой даты}. Дни с разрывом в снимках пропущены.

    Дельта относится к дню РАННЕГО снимка (правило 2 в шапке): посты дня D живут в окне между
    снимком D и снимком D+1."""
    rows = entries()
    out: dict[str, int] = {}
    for a, b in zip(rows, rows[1:]):
        d1, d2 = date.fromisoformat(a["date"]), date.fromisoformat(b["date"])
        if d2 - d1 != timedelta(days=1):      # разрыв: за какой день прирост — неизвестно
            continue
        out[a["date"]] = int(b["followers"]) - int(a["followers"])
    return out


def attach(posts: list[dict]) -> list[dict]:
    """Приписать постам прирост подписчиков их дня. Меняет посты на месте и возвращает их же.

    Кладём два поля: `followers_gain` — прирост дня (None, если снимков на этот день нет) и
    `gain_posts` — сколько постов делят этот прирост. Атрибуция честна только при gain_posts == 1;
    при большем числе прирост показываем, но как ОБЩИЙ для дня, и в средние по постам не берём."""
    g = growth()
    per_day: dict[str, int] = {}
    for p in posts:
        per_day[(p.get("date") or "")[:10]] = per_day.get((p.get("date") or "")[:10], 0) + 1
    for p in posts:
        d = (p.get("date") or "")[:10]
        p["followers_gain"] = g.get(d)
        p["gain_posts"] = per_day.get(d, 0)
        p["gain_solo"] = bool(g.get(d) is not None and per_day.get(d) == 1)
    return posts


def report(posts: list[dict] | None = None) -> str:
    """Что журнал уже может сказать. Пока данных мало — честно говорит, сколько ещё ждать."""
    rows = entries()
    if not rows:
        return ("👥 Подписчики: журнал пуст. Снимок берёт автопилот раз в сутки "
                "(или `python -m core.threads_followers`). Подписок НА ПОСТ Meta не отдаёт — "
                "дневной прирост единственный доступный сигнал.")
    g = growth()
    head = (f"👥 Подписчики: сейчас {rows[-1]['followers']} · снимков {len(rows)} "
            f"({rows[0]['date']} → {rows[-1]['date']}) · дней с приростом {len(g)}")
    if len(g) < 7:
        return head + (f"\n   Ряд короткий: для вывода нужно ≥7 суток подряд, есть {len(g)}. "
                       "Считать средние на таком ряду — гадание, поэтому не считаю.")
    out = [head, f"   Прирост за наблюдаемый период: {sum(g.values()):+d} · "
                 f"медиана в сутки {sorted(g.values())[len(g) // 2]:+d}"]
    if posts:
        attach(posts)
        solo = [p for p in posts if p.get("gain_solo")]
        if solo:
            out.append(f"\n   ДНИ С ОДНИМ ПОСТОМ ({len(solo)}) — прирост можно отнести к посту:")
            for p in sorted(solo, key=lambda x: x.get("followers_gain") or 0, reverse=True)[:10]:
                head_txt = " ".join((p.get("text") or "").split())[:56]
                out.append(f"   {p.get('date','')[:10]} {p['followers_gain']:+3d} подписчиков · "
                           f"просм {p.get('views', 0):>5} · «{head_txt}»")
        shared = [p for p in posts if p.get("followers_gain") is not None and not p.get("gain_solo")]
        if shared:
            out.append(f"   Дней с несколькими постами: прирост есть, но между постами не делится "
                       f"({len(shared)} постов) — в атрибуцию не идут.")
    return "\n".join(out)


if __name__ == "__main__":
    print(snapshot())
    print(report())
