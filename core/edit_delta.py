"""Замер правок владельца: драфт (А) → то, что вышло в канал (Б).

ЗАЧЕМ. Петля обучения завода до сих пор зависела от одного человека: урок появлялся, только если
владелец САМ присылал правку в чат (`/feedback`). А правки уже лежат в канале — между тем, что
написал писатель, и тем, что реально опубликовано. Раньше эту разницу приходилось поднимать руками
и сравнивать глазами; теперь её считает код.

ЧТО ЭТО ДАЁТ. Число вместо ощущения «страдает / не страдает». Замер 20.08 (7 флагманов + 7 scope с
конца июля, покрытие по ТЕЛУ поста) показал то, чего на глаз видно не было:
- флагман — 100% на всех семи: владелец не переставил в них ни слова, правил только эмодзи заголовка;
- scope — 51% (31.07) → 79 → 59 → 100 (12.08, первый на Opus) → 93 → 89 → 95% (19.08), среднее 81%;
- самые упорные зоны правок scope — ЗАГОЛОВОК (11 постов из 15 за два месяца) и ФИНАЛ (12 из 15).

ЧЕГО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ (осознанно):
- НЕ пишет уроки сам. Не всякая правка = ошибка: владелец правит и по вкусу дня. Урок имеет смысл
  только на ПОВТОРЯЮЩЕМСЯ классе — модуль его помечает (`repeats`), решение остаётся за человеком.
  Автоурок с каждой мелочи уже проходили: файл уроков раздувается и разжижает контекст (дистилляция
  36→12 и откат 29.07).
- НЕ зовёт модель. Это арифметика по тексту: ноль API-вызовов, можно дёргать на каждом прогоне.
- НЕ судит качество. «Правка = ошибка писателя» — вывод человека, код лишь показывает ГДЕ и СКОЛЬКО.

КАК СОПОСТАВЛЯЕТ. Драфт ищет свой пост в канале по покрытию слов; несколько драфтов на один пост
(круги сохранения: писатель → фикс 2FA → бэкстоп) сводятся к ПОСЛЕДНЕМУ по времени файла — он и
уехал в канал. Дальше абзац драфта ищет ближайший абзац поста, и всё, что не нашлось, — снято
владельцем; всё, чему не нашлось пары с той стороны, — дописано им.
"""
from __future__ import annotations

import re

from core import analytics

# ── Пороги. Все — из замера 20.08 по 62 драфтам и 407 постам канала, не с потолка ──
MATCH_MIN = 0.45      # покрытие ниже → это ВООБЩЕ не тот пост (драфт не опубликован)
PARA_MATCH = 0.55     # взаимное покрытие абзацев: пара найдена
WORDY_KEEP = 0.80     # изменённый абзац с таким сходством = шлифовка СЛОВ, не переписывание мысли
REWRITE_MAX = 0.60    # покрытие ниже → пост переписан заново (31.07 Coldcard 51%, 10.08 BIP-110 59%)
CLEAN_MIN = 0.94      # выше → правка была лёгкой (scope 19.08 = 95%); ниже — уже содержательная
REPEAT_WINDOW = 3     # окно, в котором класс правки считается ПОВТОРЯЮЩИМСЯ
FLAGSHIP_MIN = 2400   # нижняя граница УЗНАВАНИЯ флагмана по драфту (не порог формата — тот в _lint)
LOOKBACK_POSTS = 60   # сколько последних постов канала держим в кандидатах (≈2 месяца выхода)

_FOOTER_MARK = ("Notion", "linktr.ee", "🖥")


def _norm(s: str) -> str:
    s = (s or "").split("[[SPLIT]]")[0]
    s = s.replace("**", "").replace(" ", " ")
    s = re.sub(r"[«»“”„]", '"', s).replace("—", "-").replace("–", "-")
    return re.sub(r"[ \t]+", " ", s).strip()


def _words(s: str) -> set:
    return set(re.findall(r"[^\W_]+", _norm(s).lower(), re.UNICODE))


def _cov(a: str, b: str) -> float:
    """Доля слов A, которые нашлись в B. Асимметрично — это и нужно: «сколько драфта уцелело»."""
    wa, wb = _words(a), _words(b)
    return (len(wa & wb) / len(wa)) if wa else 0.0


def _paras(text: str) -> list:
    """Абзацы без футера — футер режется/возвращается кодом и правкой владельца не является."""
    out = []
    for p in _norm(text).split("\n\n"):
        p = p.strip()
        if p and not any(m in p for m in _FOOTER_MARK):
            out.append(p)
    return out


def compare(draft: str, published: str) -> dict:
    """Карта различий драфт→канал. Чистая функция (тесты гоняют её напрямую)."""
    D, P = _paras(draft), _paras(published)
    used, same, wordy, rewritten, removed = set(), 0, 0, 0, 0
    for d in D:
        best_i, best_s = -1, 0.0
        for i, p in enumerate(P):
            if i in used:
                continue
            s = _cov(d, p) * _cov(p, d)          # взаимное — иначе короткий абзац «совпадает» со всем
            if s > best_s:
                best_i, best_s = i, s
        if best_i >= 0 and best_s >= PARA_MATCH:
            used.add(best_i)
            if P[best_i] == d:
                same += 1
            elif best_s >= WORDY_KEEP:
                wordy += 1                        # переставил слова/уточнил термин
            else:
                rewritten += 1                    # мысль переписана
        else:
            removed += 1
    added = len(P) - len(used)
    # Покрытие меряем по ТЕЛУ, без футера: он режется и возвращается кодом (линтер 14.08), в драфте
    # лежит markdown-ссылками, а в выгрузке канала — голым текстом. Считать его — мерить разметку,
    # а не правку владельца: на коротком посте один футер утягивал бы покрытие процентов на сорок.
    coverage = _cov("\n\n".join(D), "\n\n".join(P))
    tags = []
    if D and P and coverage < REWRITE_MAX:
        tags.append("переписан целиком")
    if D and P and D[0] != P[0]:
        tags.append("заголовок")
    if D and P and _norm(D[-1]) != _norm(P[-1]):
        tags.append("финал")
    if removed:
        tags.append(f"снял блок×{removed}")
    if added:
        tags.append(f"дописал×{added}")
    if rewritten:
        tags.append(f"переписал мысль×{rewritten}")
    if wordy and not rewritten:
        tags.append("шлифовка слов")
    # «Чисто» = владелец не тронул НИЧЕГО (даже слова). Мягче нельзя: 19.08 покрытие было 95%, но пять
    # абзацев он всё-таки поправил — назвать такой пост «без правок» значит соврать самим себе о цели
    # «не редактирую вообще». Покрытие рядом остаётся как мера ТЯЖЕСТИ правки.
    return {"coverage": round(coverage, 3), "same": same, "wordy": wordy, "rewritten": rewritten,
            "removed": removed, "added": added, "n_draft": len(D), "n_post": len(P), "tags": tags,
            "clean": not (removed or added or rewritten or wordy) and bool(D)}


def _draft_kind(name: str, text: str) -> str:
    """Формат драфта. Имя файла надёжнее длины: save_draft клеит в слаг латинский 'scope', а
    кириллическое 'флагман' из имени вырезает регексом слага — поэтому флагман узнаём по размеру."""
    if "-scope" in name:
        return "scope"
    return "флагман" if len(_norm(text)) >= FLAGSHIP_MIN else ""


def reports(kind: str = "", limit: int = 5) -> list:
    """Отчёты по последним опубликованным постам формата, свежие первыми.

    Драфты читаем с диска (это выход писателя), посты — из выгрузки канала (это решение владельца).
    Оба источника уже актуализируются шагом 0 пайплайна, своих обновлений модуль не делает.
    """
    # Импорт ЛЕНИВЫЙ и это не стиль, а необходимость: creator_tools тянет analytics_tools, а тот —
    # нас (там живёт инструмент edit_report). На уровне модуля получился бы цикл и падение импорта.
    from core import creator_tools
    try:
        posts = [p for p in analytics._load_posts() if (p.get("text") or "").strip()]
    except Exception:                              # нет выгрузки — замер просто молчит
        return []
    if not posts:
        return []
    posts = sorted(posts, key=lambda p: p.get("date") or "", reverse=True)[:LOOKBACK_POSTS]
    # тела постов считаем ОДИН раз: матчить драфт с футером нельзя — он одинаков у всех постов канала
    # и подтягивает сходство любому кандидату, размывая порог MATCH_MIN.
    bodies = [(p, "\n\n".join(_paras(p["text"]))) for p in posts]
    d = creator_tools.DRAFTS_DIR
    if not d.exists():
        return []
    best_by_post: dict = {}
    for path in sorted(d.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        k = _draft_kind(path.name, text)
        if not k or (kind and k != kind):
            continue
        draft_body = "\n\n".join(_paras(text))
        cand, cov_best = None, 0.0
        for p, body in bodies:
            c = _cov(draft_body, body)
            if c > cov_best:
                cand, cov_best = p, c
        if not cand or cov_best < MATCH_MIN:
            continue
        # круги одного поста: файлы идут от свежих к старым → первым попал ПОСЛЕДНИЙ круг, он и верен
        if cand["id"] in best_by_post:
            continue
        rep = compare(text, cand["text"])
        rep.update({"post_id": cand["id"], "date": (cand.get("date") or "")[:10],
                    "kind": k, "draft": path.name})
        best_by_post[cand["id"]] = rep
        if len(best_by_post) >= limit:
            break
    return sorted(best_by_post.values(), key=lambda r: r["date"], reverse=True)


def repeats(reps: list, window: int = REPEAT_WINDOW) -> list:
    """Классы правок, повторившиеся в окне ≥2 раз, — только они кандидаты в уроки.

    Одиночная правка = вкус дня, а не правило (поэтому автоурок с каждой мелочи мы не пишем).
    Счётчики в ярлыках («снял блок×2») для сравнения срезаем — важен КЛАСС, а не количество.
    """
    seen: dict = {}
    for r in reps[:window]:
        for t in r.get("tags", []):
            base = t.split("×")[0]
            seen[base] = seen.get(base, 0) + 1
    return [f"{t} ({n} из {min(window, len(reps))})" for t, n in sorted(seen.items(), key=lambda x: -x[1])
            if n >= 2]


def panel_line(kind: str = "") -> str:
    """Одна строка для ИТОГ-панели прогона: как обошлись с ПРОШЛЫМ постом этого формата."""
    reps = reports(kind, limit=REPEAT_WINDOW)
    if not reps:
        return ""
    r = reps[0]
    head = f"#{r['post_id']} {round(r['coverage'] * 100)}%"
    body = "правок нет" if r["clean"] else ", ".join(r["tags"][:3]) or "мелкие правки"
    rep = repeats(reps)
    return f"{head} · {body}" + (f"  ⟲ повтор: {rep[0]}" if rep else "")


def text_report(kind: str = "", limit: int = 5) -> str:
    """Человекочитаемый отчёт (для Аналитика и чата)."""
    reps = reports(kind, limit)
    if not reps:
        return ("Замер правок недоступен: нет опубликованных постов, совпавших с драфтами "
                "(проверь выгрузку канала и memory/drafts).")
    lines = [f"Правки владельца по формату «{kind or 'все'}» — драфт → канал:"]
    for r in reps:
        lines.append(f"  {r['date']} #{r['post_id']}: сохранилось {round(r['coverage'] * 100)}% · "
                     f"абзацы {r['same']}=/{r['wordy']}~/{r['rewritten']}≠/{r['removed']}-/{r['added']}+"
                     + (f" · {', '.join(r['tags'])}" if r["tags"] else " · правок нет"))
    rep = repeats(reps)
    if rep:
        lines.append("ПОВТОРЯЮЩИЕСЯ классы (кандидаты в уроки): " + "; ".join(rep))
    else:
        lines.append("Повторяющихся классов правок нет — разовые случаи, в уроки не годятся.")
    avg = sum(r["coverage"] for r in reps) / len(reps)
    lines.append(f"Среднее сохранение по {len(reps)} постам: {round(avg * 100)}% "
                 f"(ориентир — флагман: 100% на семи постах с конца июля).")
    return "\n".join(lines)
