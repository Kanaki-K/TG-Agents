"""Ручная проверка обложки БЕЗ пайплайна: даёшь несколько ссылок-статей + сущности повода → тянем
с каждой ВСЕ кадры (шапка og:image + картинки из тела статьи) → vision ВЫБИРАЕТ подходящий по смыслу
(та же логика, что в scope). Печатает пул и выбор.
Дёшево: без Скаута/Криейтора, один vision-вызов. Так тестируется ИМЕННО отбор картинки под контекст.

Запуск (у себя, в venv):
    python -m connectors.source_media.demo "<url1>" "<url2>" --subject "Saylor, Strategy, MSTR" --topic "Strategy авторизовала продажи BTC"
    python -m connectors.source_media.demo "<url>"          # одна ссылка тоже ок
"""
from __future__ import annotations

import sys

from connectors.source_media import fetch


def _opt(args: list, flag: str) -> str:
    return args[args.index(flag) + 1] if flag in args and len(args) > args.index(flag) + 1 else ""


def main() -> None:
    args = sys.argv[1:]
    urls = [a for a in args if a.startswith(("http://", "https://"))]
    if not urls:
        print('Дай 1+ URL статей: python -m connectors.source_media.demo "<url1>" "<url2>" '
              '--subject "сущности" --topic "тема"')
        return
    subject, topic = _opt(args, "--subject"), _opt(args, "--topic")
    imgs = []
    for i, u in enumerate(urls):
        got = fetch.fetch_source_images(u, name=f"demo_{i}")
        print(f"[{i}] {u}\n     шапка og:image → {fetch.og_image_url(u) or '(нет)'}"
              f"\n     кадры из тела  → {fetch.article_images(u) or '(нет)'}"
              f"\n     скачано годных → {[str(x.name) for x in got] or '(ни одного)'}")
        imgs.extend(got)
    if not imgs:
        print("Итог: ни одной годной картинки — пост ушёл бы без обложки (а значит НЕ вышел бы).")
        return
    from core import config, scope_writer  # ленивый импорт (vision)
    key = config.agent_api_key(config.load_agent("creator"))
    chosen = scope_writer._vision_pick(imgs, topic, subject, key)
    print("\nVISION ВЫБРАЛ:", chosen or "НИ ОДНА не подошла (пост НЕ вышел бы)")


if __name__ == "__main__":
    main()
