"""Разовый вход бёрнер-аккаунта ChatGPT — помощник коннектора картинок.

Зачем именно так: у ChatGPT нет бесплатного API на картинки и нет входа по QR (как в ТГ).
Бесплатный рендер берём с РАСХОДНОГО (бёрнер) аккаунта через веб (Playwright). ChatGPT за
Cloudflare, который привязывает сессию к отпечатку браузера — поэтому логинимся в ТОМ ЖЕ
браузере, что потом рендерит, а не копируем куки из другого (как у X). Сессия — в постоянном
профиле data/gpt_profile/ (папка data/ в .gitignore = секрет сессии не уедет в git).

Как войти (один раз), на машине, где запускаешь ботов:
    python -m connectors.gpt_image.login
Откроется ОКНО браузера на твоём экране. Войди почтой+паролем (+код, если спросит),
дождись, пока откроется чат ChatGPT, и нажми Enter в терминале. Профиль сохранится —
дальше рендер идёт сам. Это РАСХОДНЫЙ аккаунт, не личный (на случай бана за автоматизацию).

Проверить, что сессия жива (без перелогина):
    python -m connectors.gpt_image.login check
"""
from __future__ import annotations

import sys
import time

from connectors.gpt_image import generate as gen  # берём оттуда профиль/URL/проверку входа


def _open_login(timeout_s: int = 300) -> None:
    """Открыть окно браузера и ДОЖДАТЬСЯ ручного входа, опрашивая страницу.

    Сознательно НЕ просим жать Enter в терминале: при запуске из IDE/обёртки stdin
    бывает неинтерактивным, input() ловит EOFError и окно закрывается через секунду.
    Поэтому скрипт сам ловит момент входа (появилось поле ввода чата) и закрывается.
    """
    from playwright.sync_api import sync_playwright

    gen.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = gen.launch_context(p, headless=False)  # вход всегда видимый — вводишь руками
        ok = False
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(gen.CHATGPT_URL, wait_until="domcontentloaded")
            print("Открылось окно браузера. Войди в БЁРНЕР-аккаунт ChatGPT")
            print("(почта+пароль, код из почты если спросит).")
            print(f"Как откроется чат — поймаю сам и закрою окно (жду до {timeout_s // 60} мин).")
            print("Окно руками НЕ закрывай — закрою сам, когда увижу вход.")
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                try:
                    if gen.is_logged_in(page, wait_ms=3000):
                        ok = True
                        break
                except Exception:
                    break  # окно закрыли руками или вкладка умерла
                time.sleep(2)
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    if ok:
        print(f"✓ Сессия сохранена в {gen.PROFILE_DIR} — рендер картинок готов.")
        print("  Напоминание: это должен быть РАСХОДНЫЙ аккаунт, не личный.")
    else:
        print("✗ Не дождался входа (таймаут или окно закрыто). Запусти ещё раз.")


def _check() -> None:
    from playwright.sync_api import sync_playwright

    if not gen.PROFILE_DIR.exists():
        print("✗ Профиля нет. Сначала войди: python -m connectors.gpt_image.login")
        return
    with sync_playwright() as p:
        ctx = gen.launch_context(p, headless=gen.HEADLESS)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(gen.CHATGPT_URL, wait_until="domcontentloaded")
            ok = gen.is_logged_in(page)
        finally:
            ctx.close()
    print("✓ Сессия ChatGPT жива — рендер готов." if ok
          else "✗ Сессия протухла — перелогинься: python -m connectors.gpt_image.login")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        _check()
    else:
        _open_login()
