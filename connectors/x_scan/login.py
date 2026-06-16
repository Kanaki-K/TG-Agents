"""Проверка X-сессии бёрнера — разовый помощник Скаута.

Доступ к X у Скаута — read-only через cookies РАСХОДНОГО (бёрнер) аккаунта, НЕ личного
(у неофициального доступа есть риск заморозки/бана). Через вход с Google twikit ходить
не умеет — поэтому используем готовую сессию из браузера.

Где взять cookies (один раз):
  1. Залогинься бёрнером в X в браузере.
  2. Открой DevTools (F12) → вкладка Application/«Хранилище» → Cookies → https://x.com
  3. Скопируй значения двух cookies: auth_token и ct0
  4. Впиши их в .env как X_AUTH_TOKEN и X_CT0

Проверить, что сессия рабочая:
    python -m connectors.x_scan.login

Выгрузить список подписок бёрнера (чтобы скурировать leaders.yaml из реальных follow):
    python -m connectors.x_scan.login follows

Печатает имя залогиненного аккаунта — либо понятную ошибку (cookies протухли и т.п.).
"""
from __future__ import annotations

import asyncio
import sys

from connectors.x_scan import read as x_read


async def _check() -> None:
    """Проверяем то, что реально делает Скаут — ЧТЕНИЕ твитов лидера.

    Не используем client.user() для теста: на свежем бёрнере с пустым профилем
    twikit спотыкается о парсинг профиля ('urls') — но к чтению чужих твитов это
    не относится. KEY_BYTE у X плавает (вариативная выдача), поэтому пара ретраев.
    """
    leaders = x_read.load_leaders()
    handle = leaders[0]["handle"] if leaders else "Twitter"
    last_err = None
    for attempt in range(1, 4):
        client, err = x_read._make_client()
        if err:
            print("✗", err)
            return
        try:
            user = await client.get_user_by_screen_name(handle)
            tweets = await user.get_tweets("Tweets", count=1)
            n = len(list(tweets))
            print(f"✓ X-сессия рабочая: чтение X работает (прочитал твиты @{handle}, получено {n}).")
            print("  Скаут готов читать X. Напоминание: это должен быть РАСХОДНЫЙ аккаунт, не личный.")
            return
        except Exception as e:
            last_err = e
            if "KEY_BYTE" in str(e):  # плавающий разлад фронта X — пробуем ещё раз
                print(f"  …попытка {attempt}: X отдал неподходящую страницу (KEY_BYTE), повторяю…")
                continue
            break
    print(f"✗ Чтение не удалось: {last_err}")
    print("  Если ошибка про KEY_BYTE повторяется стабильно — X снова сменил фронт; скажи мне, обновлю патч.")
    print("  Если про cookies/авторизацию — пере-логинься бёрнером в браузере и обнови X_AUTH_TOKEN/X_CT0 в .env.")


def _dump_following() -> None:
    rows = x_read.following()
    if rows and rows[0].get("error"):
        print("✗", rows[0]["error"])
        return
    print(f"Подписок получено: {len(rows)}. Скопируй и пришли мне — соберу leaders.yaml.\n")
    for r in rows:
        foll = r.get("followers")
        foll_s = f"{foll:,}".replace(",", " ") if isinstance(foll, int) else "?"
        print(f"@{r['handle']}  ({r.get('name','')}, подписчиков: {foll_s})")
        if r.get("description"):
            print(f"    {r['description']}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "follows":
        _dump_following()
    else:
        asyncio.run(_check())
