"""Снять пост из нативных «Отложенных» канала — руками, из терминала.

ЗАЧЕМ. 12.09.2026 завод поставил в отложку пост, который владелец забраковал целиком («заголовок
дерьмище, финал дерьмище, пользы 0»). Поставить завод умел, снять — нет, и отменять свою же ошибку
приходилось в клиенте. Теперь отмена живёт там же, где публикация.

ПРЕДОХРАНИТЕЛИ (удаление необратимо):
  · без --yes скрипт НИЧЕГО не удаляет — только показывает, что снял бы;
  · сначала печатает id, слот и первую строку поста, чтобы было видно, ту ли вещь снимаем;
  · пайплайн эту команду не вызывает и вызывать не должен: снимать чужое решение — дело человека.

Запуск:
  python tools/cancel_scheduled.py                 # показать отложку
  python tools/cancel_scheduled.py --last          # показать, что снял бы (НЕ снимает)
  python tools/cancel_scheduled.py --last --yes    # снять последний поставленный
  python tools/cancel_scheduled.py --id 123 --yes  # снять конкретный
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from connectors.telegram_publish import publish       # noqa: E402
from core import config                               # noqa: E402


def _fmt(row: dict) -> str:
    when = row.get("date")
    when = when.strftime("%d.%m %H:%M UTC") if when else "без слота"
    first = (row.get("text") or "").splitlines()[0] if row.get("text") else "(без текста)"
    return f"  id={row['id']:<8} {when:<18} {first[:70]}"


def main() -> int:
    ap = argparse.ArgumentParser(description="снять пост из «Отложенных» канала")
    ap.add_argument("--last", action="store_true", help="цель — последний поставленный (макс. id)")
    ap.add_argument("--id", type=int, default=0, help="цель — конкретный id из списка")
    ap.add_argument("--yes", action="store_true", help="подтвердить удаление (без него — сухой прогон)")
    a = ap.parse_args()

    channel = config.get_optional("PUBLISH_CHANNEL")
    if not channel:
        print("PUBLISH_CHANNEL не задан в конфиге секретов — нечего снимать.")
        return 2
    rows = publish.scheduled_list(channel)
    if not rows:
        print("В отложке канала ничего нет (или нет доступа к MTProto-сессии).")
        return 1
    print(f"В «Отложенных» {len(rows)} сообщ.:")
    for r in sorted(rows, key=lambda x: x["id"]):
        print(_fmt(r))

    if not (a.last or a.id):
        print("\nЦель не выбрана. Добавь --last или --id N (и --yes, чтобы снять).")
        return 0
    target = next((r for r in rows if r["id"] == a.id), None) if a.id else max(rows, key=lambda r: r["id"])
    if target is None:
        print(f"\nid={a.id} в отложке нет — ничего не делаю.")
        return 1
    print("\nЦель:\n" + _fmt(target))
    if not a.yes:
        print("\nСУХОЙ ПРОГОН: ничего не удалено. Повтори с --yes, если это точно тот пост.")
        return 0
    res = publish.cancel_scheduled(channel, target["id"])
    if res.get("ok"):
        print(f"\n✅ Снял id={res['id']}. В отложке осталось: {res.get('left', '?')} сообщ.")
        return 0
    print(f"\n⛔ Не снял: {res.get('error') or 'неизвестная ошибка'}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
