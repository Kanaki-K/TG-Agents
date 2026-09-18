"""Гейт публикации ФЛАГМАНА — три дыры одной цепи, найденные на прогоне 18.09.2026.

Пост «12 слов» вышел хороший, и именно поэтому разбор был полезен: дефекты были не в тексте, а в
проверках вокруг него, и все три молчали.

1. ФОРМАТ НЕ ПЕРЕДАВАЛСЯ В ГЕЙТ. `publish_blockers(_final, "scope" if scope else "")` — а все
   флагманские правила линтера включены условием «формат содержит „флагман“». Значит единственный
   жёсткий запрет флагмана («>4096 — Telegram порвёт пост на два сообщения») не мог сработать ни разу.
   Замер на живом посте: пустой формат — 1 замечание, «флагман» — 2, включая «у СТЕНЫ: 4044 знака».
2. КРУГ ПОЧИНКИ БЫЛ ЧУЖОЙ. На оба формата звался `scope_writer.fix_blockers`, а он читает
   `latest_draft("scope")`: на флагмане круг взял бы последний СКОУП и переписал бы его скоуп-сводом.
   Дыра не всплывала только потому, что дыра №1 не давала гейту ничего найти.
3. МЕТА НЕ ДОЕЗЖАЛА ДО ЖУРНАЛА. `record()` читает [[УЗЕЛ]]/[[ТИП]]/[[ВЫХОД]] из первого аргумента, а
   пайплайн передавал туда реплику модели в чат — при том что круг меты сам велит писателю ответить
   одной строкой. Итог 18.09: тип услуги в журнале «линза» (фолбэк пикера) вместо реального
   «механизм», пустой узел — и Threads-ветка осталась без входа.
"""
import inspect

import run_pipeline as rp
from core import creator_bot, creator_tools, published_journal


def _post(n: int) -> str:
    """Флагман нужной длины с футером — чтобы срабатывала длина, а не отсутствие футера."""
    body = "**🔒 Заголовок поста про кошельки**\n\n" + ("Обычная строка разбора без разметки. " * 400)
    footer = "\n\n🖥 [Канал](https://t.me/x) | 📱 [Notion](https://notion.so/x)"
    return body[:n] + footer


def test_length_blocker_fires_only_when_format_is_passed():
    """Тот же текст: с форматом «флагман» гейт его блокирует, с пустым — пропускает молча."""
    huge = _post(4300)
    assert creator_tools.publish_blockers(huge, "флагман"), "запрет >4096 не сработал на флагмане"
    assert not creator_tools.publish_blockers(huge, ""), "тест устарел: пустой формат больше не слеп"


def test_pipeline_passes_flagship_format_to_the_gate():
    """Регресс-сторож дыры №1: формат в гейт передаётся явно, оба раза."""
    src = inspect.getsource(rp.run_cycle)
    assert 'publish_blockers(_final, "scope" if scope else "")' not in src, "формат снова потерян"
    assert src.count('publish_blockers(_final, "scope" if scope else "флагман")') == 2, \
        "гейт и его перепроверка должны знать формат"


def test_blockers_round_is_per_format():
    """Регресс-сторож дыры №2: скоуп чинит scope_writer, флагман — своя персона и СВОЙ драфт."""
    src = inspect.getsource(rp.run_cycle)
    assert "scope_writer.fix_blockers, _blockers, fkey) if scope" in src, "круг скоупа снова на обоих"
    assert "_run_creator_blockers(_final, _blockers)" in src
    own = inspect.getsource(rp._run_creator_blockers)
    assert 'latest_draft("flagship")' in own, "круг флагмана обязан читать флагманский драфт"
    assert "[[SPLIT]]" in creator_bot.FIX_BLOCKERS, "круг правок обязан требовать перенос меты"


def test_journal_takes_meta_from_the_draft_not_from_the_chat_reply(tmp_path, monkeypatch):
    """Регресс-сторож дыры №3: мета читается из драфта, тело — из квитанции канала."""
    monkeypatch.setattr(published_journal, "JOURNAL", tmp_path / "published_posts.jsonl")
    monkeypatch.setattr(published_journal, "LEGACY_JOURNAL", tmp_path / "published_flagships.jsonl")
    body = "**🔒 Заголовок**\n\nТело поста, которое ушло в канал"
    draft = (body + "\n\n[[SPLIT]]\n[[УЗЕЛ]] мысль, которая живёт сама и понятна без крипты\n"
             "[[ТИП]] механизм\n[[ВЫХОД]] читатель завтра выберет кошелёк по второму вопросу")
    published_journal.record(draft, "тема", tg={"text": body, "msg_id": 1})
    row = published_journal.entries("flagship")[-1]
    assert row["service"] == "механизм", "тип услуги снова берётся не из меты — ротация ослепнет"
    assert row["nodes"] and row["exit"], "узел/выход потеряны — Threads-ветка останется без входа"
    assert "[[SPLIT]]" not in row["text"], "мета не должна попадать в тело поста"

    src = inspect.getsource(rp.run_cycle)
    assert src.count("published_journal.record(_final or post") == 2, "в журнал снова уходит чат-ответ"
