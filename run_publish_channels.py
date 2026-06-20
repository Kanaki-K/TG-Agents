"""Показать каналы, где аккаунт-публикатор (ЕвгенийП) владелец/админ — с их ID.

    python run_publish_channels.py

Зачем: имя вроде «test_k» может совпасть с ЧУЖИМ публичным каналом, и userbot пишет не туда
(ChatWriteForbidden). Числовой id однозначен. Найди в списке свой «Тест!», скопируй его id
(вида -100…) и впиши в .env: PUBLISH_CHANNEL=-100…  — тогда публикуем гарантированно в него.

Печатает: id · название · @username · твой статус (владелец/админ) · можно ли постить.
"""
import asyncio

from connectors.telegram_export.collect import _client


async def run() -> None:
    client = _client()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            print("❌ Сессия не авторизована (TELEGRAM_SESSION / data/evgeniyp.session).")
            return
        me = await client.get_me()
        who = f"@{me.username}" if getattr(me, "username", None) else (me.first_name or "?")
        print(f"Аккаунт-публикатор: {who}\n")
        print("Каналы, где ты владелец/админ — бери id для PUBLISH_CHANNEL:")
        found = False
        async for d in client.iter_dialogs():
            if not getattr(d, "is_channel", False):
                continue
            e = d.entity
            creator = bool(getattr(e, "creator", False))
            rights = getattr(e, "admin_rights", None)
            can_post = creator or bool(getattr(rights, "post_messages", False))
            if not (creator or rights):
                continue  # только где ты владелец/админ
            found = True
            role = "ВЛАДЕЛЕЦ" if creator else "админ"
            post = "постить можно ✅" if can_post else "БЕЗ права постить ⚠"
            uname = getattr(e, "username", None)
            print(f"  id={d.id}  «{d.title}»  @{uname or '—'}  [{role}, {post}]")
        if not found:
            print("  (ничего не нашёл — аккаунт не владелец/админ ни одного канала?)")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(run())
