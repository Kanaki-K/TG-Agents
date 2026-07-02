"""Комментарии под своими постами Threads — чтобы отделить ЖИВОЙ отклик людей от self-тредов.

Метрика `replies` из insights считает ВСЕ ответы, включая твои собственные (когда сам
разворачиваешь ветку 1→2→4→5). Как сигнал «зашло ли людям» это врёт. Здесь тянем реальные
ответы и считаем только чужие (автор ≠ владелец).

Право: threads_manage_replies (уже в скоупах auth.py). Эндпоинт {media-id}/conversation —
весь тред ответов плоским списком; у каждого ответа есть is_reply_owned_by_me (свой/чужой).
Подстраховка: если это поле не придёт — сверяем username с ником владельца.
"""
from __future__ import annotations

from connectors.threads import _api, auth

# Минимум полей для подсчёта: кто автор (свой/чужой) и статус.
_FIELDS = "id,username,is_reply_owned_by_me,hide_status,timestamp"
_HARD_CAP = 1000   # предохранитель от бесконечной пагинации по огромным тредам

_owner_username: str | None = None


def _owner() -> str:
    """Ник владельца (кэш на процесс) — запасной способ отличить свой ответ от чужого."""
    global _owner_username
    if _owner_username is None:
        try:
            me = _api.get("me", {"fields": "id,username"}, token=auth.valid_token())
            _owner_username = (me.get("username") or "").lower()
        except _api.ThreadsError:
            _owner_username = ""
    return _owner_username


def _is_own(reply: dict) -> bool:
    flag = reply.get("is_reply_owned_by_me")
    if isinstance(flag, bool):
        return flag
    # поле не пришло — сверяем ник
    own = _owner()
    return bool(own) and (reply.get("username") or "").lower() == own


def conversation(media_id: str) -> list[dict]:
    """Все ответы треда плоским списком (с пагинацией)."""
    token = auth.valid_token()
    out: list[dict] = []
    after: str | None = None
    while len(out) < _HARD_CAP:
        page = _api.get(f"{media_id}/conversation", {
            "fields": _FIELDS, "limit": 100, "after": after,
        }, token=token)
        rows = page.get("data") or []
        out.extend(rows)
        after = ((page.get("paging") or {}).get("cursors") or {}).get("after")
        if not rows or not after:
            break
    return out


def audience_for(media_id: str) -> dict:
    """Разбор комментов поста: {people_replies, people_count, self_replies, error?}.

    people_replies — сколько ответов от ДРУГИХ людей (главный честный сигнал);
    people_count   — сколько РАЗНЫХ людей отписалось (шире = живее);
    self_replies   — сколько своих ответов (длина self-треда, для контекста).
    """
    try:
        rows = conversation(media_id)
    except _api.ThreadsError as e:
        return {"people_replies": 0, "people_count": 0, "self_replies": 0, "error": str(e)}
    people, selfr, names = 0, 0, set()
    for r in rows:
        if _is_own(r):
            selfr += 1
        else:
            people += 1
            u = r.get("username")
            if u:
                names.add(u.lower())
    return {"people_replies": people, "people_count": len(names) or (1 if people else 0),
            "self_replies": selfr, "error": None}


def audience_for_many(media_ids: list[str]) -> dict[str, dict]:
    """Разбор комментов для набора постов: {media_id: {...}}. Ошибка по одному не роняет остальные."""
    return {mid: audience_for(mid) for mid in media_ids}


if __name__ == "__main__":
    # Само-тест на ОДНОМ посте — проверка, что /conversation и is_reply_owned_by_me живые.
    # id указывать НЕ надо: сам возьмёт пост с комментами из data/threads_posts.json.
    # (можно и вручную: python -m connectors.threads.replies <media_id>)
    import json
    import sys
    from pathlib import Path

    if len(sys.argv) > 1:
        mid = sys.argv[1]
    else:
        posts_file = Path(__file__).resolve().parents[2] / "data" / "threads_posts.json"
        if not posts_file.exists():
            raise SystemExit("Нет data/threads_posts.json — сначала: python -m connectors.threads.collect")
        posts = json.loads(posts_file.read_text(encoding="utf-8"))
        cand = next((p for p in posts if (p.get("replies") or 0) > 0 and p.get("id")), None)
        if not cand:
            raise SystemExit("В данных нет постов с комментами для теста — можно сразу: collect")
        mid = cand["id"]
        print(f"Беру для теста пост id={mid} (ответов по метрике: {cand.get('replies')})\n")

    raw = conversation(mid)
    print(f"Всего ответов в треде: {len(raw)}")
    if raw:
        print(f"Пример ответа (поля): {raw[0]}")
    print(f"Разбор: {audience_for(mid)}")
