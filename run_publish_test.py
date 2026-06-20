"""Разовый тест МОТОРА публикации — БЕЗ бота. Ставит тест-пост в отложенные PUBLISH_CHANNEL.

    python run_publish_test.py [путь_к_картинке]

Берёт канал и сессию из .env, считает слот по контент-плану и ставит нативный ОТЛОЖЕННЫЙ пост
аккаунтом-публикатором (ЕвгенийП). Печатает режим, слот и ссылку/ошибку. После запуска открой
«Отложенные» канала и проверь, что пост лёг как надо (с обложкой — фото + текст).

Это проверка движка в изоляции, до того как вшивать его в Криейтора. Пост можно удалить из
отложенных руками — в эфир он сам не уйдёт раньше слота.
"""
import sys

from connectors.telegram_publish import publish
from core import config, content_plan

SAMPLE = (
    "Тест Публикатора (мотор без бота).\n\n"
    "Проверяем, что аккаунт-публикатор кладёт пост в «Отложенные» канала нативно — фото сверху, "
    "текст под ним — на слот из контент-плана (ритм недели). Если ты видишь это в отложенных "
    "канала именно так — движок работает, можно вшивать его в Криейтора.\n\n"
    "Это просто тест — удали из отложенных."
)


def main() -> None:
    channel = config.get_optional("PUBLISH_CHANNEL")
    if not channel:
        print("❌ PUBLISH_CHANNEL не задан в .env — некуда ставить.")
        return
    cover = sys.argv[1] if len(sys.argv) > 1 else None
    kind = content_plan.infer_kind(SAMPLE)
    slot = content_plan.next_slot(kind)
    print(f"Канал: {channel}")
    print(f"Пояс: {content_plan.tz_label()}")
    print(f"Слот: {content_plan.human(slot)} ({content_plan.kind_label(kind)})")
    print(f"Обложка: {cover or 'нет (только текст)'}")
    res = publish.publish(channel, SAMPLE, cover, slot)
    if res.get("ok"):
        print(f"✅ Поставлено в отложенные ({res.get('mode', '?')}). Проверь «Отложенные» канала.")
    else:
        print(f"❌ Ошибка: {res.get('error', '?')}")


if __name__ == "__main__":
    main()
