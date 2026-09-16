"""Приём страницы Insights, снятой браузером владельца (tools/threads_insights.ps1).

ЗАЧЕМ ЭТОТ ПУТЬ СУЩЕСТВУЕТ. Подписки и заходы в профиль НА ПОСТ есть в интерфейсе Threads и
отсутствуют в API — проверено перебором допустимых метрик 09.09.2026 (Meta отвечает списком, их
там нет). Владелец: «мне нужно решение на дистанцию» — то есть без ручного прокликивания. Решение:
его же Chrome раз в 3-5 суток (в случайное время — решение владельца 09.09: ровный ритм виден
со стороны) открывает свою страницу Insights и сохраняет ОТРИСОВАННУЮ страницу в data/incoming/. Завод забирает файл с диска. Сети со стороны завода тут нет вообще: мы читаем
файл, а не ходим в Meta.

ЧТО ЗДЕСЬ ВАЖНО. Разбор идёт не по вёрстке (она меняется каждый месяц и ломала бы всё), а по
СЛОВАМ интерфейса: «Перегляди», «Відвідування профілю», «Глядачі», «Нові читачі» и их русские и
английские варианты. Разметку мы просто срезаем, оставляя текст в том же порядке, в каком его
видит человек, — а дальше работает тот же разбор, что и для вставки из приложения
(core/threads_app_metrics). Один разборщик на два источника: меньше мест, где врать.

ОБРАБОТАННЫЕ ФАЙЛЫ УЕЗЖАЮТ в data/incoming/processed/ — иначе каждый прогон перечитывал бы всю
папку и записывал бы старые цифры поверх свежих (метрики растут со временем, это была бы порча).
"""
from __future__ import annotations

import html
import logging
import re
import shutil
from pathlib import Path

import json
import time
from datetime import date

from core import config, threads_app_metrics

INCOMING = config.ROOT / "data" / "incoming"
DONE = INCOMING / "processed"
OVERVIEW = "insights-????-??-??.html"      # общая страница: цифры АККАУНТА
POST_PAGE = "insights-post-*.html"          # страница одного поста: заходы в профиль и подписки
ACCOUNT_LOG = config.ROOT / "data" / "threads_account_insights.jsonl"
_POST_CODE = re.compile(r"insights-post-([A-Za-z0-9_-]+)-\d{4}-\d{2}-\d{2}\.html$")

# Страница поста содержит СНАЧАЛА общий список последних постов, и только потом карточку самого
# поста. Без этого якоря разбор брал «Просмотры» из списка — то есть цифры чужого поста.
_POST_SECTION = re.compile(r"^\s*(Статистика публикации|Статистика публікації|"
                           r"Beitrags-Insights|Post insights)\s*$", re.I | re.M)

# «Что влияет на число просмотров» — Meta сама называет доли, повлиявшие на охват, и источники
# показов. Для разбора виральности это прямое показание площадки, а не наша догадка.
_FACTORS = (
    ("like_share",    r"Доля отметок.*|Частка вподобайок.*|Like share"),
    ("reply_share",   r"Доля ответов|Частка відповідей|Reply share"),
    ("share_share",   r"Доля поделившихся|Частка поширень|Share share"),
    ("quote_share",   r"Доля цитат|Частка цитат|Quote share"),
    ("repost_share",  r"Доля репостов|Частка репостів|Repost share"),
    ("src_home",      r"Главная|Головна|Home"),
    ("src_instagram", r"Instagram"),
    ("src_search",    r"Поиск|Пошук|Search"),
    ("src_profile",   r"Профиль|Профіль|Profile"),
)
_PCT = re.compile(r"^-?\d+(?:[.,]\d+)?\s*%$")

# Цифры аккаунта с общей страницы. Ключ — наше имя, значение — как это называется в интерфейсе.
_ACCOUNT = (
    ("views",               r"(Aufrufe|Перегляди|Просмотры|Views)"),
    ("viewers",             r"(Betrachter|Глядачі|Зрители|Viewers)"),
    ("net_followers",       r"(Netto-Follower|Чист[а-я]+ (?:приріст|прирост)[а-я ]*|Net followers)"),
    ("interactions",        r"(Interaktionen|Взаємодії|Взаимодействия|Interactions)"),
    ("non_follower_viewers", r"(Nicht-Follower|Не підписники|Не подписчики|Non-followers)"),
)
# «Подписчики» на странице встречаются ДВАЖДЫ и означают разное: в разделе «типы зрителей» это
# сколько ваших подписчиков вас увидело (171), а ниже, в разделе профиля, — сколько их всего (619).
# Отличаем по порядку: первое вхождение — зрители-подписчики, последнее — всего подписчиков.
# Это надёжнее привязки к заголовку раздела: заголовки переводятся, порядок блоков — нет.
_FOLLOWER = r"(Follower|Followers|Читачі|Підписники|Подписчики)"

_SCRIPTS = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n{3,}")


def to_text(raw_html: str) -> str:
    """Отрисованная страница → текст в том же порядке, в каком его видит человек.

    Блочные теги превращаем в перенос строки: приложение и веб выводят метрику тремя строками
    (название, число, сравнение), и именно этот порядок читает разборщик."""
    s = _SCRIPTS.sub(" ", raw_html or "")
    s = re.sub(r"</(div|p|li|section|article|h[1-6]|span|td|tr)>", "\n", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = _TAGS.sub("\n", s)
    s = html.unescape(s)
    s = "\n".join(ln.strip() for ln in s.splitlines())
    return _BLANKS.sub("\n\n", s).strip()


def parse_factors(text: str) -> dict:
    """Доли влияния на охват и источники показов → проценты (float).

    Проценты держим ОТДЕЛЬНО от счётчиков: смешать «366 просмотров» и «0,82 %» в одном словаре
    значит однажды сложить их в одном отчёте. Значения приводим к точке — «0,82 %» это 0.82."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: dict = {}
    for field, pattern in _FACTORS:
        rx = re.compile(rf"^(?:{pattern})$", re.I)
        for i, ln in enumerate(lines):
            if not rx.match(ln):
                continue
            for nxt in lines[i + 1:i + 3]:
                if _PCT.match(nxt):
                    out[field] = float(nxt.replace("%", "").replace(",", ".").strip())
                    break
            if field in out:
                break
    return out


def parse_post_page(text: str) -> tuple[dict, dict]:
    """Страница одного поста → (счётчики, доли). Читаем ТОЛЬКО карточку поста, не список сверху."""
    m = _POST_SECTION.search(text)
    body = text[m.end():] if m else text
    nums = {k: v for k, v in threads_app_metrics.parse_block(body).items() if k != "text"}
    return nums, parse_factors(body)


def parse_account(text: str) -> dict:
    """Цифры АККАУНТА с общей страницы: просмотры, зрители, чистый прирост, взаимодействия.

    Читаем по подписям, а не по вёрстке. Число на этой странице стоит СТРОКОЙ НИЖЕ подписи, а
    следом идёт процент изменения — его берём отдельно и в метрики не мешаем: доля изменения это
    комментарий к числу, а не число."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    def value_after(idx: int):
        for nxt in lines[idx + 1:idx + 3]:
            v = threads_app_metrics._num(nxt)
            if v is not None:
                return v
        return None

    out: dict = {}
    for field, pattern in _ACCOUNT:
        rx = re.compile(rf"^{pattern}$", re.I)
        for i, ln in enumerate(lines):
            if rx.match(ln):
                v = value_after(i)
                if v is not None:
                    out[field] = v
                    break
    hits = [value_after(i) for i, ln in enumerate(lines)
            if re.fullmatch(_FOLLOWER, ln, re.I) and value_after(i) is not None]
    if hits:
        out["follower_viewers"] = hits[0]      # первое вхождение — сколько подписчиков увидело
        out["followers"] = hits[-1]            # последнее — сколько их всего
    return out


def save_account(row: dict) -> None:
    """Дописать снимок аккаунта в журнал (строка на дату). Журнал только растёт."""
    if not row:
        return
    row = dict(row, date=date.today().isoformat())
    ACCOUNT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ACCOUNT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def ingest_file(path: Path) -> str:
    """Разобрать один снимок и записать метрики. Возвращает отчёт.

    Два вида файлов разбираются ПО-РАЗНОМУ, и это не мелочь: общая страница свёрстана списком и
    цифры постов на ней неполные (заходов в профиль там нет вовсе), а страница поста — карточка
    одного поста. Смешать их в один разбор значило бы записывать половинчатые цифры поверх полных."""
    path = Path(path)
    text = to_text(path.read_text(encoding="utf-8", errors="replace"))
    m = _POST_CODE.search(path.name)
    if m:
        code = m.group(1)
        post = threads_app_metrics.by_code(code)
        if not post:
            return f"📄 {path.name}: пост с кодом {code} не найден в выгрузке"
        nums, factors = parse_post_page(text)
        if not nums:
            return f"📄 {path.name}: цифр на странице не нашёл (вёрстка или язык изменились)"
        threads_app_metrics.save(post["id"], dict(nums, **factors), post.get("date", ""))
        head = " ".join((post.get("text") or "").split())[:44]
        return (f"✅ {(post.get('date') or '')[:10]} «{head}» ← "
                + " · ".join(f"{k} {v}" for k, v in nums.items()))
    acc = parse_account(text)
    save_account(acc)
    return (f"📄 {path.name}: цифры аккаунта — "
            + " · ".join(f"{k} {v}" for k, v in acc.items()) if acc
            else f"📄 {path.name}: цифр аккаунта не нашёл")


def intake(move: bool = True) -> str:
    """Забрать все новые снимки из data/incoming. Пусто — молчим (это штатный день без файла)."""
    files = sorted(INCOMING.glob(OVERVIEW)) + sorted(INCOMING.glob(POST_PAGE))
    if not files:
        return ""
    out = []
    for f in files:
        # Файл может ПИСАТЬСЯ прямо сейчас (браузер снимает страницы часами). Разобрать половину
        # и увезти её в «обработанные» — значит потерять пост молча, поэтому свежие не трогаем.
        if time.time() - f.stat().st_mtime < 60:
            continue
        try:
            report = ingest_file(f)
            out.append(report)
            # Увозим ТОЛЬКО удачный разбор. Неудачный остаётся на месте: вёрстка могла измениться,
            # и файл ещё понадобится, когда я починю разбор. Увезённый файл — потерянный день.
            if move and ("✅" in report or "цифры аккаунта" in report):
                DONE.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(DONE / f.name))
        except Exception:  # noqa: BLE001 — один битый файл не отменяет остальные
            logging.getLogger(__name__).warning("снимок %s не разобрался", f.name, exc_info=True)
            out.append(f"📄 {f.name}: разобрать не смог (файл оставлен на месте)")
    try:                       # очередь пересобираем ПОСЛЕ разбора: собранные посты из неё уходят
        from core import threads_insights_queue
        out.append(threads_insights_queue.write_queue())
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("очередь снимков не пересобралась", exc_info=True)
    note = threads_app_metrics.coverage_note(days=3)
    if note:
        out.append(note)     # снимок был, но пост в него не попал — это видно сразу, а не через месяц
    return "\n".join(out)


if __name__ == "__main__":
    print(intake() or f"Новых снимков в {INCOMING} нет. Их кладёт tools/threads_insights.ps1.")
