"""ПРАВИЛЬНЫЙ линкер: собранный Threads-пост → дистилляция (журнал) → флагман/категория.

Ключевая идея (в отличие от threads_flagship_link, который сверял пост с ПЕРЕПИСАННЫМ текстом
флагмана): журнал дистилляций хранит ТОЧНЫЙ текст серии, которую опубликовали. Значит связь ищем
по нему — совпадение почти идеальное (пост ≈ его же сгенерированный текст ± мелкие правки владельца),
а не по угадыванию поверх переписывания. Две ступени надёжности:

1. **ID** — если авто-публикация записала id постов в журнал → связь детерминированная, без сверки.
2. **Тугой текст** — иначе сверяем текст поста с текстом поста серии из журнала (порог высокий).

До-журнальные дистилляции (журнал завели позже публикации) сюда НЕ попадут — их подхватывает
запасной threads_flagship_link (фаззи по флагману). Слои деградируют мягко: ID → журнал → флагман.
"""
from __future__ import annotations

from core import text_match

TIGHT = 0.55      # пост ≈ его же текст серии → покрытие высокое; ниже — не та серия


def link(entries: list[dict], threads_posts: list[dict], tight: float = TIGHT) -> dict:
    """Сматчить посты с записями журнала дистилляций.

    Возвращает {"groups": [...], "unmatched": [...]}. group = {"entry": e, "posts":
    [{"post": p, "coverage": float, "via": "id"|"text"}]}. Каждый пост — максимум к ОДНОЙ записи."""
    by_id: dict[str, dict] = {}
    for e in entries:
        for pid in e.get("post_ids") or []:
            by_id[str(pid)] = e

    idx = {id(e): i for i, e in enumerate(entries)}
    groups: dict[int, dict] = {}
    unmatched: list[dict] = []

    def _add(e: dict, post: dict, cov: float, via: str) -> None:
        g = groups.setdefault(idx[id(e)], {"entry": e, "posts": []})
        g["posts"].append({"post": post, "coverage": cov, "via": via})

    for p in threads_posts:
        pid = str(p.get("id", ""))
        if pid and pid in by_id:                       # ступень 1: детерминированно по ID
            _add(by_id[pid], p, 1.0, "id")
            continue
        best_e, best_cov = None, 0.0                   # ступень 2: тугой текст серии
        for e in entries:
            for jp in e.get("posts") or []:
                cov = text_match.coverage(p.get("text", ""), jp)
                if cov > best_cov:
                    best_cov, best_e = cov, e
        if best_e is not None and best_cov >= tight:
            _add(best_e, p, round(best_cov, 2), "text")
        else:
            unmatched.append(p)

    return {"groups": list(groups.values()), "unmatched": unmatched}
