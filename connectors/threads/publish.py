"""Запись в Threads: публикация постов и ответов — своих и под чужими (веха E; шаги 3-4 роадмапа).

БЕЗОПАСНОСТЬ ПРЕЖДЕ ВСЕГО. Проверка аккаунта 14.07 оказалась массовым сбоем Meta, не нашей
виной — но урок остаётся: запись в чужую платформу строится так, чтобы наш баг физически
не мог превратиться в объём. Пять слоёв, снять нельзя ни один:

1) ДВА КЛЮЧА. Запись идёт полосой записи `_guard`: нужен и data/threads_unlocked (чтение),
   и data/threads_write_unlocked (запись). Открытие — осознанное, с причиной:
   `_guard.unlock_write('причина')`. По умолчанию ЗАКРЫТО.
2) БЮДЖЕТЫ И ТЕМП — в `_guard` (10 записей/прогон, 24/сутки, 30-75с между записями), обойти
   из этого модуля нельзя: `_api._open()` — единственная дверь наружу.
3) КВОТА ГЛАЗАМИ META. Перед каждой записью сверяемся с их фактическим счётчиком
   (GET /{uid}/threads_publishing_limit: израсходовано из 250 постов / 1000 ответов за 24ч).
   ≥80% — не пишем. Их цифры, не наши догадки.
4) ЛИНТ ОХВАТА. Ссылки и хештеги режут охват в ~5 раз (данные 434 своих постов, см. память
   threads-reach-killers) — пост с ними НЕ уйдёт. Лимит 500 символов — жёсткий.
5) НИКАКОГО BULK. Модуль публикует ОДИН пост за вызов и не содержит циклов. Серию гонит
   вызывающий код, каждый пост — через ревью владельца. Автономных залпов здесь не будет.

Ответ (reply) = та же публикация с reply_to_id. Это фундамент будущего комментинга: под своим
постом (разворачивать тред, отвечать людям) и под чужим (когда дойдём до шага 4 — банк целей
через keyword_search строится ОТДЕЛЬНО и позже; мозг-комментатор — тоже не этот модуль).

Механика Meta (подтверждена докой): публикация двухшаговая —
  POST /{uid}/threads (media_type=TEXT, text[, reply_to_id][, reply_control]) → контейнер
  POST /{uid}/threads_publish (creation_id) → живой пост.
Права threads_content_publish и threads_manage_replies уже в токене (auth.SCOPES).

CLI (для обкатки руками):
    python -m connectors.threads.publish --check                    # лимиты Meta + защита
    python -m connectors.threads.publish --post "текст"             # 1 пост, спросит «да»
    python -m connectors.threads.publish --reply-to <id> --post "…" # 1 ответ, спросит «да»
"""
from __future__ import annotations

import logging
import os
import re

from connectors.threads import _api, auth
from connectors.threads._api import ThreadsBlocked, ThreadsError

log = logging.getLogger(__name__)

MAX_LEN = 500
# Порог по фактической квоте Meta: выше — не пишем (то же число, что стоп по x-app-usage).
LIMIT_STOP_PERCENT = float(os.getenv("THREADS_PUBLISH_LIMIT_STOP", "80"))

# Кто может отвечать под постом (параметр Meta reply_control; None = дефолт площадки).
REPLY_CONTROLS = {"everyone", "accounts_you_follow", "mentioned_only"}

_LINK_RE = re.compile(r"(?:https?://|www\.|t\.me/)", re.IGNORECASE)
_HASHTAG_RE = re.compile(r"(?:^|\s)#\w")


def lint(text: str) -> list[str]:
    """Проблемы текста, с которыми публиковать НЕЛЬЗЯ. Пусто = чисто.

    Жёсткий, не советующий: охват — главная валюта Threads, и его убийцы известны по нашим
    же данным. Захотим осознанное исключение — сначала меняем правило здесь, глазами.
    """
    t = (text or "").strip()
    problems = []
    if not t:
        problems.append("пустой текст")
        return problems
    if len(t) > MAX_LEN:
        problems.append(f"длина {len(t)} > {MAX_LEN} символов (Threads обрежет/отклонит)")
    if _LINK_RE.search(t):
        problems.append("ссылка в тексте — охват режется ~×5 (threads-reach-killers); "
                        "ссылки в Threads не публикуем вовсе")
    if _HASHTAG_RE.search(t):
        problems.append("хештег в тексте — тот же убийца охвата; убери")
    return problems


def publishing_limits() -> dict:
    """Фактический расход квоты записи ГЛАЗАМИ Meta (посты и ответы за 24ч).

    GET /{uid}/threads_publishing_limit. Это чтение (полоса чтения). Поля отдаём как есть +
    удобные проценты; чего-то нет в ответе — считаем 0/None, НЕ падаем.
    """
    uid = auth.user_id()
    data = _api.get(f"{uid}/threads_publishing_limit",
                    {"fields": "quota_usage,config,reply_quota_usage,reply_config"},
                    token=auth.valid_token())
    row = (data.get("data") or [{}])[0] if isinstance(data.get("data"), list) else data

    def _pair(usage_key: str, config_key: str) -> tuple[int, int | None]:
        used = row.get(usage_key)
        cap = (row.get(config_key) or {}).get("quota_total")
        try:
            return int(used or 0), (int(cap) if cap is not None else None)
        except (TypeError, ValueError):
            return 0, None

    posts_used, posts_cap = _pair("quota_usage", "config")
    replies_used, replies_cap = _pair("reply_quota_usage", "reply_config")

    def _pct(used: int, cap: int | None) -> float | None:
        return round(100.0 * used / cap, 1) if cap else None

    return {
        "posts_used": posts_used, "posts_cap": posts_cap,
        "posts_pct": _pct(posts_used, posts_cap),
        "replies_used": replies_used, "replies_cap": replies_cap,
        "replies_pct": _pct(replies_used, replies_cap),
    }


def _meta_limit_reason(is_reply: bool) -> str:
    """Почему Meta-квота не пускает. Пустая строка = можно.

    Сбой самой проверки = НЕ пишем (fail-closed): запись — то место, где «не знаю» = «нет».
    """
    try:
        lim = publishing_limits()
    except ThreadsBlocked as e:
        return str(e)
    except ThreadsError as e:
        return f"не смог проверить квоту записи Meta ({e}) — при сомнении НЕ пишем"
    pct = lim["replies_pct"] if is_reply else lim["posts_pct"]
    if pct is not None and pct >= LIMIT_STOP_PERCENT:
        kind = "ответов" if is_reply else "постов"
        return (f"квота {kind} Meta израсходована на {pct:.0f}% "
                f"(порог {LIMIT_STOP_PERCENT:.0f}%) — сегодня больше не пишем")
    return ""


def create_post(text: str, *, reply_to_id: str | None = None,
                reply_control: str | None = None, dry_run: bool = False) -> dict:
    """Опубликовать ОДИН пост (или ответ, если reply_to_id). НИКОГДА не бросает.

    Возвращает {"ok": bool, "id": ..., "permalink": ..., "error": ..., "dry_run": ...}.
    dry_run=True — репетиция БЕЗ сети: линт + состояние защиты; ничего не уходит.
    Порядок гейтов: дешёвые локальные → сеть. Любой отказ — с человекочитаемой причиной.
    """
    problems = lint(text)
    if problems:
        return {"ok": False, "error": "линт: " + "; ".join(problems)}
    if reply_control and reply_control not in REPLY_CONTROLS:
        return {"ok": False, "error": f"reply_control '{reply_control}' не из {sorted(REPLY_CONTROLS)}"}

    if dry_run:
        from connectors.threads import _guard
        frozen = _guard.frozen_reason(write=True)
        return {"ok": not frozen, "dry_run": True,
                "error": frozen or None,
                "note": "репетиция: линт пройден" + ("" if frozen else ", защита пустила бы")}

    is_reply = bool(reply_to_id)
    reason = _meta_limit_reason(is_reply)
    if reason:
        return {"ok": False, "error": reason}

    try:
        tok = auth.valid_token()
        uid = auth.user_id()
        params = {"media_type": "TEXT", "text": text.strip()}
        if reply_to_id:
            params["reply_to_id"] = reply_to_id
        if reply_control:
            params["reply_control"] = reply_control
        container = _api.post(f"{uid}/threads", params, token=tok)          # запись №1
        cid = container.get("id")
        if not cid:
            return {"ok": False, "error": f"Meta не вернула id контейнера: {container}"}
        published = _api.post(f"{uid}/threads_publish",                      # запись №2
                              {"creation_id": cid}, token=tok)
        mid = published.get("id")
        if not mid:
            return {"ok": False, "error": f"контейнер создан ({cid}), но publish не вернул id: "
                                          f"{published} — проверь глазами, вышел ли пост"}
    except (ThreadsBlocked, ThreadsError) as e:
        return {"ok": False, "error": str(e)}

    permalink = None
    try:  # ссылка на вышедший пост — приятно, но не критично: сбой не портит успех
        permalink = _api.get(mid, {"fields": "permalink"}, token=tok).get("permalink")
    except (ThreadsBlocked, ThreadsError) as e:
        log.info("Пост %s вышел, но permalink не добыл: %s", mid, e)

    what = f"ответ на {reply_to_id}" if is_reply else "пост"
    log.warning("Threads: опубликован %s id=%s %s", what, mid, permalink or "")
    return {"ok": True, "id": mid, "permalink": permalink}


def reply(post_id: str, text: str, *, dry_run: bool = False) -> dict:
    """Ответ под постом (СВОИМ или чужим) — фундамент комментинга. Один вызов = один ответ."""
    if not (post_id or "").strip():
        return {"ok": False, "error": "нет id поста, под которым отвечать"}
    return create_post(text, reply_to_id=post_id.strip(), dry_run=dry_run)


def _cli() -> int:
    import argparse
    import json as _json

    from connectors.threads import _guard

    p = argparse.ArgumentParser(description="Запись в Threads: один пост/ответ за запуск.")
    p.add_argument("--check", action="store_true", help="лимиты Meta + состояние защиты")
    p.add_argument("--post", metavar="ТЕКСТ", help="текст поста (или ответа при --reply-to)")
    p.add_argument("--reply-to", metavar="ID", help="id поста, под которым ответить")
    p.add_argument("--dry-run", action="store_true", help="репетиция без сети")
    args = p.parse_args()

    if args.check:
        print("Защита:", _json.dumps(_guard.stats(), ensure_ascii=False, indent=2))
        try:
            print("Квота записи Meta:", _json.dumps(publishing_limits(), ensure_ascii=False))
        except (ThreadsBlocked, ThreadsError) as e:
            print(f"Квота записи Meta: не добыл ({e})")
        return 0

    if not args.post:
        p.print_help()
        return 2

    what = f"ОТВЕТ под {args.reply_to}" if args.reply_to else "ПОСТ"
    if not args.dry_run:
        print(f"Публикую {what} в Threads:\n---\n{args.post}\n---")
        if input("Точно публиковать? Напиши «да»: ").strip().lower() != "да":
            print("Отменено.")
            return 1
    res = (reply(args.reply_to, args.post, dry_run=args.dry_run) if args.reply_to
           else create_post(args.post, dry_run=args.dry_run))
    print(_json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
