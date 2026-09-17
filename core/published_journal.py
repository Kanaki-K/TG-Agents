"""🧵 Журнал ВЫШЕДШИХ ТГ-постов — мост Telegram → Threads (оба формата).

Когда ТГ-пост реально уходит в отложку канала (run_pipeline, только боевая публикация — не
draft-only/тест), его ПОЛНЫЙ текст + формат + тема + дата дописываются сюда одной строкой JSON.
Это ВХОД Threads-ветки: `threads_creator` берёт последнюю запись СВОЕГО формата и делает из неё
пост площадки (флагман → мини-флагман, скоуп → мини-скоуп).

Формат в записи обязателен и решает, ЧЕЙ свод правил применится: четыре свода (площадка × формат)
не смешиваются, и журнал — то место, где ТГ-пост получает свою метку на входе в Threads.

Почему отдельный журнал, а не «читать последний драфт»: драфты эфемерны (их перетирает следующий
прогон), а журнал — намеренная датированная история (архив + устойчивый вход Threads).
Файл в data/ (gitignored) — рантайм-состояние, не код. Append-only, один пост = одна строка.

Миграция: до 09.09.2026 журнал был флагман-только и жил в data/published_flagships.jsonl. Старые
записи переносятся сюда один раз при первом обращении и получают формат 'flagship' — история
вышедших флагманов (вход мини-флагмана) не теряется.
"""
import json
import logging
import re
import shutil
from datetime import date, datetime
from pathlib import Path

from core import config, content_plan

JOURNAL = config.ROOT / "data" / "published_posts.jsonl"
# Копии обложек постов журнала под своими именами. НЕ data/published_covers: там эталон ОБЛОЖЕК БОЕВОГО
# КАНАЛА (dump_covers + index.json), по нему tools/probe_covers сравнивает качество — копии завода его засоряли бы.
COVERS_DIR = config.ROOT / "data" / "journal_covers"
LEGACY_JOURNAL = config.ROOT / "data" / "published_flagships.jsonl"   # флагман-только, до 09.09.2026


def _migrate() -> None:
    """Один раз перелить старый флагман-журнал в новый (формат проставляем 'flagship').

    Старый файл НЕ удаляем: он безвреден, а его наличие — след истории. Повторный вызов ничего не
    делает (новый файл уже есть). Сбой миграции не роняет вызывающего — журнал вторичен к посту."""
    if JOURNAL.exists() or not LEGACY_JOURNAL.exists():
        return
    try:
        rows = []
        for ln in LEGACY_JOURNAL.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                entry = json.loads(ln)
            except json.JSONDecodeError:
                continue
            entry.setdefault("kind", "flagship")
            rows.append(json.dumps(entry, ensure_ascii=False))
        if rows:
            JOURNAL.parent.mkdir(parents=True, exist_ok=True)
            JOURNAL.write_text("\n".join(rows) + "\n", encoding="utf-8")
            logging.info("published_journal: перенёс %d записей из старого флагман-журнала", len(rows))
    except Exception:
        logging.exception("published_journal: миграция старого журнала не удалась (иду дальше)")


_NODE = re.compile(r"^\s*\[\[УЗЕЛ\]\]\s*(.+)$", re.M | re.I)
_TYPE = re.compile(r"^\s*\[\[ТИП\]\]\s*(.+)$", re.M | re.I)
_EXIT = re.compile(r"^\s*\[\[ВЫХОД\]\]\s*(.+)$", re.M | re.I)

# Пять типов услуги читателю (v2.1, 10.09.2026). Ротация по ним — защита не от скуки, а от того,
# что канал начнёт оказывать ОДНУ услугу: владелец 10.09 — «читатель не умнеет по-новому, он
# получает ту же эмоцию заново».
SERVICE_TYPES = ("механизм", "личная ставка", "инструмент", "переворот", "линза")


def _meta(text: str, rx) -> str:
    """Значение однострочной пометки из МЕТЫ (после [[SPLIT]]). В теле не ищем — там это мусор."""
    parts = (text or "").split("[[SPLIT]]")
    if len(parts) < 2:
        return ""
    m = rx.search(parts[1])
    return m.group(1).strip() if m else ""


def service_of(text: str) -> str:
    """Ведущий тип услуги, помеченный автором. Нераспознанное имя → '' (лучше пусто, чем ложь)."""
    raw = _meta(text, _TYPE).lower()
    return next((t for t in SERVICE_TYPES if t in raw), "")


def recent_services(limit: int = 3) -> list[str]:
    """Типы услуги последних постов (свежие первыми) — для ротации в пикере темы."""
    out = []
    for e in reversed(entries()):
        s_ = (e.get("service") or "").strip()
        if s_:
            out.append(s_)
        if len(out) >= limit:
            break
    return out


def nodes_of(text: str) -> list[str]:
    """Узлы, помеченные автором поста в МЕТЕ (после [[SPLIT]]): «что здесь живёт само».

    ЗАЧЕМ (v2, 10.09.2026). Прямая просьба автора Threads-дистилляций: «думающий и знающий слой были
    сплавлены в один абзац, и мне приходилось их растаскивать; если бы завод сам помечал — вот это
    мысль, вот это цифры — дистилляция шла бы вдвое быстрее». Помеченный узел избавляет деривацию от
    поиска вслепую, а расхождение «что автор считал узлом» против «что реально сработало» становится
    отдельным замером через месяц.

    Ищем ТОЛЬКО в мете: в теле такая строка была бы служебным мусором в опубликованном посте."""
    meta = (text or "").split("[[SPLIT]]")
    if len(meta) < 2:
        return []
    return [m.group(1).strip() for m in _NODE.finditer(meta[1]) if m.group(1).strip()]


def _keep_cover(path: str, kind: str, tg: dict) -> str:
    """Скопировать обложку под НЕПОВТОРЯЮЩИМСЯ именем и вернуть путь копии — журнал ссылается на неё.

    ЗАЧЕМ (аудит 11.09.2026): ТГ-скоуп называет кадры scope_<страница>_<кадр>.jpg, и каждый прогон пишет
    поверх. Журнал хранил путь к такому кадру — к 11.09 обложки записей 09.09 и 10.09 уже были картинками
    другого прогона, и мини-скоуп уехал бы в Threads с чужой обложкой. Не скопировалось — оставляем
    исходный путь: журнал вторичен к посту, а пайплайн Threads сам проверит, не перезаписан ли файл."""
    raw = (path or "").strip()
    if not raw or not Path(raw).is_file():
        return raw
    stamp = tg.get("msg_id") if tg.get("msg_id") is not None else datetime.now().strftime("%H%M%S")
    dst = COVERS_DIR / f"{date.today().isoformat()}_{kind}_{stamp}{Path(raw).suffix or '.jpg'}"
    try:
        COVERS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(raw, dst)
        return str(dst)
    except Exception:
        logging.exception("published_journal: обложку не скопировал — оставляю исходный путь")
        return raw


def record(text: str, theme: str = "", kind: str = "flagship", cover: str = "",
           tg: dict | None = None, service: str = "") -> None:
    """Дописать вышедший пост (текст + формат + тема + дата + путь к обложке) в журнал.

    Мету после [[SPLIT]] отбрасываем (в Threads уходит только тело). cover — файл обложки, с которой
    пост вышел в ТГ: мини-скоуп берёт ЕЁ же (решение владельца 09.09 — картинку для Threads не ищем
    заново, она уже опубликована и одобрена). Сбой записи НЕ роняет публикацию — журнал вторичен.

    tg — квитанция постановки из creator_tools._publish_now (channel / msg_id / scheduled_at / text).
    Номер сообщения и время сохраняем: по ним Threads-ветка сверяет журнал с каналом (threads_source)."""
    tg = tg or {}
    # Тело — ТО, ЧТО РЕАЛЬНО УШЛО В КАНАЛ, если квитанция есть. `text` пайплайна — ответ модели: 11.09 в
    # журнал вместе с постом записалась её реплика «Линтер чистый. Выдаю.» — в канал она не попала, а в
    # Threads уехала бы. Мету (узлы/тип/выход) по-прежнему читаем из `text`: в канал она не уходит.
    body = (tg.get("text") or text or "").split("[[SPLIT]]")[0].strip()
    if not body:
        return
    try:
        _migrate()
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        entry = {"date": date.today().isoformat(), "kind": content_plan.norm_kind(kind),
                 "theme": (theme or "").strip(), "text": body,
                 "cover": _keep_cover(cover, content_plan.norm_kind(kind), tg),
                 # ТИП УСЛУГИ: сначала мета поста, потом — то, что назвал пикер прогона. Фолбэк не
                 # роскошь: замер 17.09 дал 40 записей подряд с пустым типом (писатель меты не давал
                 # вовсе), и ротация «два поста одного типа подряд запрещены» жила без единых данных.
                 "nodes": nodes_of(text), "service": service_of(text) or (service or "").strip(),
                 "exit": _meta(text, _EXIT)}
        if tg.get("msg_id") is not None:
            entry.update({"tg_channel": tg.get("channel") or "", "tg_msg_id": tg["msg_id"],
                          "tg_scheduled_at": tg.get("scheduled_at") or ""})
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        logging.exception("published_journal: не смог записать вышедший пост (публикацию не роняю)")


def _entries() -> list[dict]:
    """Все записи (старые→новые). Битую строку пропускаем, битый файл не роняем в трейс."""
    _migrate()
    if not JOURNAL.exists():
        return []
    out: list[dict] = []
    try:
        for ln in JOURNAL.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    except Exception:
        logging.exception("published_journal: журнал не читается — возвращаю, что успел")
    return out


def entries(kind: str = "") -> list[dict]:
    """Все записи журнала (старые→новые), при желании — только своего формата.

    Записи без поля 'kind' (доисторические) считаем флагманами — так их и писали."""
    want = content_plan.norm_kind(kind) if kind else ""
    rows = [e for e in _entries() if e.get("text")]
    return [e for e in rows if (e.get("kind") or "flagship") == want] if want else rows


def latest(kind: str = "") -> dict | None:
    """Последняя запись журнала (dict: date/kind/theme/text) или None.

    kind пустой — последний пост ЛЮБОГО формата; иначе последний пост именно этого формата.
    Вход Threads-ветки: ЧТО перерабатывать. Записи без поля 'kind' (доисторические) считаем
    флагманами — так их и писали."""
    want = content_plan.norm_kind(kind) if kind else ""
    for entry in reversed(_entries()):
        if not entry.get("text"):
            continue
        if want and (entry.get("kind") or "flagship") != want:
            continue
        return entry
    return None
