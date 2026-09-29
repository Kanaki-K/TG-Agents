"""Переписать 🔭-пост ПО ЗАДАННОЙ ТЕМЕ с чистого листа — без Скаута, гейта темы и публикации.

    python rewrite_scope.py "BIP-110 отклонён 97.47% хэшрейта: почему неизменяемость Bitcoin — актив"
    python rewrite_scope.py "..." --weak "механика самого BIP не верифицирована из первоисточника"
    python rewrite_scope.py "..." --no-verify      # без веб-2FA (дешевле ~$0.2, факты не сверяются)

ЗАЧЕМ. Прогон `run_pipeline.py --scope` каждый раз выбирает тему заново, и повторный запуск по ТОЙ ЖЕ
теме невозможен: анти-повтор увидит уже поставленный в отложку пост и уведёт writer на другой повод.
Этот скрипт нужен ровно для одного случая — «тема правильная, письмо не устроило, перепиши заново»
(например, после смены модели: сравнить подачу Sonnet и Opus на ОДНОМ поводе).

ЧИСТЫЙ ЛИСТ — НЕ ДЕКЛАРАЦИЯ, А УСТРОЙСТВО. Прошлый драфт не попадает в контекст письма ни при каком
запуске: `_system()` scope собирается из персоны + voice_core + scope_manual + банка заголовков +
brand + scope_lessons, а задание — из TASK + брифа Скаута. Готовых постов там нет. Единственный
канал, которым прошлая попытка могла бы повлиять на новую, — это `avoid` анти-повтора; здесь он
пуст намеренно, иначе повтор темы был бы запрещён. Прошлый драфт остаётся в memory/drafts/ как файл,
но модель его не видит.

ЧТО ДЕЛАЕТ: письмо scope по заданному поводу (write) → веб-2FA с Тир-1 и прицельная правка фактов,
как в пайплайне → обложка из первоисточника. ЧЕГО НЕ ДЕЛАЕТ: не зовёт Скаута, не выбирает тему, НЕ
ставит в отложку. Готовый пост печатается и лежит в драфте — поставить в канал можно ботом
`/schedule`. Если предыдущая версия УЖЕ в «Отложенных» канала — удали её там руками, иначе выйдут обе.
"""
import concurrent.futures
import sys

from core import config, cost, creator_tools, logging_setup, runmode, scope_writer, verify

logging_setup.setup()


def _threaded(fn, *args):
    """Как в run_pipeline: тяжёлое — в отдельном потоке (event-loop для коннекторов на Windows)."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(fn, *args).result()


def _arg(flag: str) -> str:
    """Значение --flag из argv ('' если флага нет)."""
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and sys.argv.index(flag) + 1 < len(sys.argv) else ""


def main() -> None:
    topic = next((a for a in sys.argv[1:] if not a.startswith("--")), "")
    if not topic:
        print(__doc__)
        sys.exit(1)
    weak = _arg("--weak")
    do_verify = "--no-verify" not in sys.argv

    cost.reset()
    model = runmode.resolve(scope_writer.SCOPE_MODEL, ceiling=scope_writer.SCOPE_MODEL)
    print(f"=== 🔭 Переписываю по заданной теме (модель {model}) ===")
    print(f"    тема: {topic}\n")
    if model != scope_writer.SCOPE_MODEL:
        print(f"⚠️ Идёт НЕ боевая модель (тест-режим/override). Боевая: {scope_writer.SCOPE_MODEL} — /main\n")

    # avoid="" НАМЕРЕННО: анти-повтор запретил бы ровно ту тему, ради которой мы и запускаемся.
    # verify_facts=False: 2FA делаем ниже с ВЕБ-сверкой (Тир-1), как в пайплайне, а не по брифу.
    post = _threaded(scope_writer.write, "", "", topic, weak, False)
    if not (post or "").strip():
        print("❌ Пост не сделан (модель вернула пусто).")
        sys.exit(2)

    if do_verify:
        key = config.agent_api_key(config.load_agent("creator"))
        try:
            sv = verify.verify_post(verify.latest_draft(), verify.latest_brief(), api_key=key,
                                    scope=True, web=True)
            print("🔎 [2FA scope · ВЕБ-сверка с Тир-1]\n" + str(sv) + "\n")
            # Полнота ряда — владельцу, не в авто-правку (правило 05.08, см. run_pipeline): дописывать
            # участников решает человек. Правим только конфликты/невериф. цифры.
            if verify.has_issues(sv) and not verify.only_completeness(sv):
                print("🛠 Правлю факты по ВЕБ-проверенным значениям:")
                post = _threaded(scope_writer.fix_facts, verify.strip_completeness(sv), key) or post
        except Exception as e:  # фейл-открыто: 2FA упал — пост не теряем
            print(f"⚠️ 2FA не удался ({e}) — пост отдаю как есть.")

    print("\n📝 --- ГОТОВЫЙ ПОСТ ---")
    print((verify.latest_draft() or post).split("[[SPLIT]]")[0].strip())
    cover = creator_tools.SCOPE_COVER.read_text(encoding="utf-8").strip() \
        if creator_tools.SCOPE_COVER.exists() else ""
    print(f"\n🖼 Обложка: {cover or '— (не нашлась, пост уйдёт текстом)'}")
    print("\n➡️ В канал не ставил. Нравится — поставь ботом /schedule. Старая версия могла остаться "
          "в «Отложенных» канала: удали её там, иначе выйдут обе.")
    print("\n" + cost.summary())


if __name__ == "__main__":
    main()
