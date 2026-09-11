"""Откуда Threads-ветка берёт исходный ТГ-пост: журнал (боевой путь) и выгрузка канала (обкатка).

Живой баг, из-за которого тест и написан: `content_plan.infer_kind` отвечает ИСТОРИЧЕСКИМ именем
формата ('short'), а сравнивали его с каноничным 'scope' — совпадения не было НИКОГДА, и «скоупы в
выгрузке не находились», хотя их там сотня."""
import json

from core import published_journal, threads_source as ts


def _channel(tmp_path, monkeypatch, posts, formats=None, topics=None):
    (tmp_path / "posts.json").write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "formats.json").write_text(json.dumps(formats or {}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "topics.json").write_text(json.dumps(topics or {}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ts, "POSTS_JSON", tmp_path / "posts.json")
    monkeypatch.setattr(ts, "FORMATS_JSON", tmp_path / "formats.json")
    monkeypatch.setattr(ts, "TOPICS_JSON", tmp_path / "topics.json")


def test_picks_nth_post_of_its_format_from_channel(tmp_path, monkeypatch):
    posts = [
        {"id": 1, "date": "2026-08-01T16:00:00", "text": "к" * 1200},          # скоуп (старый)
        {"id": 2, "date": "2026-08-02T16:00:00", "text": "ф" * 3000},          # флагман
        {"id": 3, "date": "2026-08-03T16:00:00", "text": "к" * 1300},          # скоуп (свежий)
    ]
    _channel(tmp_path, monkeypatch, posts, topics={"3": {"title": "Свежий скоуп"}})

    first = ts.from_channel("scope", 1)
    assert first["date"] == "2026-08-03" and first["theme"] == "Свежий скоуп"   # 1 = самый свежий
    assert "#3" in first["origin"]
    assert ts.from_channel("scope", 2)["date"] == "2026-08-01"                  # 2 = предыдущий
    assert ts.from_channel("flagship", 1)["date"] == "2026-08-02"               # формат не путается
    assert ts.from_channel("scope", 9) is None                                  # столько постов нет


def test_service_messages_and_foreign_formats_are_skipped(tmp_path, monkeypatch):
    posts = [
        {"id": 10, "date": "2026-08-01T16:00:00", "text": "🖥 Медиа | 🥸 Мемы"},   # футер-сообщение
        {"id": 11, "date": "2026-08-02T16:00:00", "text": "л" * 900},            # размечен как личный
        {"id": 12, "date": "2026-08-03T16:00:00", "text": "к" * 1000},           # настоящий скоуп
    ]
    _channel(tmp_path, monkeypatch, posts, formats={"11": "личный"})
    picked = ts.from_channel("scope", 1)
    assert picked["text"].startswith("к") and "#12" in picked["origin"]
    assert ts.from_channel("scope", 2) is None                                   # больше кандидатов нет


def _journal(tmp_path, monkeypatch, *rows):
    """Журнал в tmp + фиктивный канал. rows — (текст, квитанция или None[, тема]), старые первыми.
    Уводим ВСЕ пути, которых касается выбор: журнал, копии обложек, журнал переработок."""
    monkeypatch.setattr(published_journal, "JOURNAL", tmp_path / "journal.jsonl")
    monkeypatch.setattr(published_journal, "LEGACY_JOURNAL", tmp_path / "legacy.jsonl")
    monkeypatch.setattr(published_journal, "COVERS_DIR", tmp_path / "published_covers")
    monkeypatch.setattr(ts.threads_distill_journal, "JOURNAL", tmp_path / "distill_none.jsonl")
    monkeypatch.setattr(ts.config, "get_optional", lambda k: "канал" if k == "PUBLISH_CHANNEL" else None)
    for row in rows:
        published_journal.record(row[0], theme=row[2] if len(row) > 2 else "ETF", kind="scope", tg=row[1])


def _distilled(tmp_path, monkeypatch, *records):
    """Журнал переработок: какие ТГ-посты уже превращали в Threads."""
    path = tmp_path / "distill.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    monkeypatch.setattr(ts.threads_distill_journal, "JOURNAL", path)


def _snap(monkeypatch, scheduled=(), recent=(), ok=True):
    """Подменяем чтение канала: в тестах в Telegram не ходим."""
    monkeypatch.setattr(ts, "_snapshot", lambda channel: {"ok": ok, "error": "нет сети",
                                                          "scheduled": list(scheduled), "recent": list(recent)})


def test_resolve_switches_between_journal_and_channel(tmp_path, monkeypatch):
    _journal(tmp_path, monkeypatch, ("Свежий пост из журнала", None))
    _snap(monkeypatch, scheduled=[{"id": 1, "text": "Свежий пост из журнала"}])
    _channel(tmp_path, monkeypatch, [{"id": 5, "date": "2026-08-01T16:00:00", "text": "к" * 1000}])

    assert ts.resolve("scope")["text"] == "Свежий пост из журнала"   # 0 = боевой путь
    assert ts.resolve("scope")["origin"].startswith("журнал вышедших постов")
    assert ts.resolve("scope", 1)["text"].startswith("к")            # ≥1 = обкатка по истории канала


# --- СВЕРКА ЖУРНАЛА С КАНАЛОМ (11.09.2026). Живой случай: ТГ-скоуп прогнали дважды на одну тему, в журнале
# два поста, админ оставил в отложке один. Threads обязан взять оставшийся, а не последний записанный.
ETF_OLD = ("**📉 Институции 228 дней в минусе, а держат стену те, кто дешевле**\n\n"
           "Спот биткоина сейчас около 77 000$. Над рынком висит потолок 83-86 тысяч, и это не случайное "
           "число. В этой зоне сходятся сразу три независимых уровня: средняя цена входа долгосрочных "
           "держателей, краткосрочных спекулянтов и спотовых фондов. Каждый из них продаёт в ноль")
ETF_NEW = ("**📊 Институции сами поставили крышу над рынком**\n\n"
           "Спотовые ETF на биткоин отыграли всю просадку и вернулись к безубытку. По данным Glassnode, "
           "средняя цена входа всех фондов около 83 000$. Рынок только что подполз к ней снизу, отыграв "
           "падение на 18 млрд$. Тот, кто заходил в фонд на просадке и досидел до минуса, у отметки "
           "безубытка делает ровно одно: выходит, лишь бы не свалиться в красное снова")


def _plain(text):
    """Так текст выглядит в Telegram: без звёздочек разметки."""
    return text.replace("**", "")


def test_deleted_newest_falls_back_to_the_one_left_in_queue(tmp_path, monkeypatch):
    _journal(tmp_path, monkeypatch, (ETF_OLD, None), (ETF_NEW, None))     # старые записи — без номера
    _snap(monkeypatch, scheduled=[{"id": 9, "text": _plain(ETF_OLD)}])      # свежий админ удалил

    src = ts.resolve("scope")
    assert src["text"] == ETF_OLD                                           # взял оставшийся
    assert "по тексту" in src["origin"]
    assert len(src["skipped"]) == 1 and "поставили крышу" in src["skipped"][0]   # удалённый назван


def test_twin_on_same_topic_does_not_claim_the_remaining_post(tmp_path, monkeypatch):
    # Обратный случай: удалён СТАРЫЙ. Свежий на ту же тему не должен «узнать себя» в чужом посте, а старый —
    # в свежем. Каждое сообщение отдаётся одной, самой похожей записи.
    _journal(tmp_path, monkeypatch, (ETF_OLD, None), (ETF_NEW, None))
    _snap(monkeypatch, scheduled=[{"id": 9, "text": _plain(ETF_NEW)}])
    src = ts.resolve("scope")
    assert src["text"] == ETF_NEW and src["skipped"] == []


def test_small_edit_is_still_recognised(tmp_path, monkeypatch):
    _journal(tmp_path, monkeypatch, (ETF_NEW, None))
    edited = (_plain(ETF_NEW).replace("отыграли", "вернули").replace("подполз", "дошёл")
              .replace("снизу", "сейчас").replace("ровно", "только").replace("свалиться", "упасть"))
    _snap(monkeypatch, scheduled=[{"id": 3, "text": edited}])                # админ поменял пять слов
    assert ts.resolve("scope")["text"] == ETF_NEW


def test_message_id_finds_post_whatever_the_edit(tmp_path, monkeypatch):
    tg = {"msg_id": 77, "scheduled_at": "2026-09-11T14:00:00+00:00", "channel": "канал", "text": ETF_NEW}
    _journal(tmp_path, monkeypatch, (ETF_OLD, None), (ETF_NEW, tg))
    _snap(monkeypatch, scheduled=[{"id": 77, "date": "2026-09-11T14:00:00+00:00",
                                   "text": "Админ переписал пост целиком, ни одного прежнего слова"}])
    src = ts.resolve("scope")
    assert src["text"] == ETF_NEW and "номеру сообщения" in src["origin"]


def test_message_id_alone_is_not_trusted(tmp_path, monkeypatch):
    # Номера отложки живут внутри канала. Совпал номер, но другой канал или другое время и чужой текст —
    # это не наш пост, а совпадение чисел.
    other = {"msg_id": 77, "scheduled_at": "2026-09-11T14:00:00+00:00", "channel": "старый канал", "text": ETF_NEW}
    _journal(tmp_path, monkeypatch, (ETF_NEW, other))
    _snap(monkeypatch, scheduled=[{"id": 77, "date": "2026-09-11T14:00:00+00:00", "text": "Чужой пост про погоду"}])
    assert ts.resolve("scope")["text"] == ""                                   # канал сменился — номер не в счёт

    same = dict(other, channel="канал")
    _journal(tmp_path, monkeypatch, (ETF_NEW, same))
    _snap(monkeypatch, scheduled=[{"id": 77, "date": "2026-09-20T14:00:00+00:00", "text": "Чужой пост про погоду"}])
    assert ts.resolve("scope")["text"] == ""                                   # и время, и текст чужие


def test_model_remark_before_headline_is_cut_from_old_entries(tmp_path, monkeypatch):
    # Запись 11.09 (до фикса журнала) начиналась с реплики модели. В Threads она уйти не должна.
    _journal(tmp_path, monkeypatch, ("Линтер чистый. Выдаю.\n\n" + ETF_NEW, None))
    _snap(monkeypatch, scheduled=[{"id": 3, "text": _plain(ETF_NEW)}])
    src = ts.resolve("scope")
    assert src["text"] == ETF_NEW and "Линтер" not in src["text"]
    assert ts._clean("Абзац без жирного заголовка\nвторая строка") == "Абзац без жирного заголовка\nвторая строка"
    assert ts._clean(ETF_NEW) == ETF_NEW                                       # нормальный пост не трогаем


def _keep_share(text, share):
    """Сильная правка: из слов поста остаётся ровно доля share, остальное — новые слова."""
    words = sorted(ts._words(text))
    return " ".join(words[: int(len(words) * share)]) + " совершенно новые слова вместо остальных"


ETF_NEW_HEAVY = _keep_share(ETF_NEW, 0.55)


def test_published_post_found_by_scheduled_time(tmp_path, monkeypatch):
    # Пост уже вышел: из отложки ушёл, в ленте у него новый номер. Держимся за назначенное время.
    tg = {"msg_id": 77, "scheduled_at": "2026-09-11T14:00:00+00:00", "channel": "канал", "text": ETF_NEW}
    _journal(tmp_path, monkeypatch, (ETF_NEW, tg))
    assert ts.TIME_MATCH <= ts._overlap(ts._words(ETF_NEW), ts._words(ETF_NEW_HEAVY)) < ts.TEXT_MATCH  # только время
    _snap(monkeypatch, recent=[{"id": 501, "date": "2026-09-11T14:00:04+00:00", "text": ETF_NEW_HEAVY}])
    src = ts.resolve("scope")
    assert src["text"] == ETF_NEW and "назначенное время" in src["origin"]

    _snap(monkeypatch, recent=[{"id": 501, "date": "2026-09-12T09:00:00+00:00", "text": ETF_NEW_HEAVY}])
    assert ts.resolve("scope")["text"] == ""                                  # то же, но в чужое время — не он


def test_nothing_left_in_channel_stops_with_reason(tmp_path, monkeypatch):
    _journal(tmp_path, monkeypatch, (ETF_OLD, None), (ETF_NEW, None))
    _snap(monkeypatch, scheduled=[{"id": 1, "text": "Совсем другой пост про погоду и выходные"}])
    src = ts.resolve("scope")
    assert src["text"] == "" and len(src["skipped"]) == 2
    assert "руками" in src["why"] and "заново" in src["why"]                  # вне завода: руками или новый прогон


def test_channel_unreachable_takes_latest_with_warning(tmp_path, monkeypatch):
    _journal(tmp_path, monkeypatch, (ETF_OLD, None), (ETF_NEW, None))
    _snap(monkeypatch, ok=False)
    src = ts.resolve("scope")
    assert src["text"] == ETF_NEW and "не проверил" in src["origin"]
    assert src["unverified"] == "нет сети"                                    # пайплайн скажет это отдельной строкой


def test_journal_keeps_sent_text_and_message_id(tmp_path, monkeypatch):
    # Реплика модели перед постом (11.09: «Линтер чистый. Выдаю.») в канал не ушла — и в журнал не идёт.
    _journal(tmp_path, monkeypatch)
    answer = "Линтер чистый. Выдаю.\n\n**Пост**\nтело\n[[SPLIT]]\n[[УЗЕЛ]] мысль"
    tg = {"msg_id": 5, "scheduled_at": "2026-09-11T14:00:00+00:00", "channel": "канал", "text": "**Пост**\nтело"}
    published_journal.record(answer, theme="т", kind="scope", tg=tg)
    last = published_journal.latest("scope")
    assert last["text"] == "**Пост**\nтело"
    assert last["tg_msg_id"] == 5 and last["tg_scheduled_at"].startswith("2026-09-11")
    assert last["nodes"] == ["мысль"]                                          # мета читается по-прежнему


def test_fallback_to_already_distilled_post_stops(tmp_path, monkeypatch):
    # Ревью 11.09: свежий удалён, а оставшийся уже превращали в Threads — откат дал бы второй тред на старую тему.
    today = published_journal.date.today().isoformat()
    _journal(tmp_path, monkeypatch, (ETF_OLD, None, "старая тема"), (ETF_NEW, None, "новая тема"))
    _distilled(tmp_path, monkeypatch, {"created": "2026-09-11", "flagship_date": today, "theme": "старая тема"})
    _snap(monkeypatch, scheduled=[{"id": 9, "text": _plain(ETF_OLD)}])
    src = ts.resolve("scope")
    assert src["text"] == "" and "уже перерабатывали" in src["why"]


def test_rerun_of_the_newest_post_is_allowed_but_flagged(tmp_path, monkeypatch):
    today = published_journal.date.today().isoformat()
    _journal(tmp_path, monkeypatch, (ETF_NEW, None, "новая тема"))
    _distilled(tmp_path, monkeypatch, {"created": "2026-09-11", "flagship_date": today, "theme": "новая тема"})
    _snap(monkeypatch, scheduled=[{"id": 9, "text": _plain(ETF_NEW)}])
    src = ts.resolve("scope")
    assert src["text"] == ETF_NEW and src["repeat"] == "2026-09-11"


def test_entry_older_than_the_checked_feed_is_not_called_deleted(tmp_path, monkeypatch):
    _journal(tmp_path, monkeypatch, (ETF_NEW, None))
    monkeypatch.setattr(ts, "RECENT_POSTS", 2)
    later = "2999-01-01T00:00:00+00:00"                                        # всё окно ленты — моложе записи
    _snap(monkeypatch, recent=[{"id": 1, "date": later, "text": "про погоду"}, {"id": 2, "date": later, "text": "про кино"}])
    src = ts.resolve("scope")
    assert src["text"] == "" and "проверить не могу" in src["skipped"][0]
