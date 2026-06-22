"""Рендер картинки для флагман-поста через веб-интерфейс ChatGPT бёрнера — «руки» Криейтора.

Почему так (а не API): платный API на картинки владелец не оплачивает; берём бесплатный
рендер с РАСХОДНОГО (бёрнер) аккаунта ChatGPT через его веб (Playwright). Лимита
«несколько в день» хватает — на флагман нужна одна картинка. Вход разовый, руками: см.
login.py. Сессия лежит в постоянном профиле data/gpt_profile/ (папка data/ уже в .gitignore).

ВАЖНО про IP: ChatGPT за Cloudflare, который привязывает сессию к браузеру и его IP.
Поэтому рендерим с той же машины и тем же профилем, где входили. Это РАСХОДНЫЙ аккаунт —
автоматизация веба серая по ToS, личный не подставляем.

Функция generate() — СИНХРОННАЯ (как x_scan.recent): из бота зови через asyncio.to_thread.
Бросает RuntimeError с понятным текстом (не залогинен / лимит / таймаут).
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from core import config  # импорт грузит .env (load_dotenv)

ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = ROOT / "data" / "gpt_profile"   # постоянный профиль с сессией бёрнера (data/ = gitignore)
OUT_DIR = ROOT / "data" / "gpt_images"        # сюда складываем отрендеренные PNG (тоже вне git)
CHATGPT_URL = "https://chatgpt.com/"

# По умолчанию окно видно (нужно для разового логина и удобно при отладке). Для фонового
# рендера поставь GPT_IMAGE_HEADLESS=1 в .env. Если Cloudflare начнёт резать скрытый режим —
# верни видимый.
HEADLESS = config.get_optional("GPT_IMAGE_HEADLESS").lower() in ("1", "true", "yes")

# --- Селекторы веб-ChatGPT. ХРУПКО: UI ChatGPT меняется. Поле ввода стабильно; готовую
#     картинку НЕ ищем по URL (он плавает, бывает blob:) — берём самую крупную картинку в
#     ответе и снимаем её скриншотом элемента (см. _capture_image). ---
SEL_COMPOSER = "#prompt-textarea"                          # поле ввода сообщения (contenteditable)
SEL_GENERATING = "button[data-testid='stop-button']"       # пока жива кнопка «стоп» — генерация идёт
MIN_IMG_W = 256                                            # обложка крупнее аватарок/иконок (px)


def launch_context(p, headless: bool):
    """Запустить браузер с постоянным профилем бёрнера — общий код для login/generate/check.

    Две хитрости против детекта автоматизации (иначе проверка «вы человек» на входе
    в ChatGPT не грузится и висит):
      • ignore_default_args=['--enable-automation'] — снимаем флаг, по которому палят бота;
      • channel='chrome' — гоняем НАСТОЯЩИЙ установленный Chrome (честный отпечаток), а не
        bundled Chromium. Если Chrome не установлен — откатываемся на Chromium.
    Канал можно переопредилить через GPT_IMAGE_BROWSER_CHANNEL (chrome|msedge|chromium).
    """
    kwargs = dict(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    channel = (config.get_optional("GPT_IMAGE_BROWSER_CHANNEL") or "chrome").lower()
    if channel and channel != "chromium":
        try:
            return p.chromium.launch_persistent_context(channel=channel, **kwargs)
        except Exception:
            pass  # нужного браузера нет — падаем на bundled Chromium ниже
    return p.chromium.launch_persistent_context(**kwargs)


def is_logged_in(page, wait_ms: int = 8000) -> bool:
    """Залогинены ли ПОД АККАУНТОМ. Признак — кука сессии, а НЕ поле ввода.

    Поле #prompt-textarea есть и у гостя (ChatGPT пускает анонимов), поэтому по нему
    нельзя отличить вход от гостевой страницы. Настоящий маркер — кука next-auth
    сессии аккаунта; у гостя её нет.
    """
    try:
        page.wait_for_selector(SEL_COMPOSER, timeout=wait_ms)  # дождаться, что страница ожила
    except Exception:
        pass
    try:
        for c in page.context.cookies():
            if "session-token" in c.get("name", "") and c.get("value"):
                return True
    except Exception:
        pass
    return False


def _goto(page) -> None:
    """Перейти на ChatGPT ТЕРПИМО к net::ERR_ABORTED.

    chatgpt.com часто делает мгновенный редирект, который обрывает первоначальную навигацию —
    Playwright кидает ERR_ABORTED, хотя страница в итоге грузится. Поэтому ждём только 'commit'
    и не паникуем на обрыве, а затем даём DOM догрузиться.
    """
    try:
        page.goto(CHATGPT_URL, wait_until="commit", timeout=60000)
    except Exception:
        pass  # обрыв из-за редиректа — не фатально, ждём загрузку ниже
    try:
        page.wait_for_load_state("domcontentloaded", timeout=30000)
    except Exception:
        pass


def _largest_image(page):
    """Самая КРУПНАЯ картинка в основной области (≥ MIN_IMG_W по ширине) — это и есть обложка.

    Не завязываемся на URL (он плавает, бывает blob:). Возвращаем (locator, площадь) или (None, 0).
    """
    imgs = page.locator("main img")
    best, best_area = None, 0
    for i in range(imgs.count()):
        el = imgs.nth(i)
        try:
            box = el.bounding_box()
        except Exception:
            box = None
        if box and box["width"] >= MIN_IMG_W:
            area = box["width"] * box["height"]
            if area > best_area:
                best, best_area = el, area
    return best, best_area


def _dump_diagnostics(page) -> None:
    """Сложить диагностику, чтобы поправить захват без лишних генераций (бережём лимит)."""
    try:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "debug_page.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        page.screenshot(path=str(OUT_DIR / "debug_page.png"), full_page=True)
    except Exception:
        pass
    try:
        srcs = page.eval_on_selector_all("main img", "els => els.map(e => e.src)")
        (OUT_DIR / "debug_imgs.txt").write_text("\n".join(srcs), encoding="utf-8")
    except Exception:
        pass


def _download_via_button(page, el, out: Path) -> bool:
    """Скачать ОРИГИНАЛ файлом через кнопку «Скачать» ChatGPT (на случай blob:-картинки).

    Открываем картинку кликом (обычно вылезает просмотрщик с кнопкой загрузки) и перехватываем
    скачивание (expect_download) — это настоящий файл, без потери качества. True если получилось.
    """
    try:
        el.click()
        time.sleep(1.5)
    except Exception:
        pass
    for sel in ("[data-testid='download-button']",
                "button[aria-label*='Download' i]", "a[aria-label*='Download' i]",
                "button[aria-label*='Скачать' i]", "[aria-label*='Скачать' i]"):
        loc = page.locator(sel)
        if not loc.count():
            continue
        try:
            with page.expect_download(timeout=15000) as dl:
                loc.first.click()
            dl.value.save_as(str(out))
            return True
        except Exception:
            continue
    return False


def _capture_image(page, ctx, out: Path, timeout_s: int) -> Path:
    """Дождаться готовой обложки и СКАЧАТЬ её ФАЙЛОМ в оригинале (без потери качества).

    Порядок: (1) скачать по URL картинки той же сессией — это оригинальный файл; (2) если картинка
    отдаётся как blob: — скачать кнопкой «Скачать» в интерфейсе. Скриншотом НЕ подменяем (потеря
    качества). Чтобы не схватить на полпути: ждём, пока пропадёт «стоп» И картинка продержится 2 опроса.
    """
    deadline = time.monotonic() + timeout_s
    stable = 0
    while time.monotonic() < deadline:
        generating = page.locator(SEL_GENERATING).count()
        el, _ = _largest_image(page)
        if el is not None and not generating:
            stable += 1
            if stable >= 2:                       # картинка держится → точно дорендерилось
                src = el.get_attribute("src") or ""
                if src.startswith("http"):        # 1) подписанный URL — качаем оригинал той же сессией
                    try:
                        out.write_bytes(ctx.request.get(src).body())
                        return out
                    except Exception:
                        pass                      # упало — пробуем кнопку «Скачать» ниже
                if _download_via_button(page, el, out):  # 2) blob: или фетч не вышел — файлом из UI
                    return out
        else:
            stable = 0
        time.sleep(2)
    _dump_diagnostics(page)
    raise RuntimeError(
        f"Картинка не скачалась за {timeout_s}с. Возможно: исчерпан дневной лимит бёрнера, "
        f"ChatGPT ответил текстом вместо картинки, либо сменилась вёрстка. Сложил диагностику в "
        f"{OUT_DIR} (debug_page.png + debug_imgs.txt) — пришли их, поправлю захват."
    )


def _stub_image() -> Path | None:
    """ТЕСТОВЫЙ режим (GPT_IMAGE_STUB): вернуть УЖЕ готовую картинку, не дёргая ChatGPT.

    Бережёт дневной лимит бёрнера, когда тестируем доставку, а не генерацию. Значение флага:
    путь к картинке (абсолютный или от корня репо), либо 1/true/yes = взять самую свежую PNG
    из data/gpt_images/. Пусто — обычная генерация.
    """
    val = config.get_optional("GPT_IMAGE_STUB").strip()
    if not val:
        return None
    if val.lower() not in ("1", "true", "yes"):
        p = Path(val)
        p = p if p.is_absolute() else ROOT / val
        return p if p.exists() else None
    if OUT_DIR.exists():  # самая свежая картинка (кроме debug_*)
        pics = sorted((f for f in OUT_DIR.glob("*.png") if not f.name.startswith("debug")),
                      key=lambda f: f.stat().st_mtime, reverse=True)
        if pics:
            return pics[0]
    return None


def generate(prompt: str, out_name: str = "flagship.png", timeout_s: int = 180) -> Path:
    """Сгенерировать картинку по промпту через веб-ChatGPT бёрнера. Вернёт путь к PNG.

    prompt — собирается Криейтором из присланного владельцем шаблона + темы поста.
    """
    stub = _stub_image()
    if stub is not None:  # тестовый режим: отдаём готовую картинку, ChatGPT не трогаем
        return stub
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "playwright не установлен — на машине, где запускаешь бота: "
            "pip install playwright && playwright install chromium"
        ) from e
    if not PROFILE_DIR.exists():
        raise RuntimeError(
            "Нет сессии ChatGPT. Войди бёрнером один раз: python -m connectors.gpt_image.login"
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # playwright запускает браузер ПОДПРОЦЕССОМ — на Windows это умеет только ProactorEventLoop.
    # В этом потоке политика могла остаться Selector (в run_pipeline после Скаута/telethon в одном
    # процессе) → sync_playwright падал с NotImplementedError, обложка не рисовалась, и в канал
    # уходила СТАРАЯ картинка (инцидент 22.06). Ставим Proactor в самой точке использования —
    # надёжно при любой причине; бот не ломаем (там политика и так Proactor).
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    with sync_playwright() as p:
        ctx = launch_context(p, headless=HEADLESS)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            _goto(page)
            if not is_logged_in(page):
                raise RuntimeError(
                    "Сессия ChatGPT протухла — перелогинься: python -m connectors.gpt_image.login"
                )
            box = page.locator(SEL_COMPOSER)
            box.click()
            box.fill(prompt)
            page.keyboard.press("Enter")
            out = OUT_DIR / out_name
            return _capture_image(page, ctx, out, timeout_s)
        finally:
            ctx.close()


if __name__ == "__main__":  # разовая ручная проверка с живым бёрнером
    import sys

    text = " ".join(sys.argv[1:]) or (
        "Сгенерируй изображение: минималистичная обложка про крипту, тёмно-синий фон, "
        "золотая монета BTC со свечением, без текста"
    )
    print("Рендерю картинку…")
    print("✓ Готово:", generate(text))
