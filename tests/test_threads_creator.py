"""Threads-ветка — журнал вышедших ТГ-постов (ОБА формата) + гейты пайплайна.

Без API/сети: проверяем сантехнику (запись/чтение журнала по формату, обрезку меты, миграцию старого
флагман-журнала, отказы на пустом журнале и на ненаписанном своде правил). Качество самой переработки
проверяется на живых прогонах, не юнит-тестом.

⚠️ Журнал в тестах подменяем ОБА: и новый (JOURNAL), и старый (LEGACY_JOURNAL) — иначе миграция
подтянула бы реальные записи с диска владельца, и тест мерил бы не то."""
import json

from core import published_journal, threads_creator


def _isolate(tmp_path, monkeypatch):
    """Подменить оба журнала на временные — тест не видит и не трогает боевые данные."""
    j = tmp_path / "published_posts.jsonl"
    monkeypatch.setattr(published_journal, "JOURNAL", j)
    monkeypatch.setattr(published_journal, "LEGACY_JOURNAL", tmp_path / "legacy.jsonl")
    return j


def test_journal_round_trip(tmp_path, monkeypatch):
    j = _isolate(tmp_path, monkeypatch)
    assert published_journal.latest() is None                    # журнала ещё нет

    published_journal.record("Тело флагмана\n[[SPLIT]]\nвнутренняя мета", theme="prediction markets")
    published_journal.record("Второй флагман", theme="стейблкоины")

    last = published_journal.latest()
    assert last is not None
    assert last["theme"] == "стейблкоины"                       # latest = ПОСЛЕДНЯЯ запись
    assert last["text"] == "Второй флагман"

    lines = [json.loads(l) for l in j.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2                                      # append-only, не перезапись
    assert lines[0]["text"] == "Тело флагмана"                  # мета после [[SPLIT]] отброшена
    assert "date" in lines[0]


def test_record_empty_or_meta_only_ignored(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    published_journal.record("", theme="x")                      # пустой текст — не пишем
    published_journal.record("   ", theme="y")                   # пробелы — не пишем
    published_journal.record("[[SPLIT]]\nтолько мета")           # тело пустое после обрезки — не пишем
    assert published_journal.latest() is None


def test_journal_keeps_formats_apart(tmp_path, monkeypatch):
    """Один журнал, две метки: мини-флагман и мини-скоуп берут СВОЙ последний пост, не чужой."""
    _isolate(tmp_path, monkeypatch)
    published_journal.record("Флагман про биткоин", theme="btc", kind="flagship")
    published_journal.record("Скоуп про банк Дорси", theme="block", kind="scope")

    assert published_journal.latest("flagship")["text"] == "Флагман про биткоин"
    assert published_journal.latest("scope")["text"] == "Скоуп про банк Дорси"
    assert published_journal.latest()["text"] == "Скоуп про банк Дорси"     # без формата — просто последний
    # имена формата приезжают и из чата («скоуп», «короткий») — нормализация общая с ТГ
    assert published_journal.latest("скоуп")["text"] == "Скоуп про банк Дорси"


def test_legacy_flagship_journal_is_migrated(tmp_path, monkeypatch):
    """Старый флагман-журнал (до 09.09.2026) не теряется: записи переезжают с меткой 'flagship'."""
    j = _isolate(tmp_path, monkeypatch)
    published_journal.LEGACY_JOURNAL.write_text(
        json.dumps({"date": "2026-08-20", "theme": "старая тема", "text": "Старый флагман"},
                   ensure_ascii=False) + "\n", encoding="utf-8")

    last = published_journal.latest("flagship")
    assert last["text"] == "Старый флагман"                     # история вышедших флагманов цела
    assert last["kind"] == "flagship"                            # и получила формат
    assert j.exists() and published_journal.latest("scope") is None


def test_pipeline_stops_on_empty_journal(tmp_path, monkeypatch):
    import run_threads_pipeline as rtp
    _isolate(tmp_path, monkeypatch)
    out = rtp.run_threads_cycle(emit=lambda *_: None)           # emit-заглушка: без вывода в терминал
    low = out.lower()
    assert "журнал" in low and "нечего" in low                  # штатный отказ, не падение/не вызов API


def test_branch_refuses_while_its_manual_is_a_placeholder(monkeypatch):
    """Свод не написан → ветка отказывается работать (иначе добрала бы правила соседнего формата)."""
    monkeypatch.setattr(threads_creator, "_read",
                        lambda rel: threads_creator.MANUAL_PLACEHOLDER if "manual" in rel else "")
    assert threads_creator.manual_missing("scope") is True
    out = threads_creator.write("scope")                        # без API: отказ раньше вызова модели
    assert "не написан" in out


def test_orientation_low_data_fallback():
    from connectors.threads import report
    assert "мануал" in report.orientation_digest(posts=[], topics={}).lower()   # нет данных → на мануал


def test_orientation_populated():
    from connectors.threads import report
    # 5 зрелых чистых постов (июнь) + 1 свежий (июль) задаёт «сейчас» → июньские mature (age ~30д)
    posts = [{"id": i, "date": "2026-06-01T10:00:00", "views": 300, "likes": 10,
              "people_count": 3, "people_replies": 4, "reposts": 2, "has_media": i <= 3}
             for i in range(1, 6)]
    posts.append({"id": 99, "date": "2026-07-01T10:00:00", "views": 100})
    topics = {str(i): {"title": f"Пост {i}", "theme": "личное", "summary": "s"} for i in range(1, 6)}
    d = report.orientation_digest(posts=posts, topics=topics)
    assert "личное" in d                                        # тема с n>=5 попала в ориентир
    assert "медиа" in d.lower()                                 # есть и медиа, и текст → строка сравнения


def test_split_output_separates_posts_and_owner_block():
    """Блок для владельца (комменты / что осталось в ТГ) отделяется от постов и НЕ едет в публикацию."""
    raw = ("Первый тред\n" + threads_creator.POST_SEP + "\nВторой тред\n\n"
           + threads_creator.GUIDE_SEP + "\nВ ТГ осталась механика. Спор пойдёт про сигнал.")
    posts, guide = threads_creator.split_output(raw)
    assert posts == ["Первый тред", "Второй тред"]
    assert guide.startswith("В ТГ осталась механика")

    posts, guide = threads_creator.split_output("Одинокий тред")     # блока нет — тоже норма
    assert posts == ["Одинокий тред"] and guide == ""


def test_length_round_compresses_only_when_needed(monkeypatch):
    """Перебор по знакам лечится ОДНИМ кругом сжатия; в норме круг не зовётся (деньги не тратим)."""
    calls = []

    def _fake_reply(*a, **kw):
        calls.append(a)
        return "Сжатый пост\n" + threads_creator.POST_SEP + "\nВторой", None

    monkeypatch.setattr(threads_creator.llm, "reply", _fake_reply)
    monkeypatch.setattr(threads_creator, "_system", lambda _k: "sys")

    short = ["Короткий", "Второй"]
    assert threads_creator._enforce_length(short, "scope", "key", "model") == short
    assert calls == []                                              # круга не было

    long_post = "я" * (threads_creator.MAX_LEN + 40)
    out = threads_creator._enforce_length([long_post, "Второй"], "scope", "key", "model")
    assert len(calls) == 1 and out == ["Сжатый пост", "Второй"]
    assert "сжал" in threads_creator.LAST_LENGTH_NOTE


def test_length_round_keeps_originals_if_model_loses_a_post(monkeypatch):
    """Круг вернул не тот состав → верим своим постам: лучше длинный пост, чем потерянный."""
    monkeypatch.setattr(threads_creator.llm, "reply", lambda *a, **kw: ("Только один", None))
    monkeypatch.setattr(threads_creator, "_system", lambda _k: "sys")
    posts = ["я" * (threads_creator.MAX_LEN + 10), "Второй"]
    assert threads_creator._enforce_length(posts, "flagship", "key", "model") == posts
    assert "оставил исходные" in threads_creator.LAST_LENGTH_NOTE


def test_writer_uses_the_source_it_was_given(monkeypatch):
    """Баг 09.09: пайплайн показывал один пост, а писатель брал из журнала другой (тред про Дорси
    из скоупа про SEC). Источник теперь ОДИН на прогон — тот, что передал вызывающий."""
    seen = {}

    def _fake_reply(model, system, history, task, *a, **kw):
        seen["task"] = task
        return "Готовый тред", None

    monkeypatch.setattr(threads_creator.llm, "reply", _fake_reply)
    monkeypatch.setattr(threads_creator, "_system", lambda _k: "sys")
    monkeypatch.setattr(threads_creator, "manual_missing", lambda _k: False)
    monkeypatch.setattr(threads_creator, "_save", lambda *a, **kw: None)
    monkeypatch.setattr(threads_creator.threads_distill_journal, "record", lambda *a, **kw: None)
    monkeypatch.setattr(threads_creator.config, "load_agent", lambda _n: {"persona": "p"})
    monkeypatch.setattr(threads_creator.config, "agent_api_key", lambda _c: "key")
    # журнал специально «заряжен» ДРУГИМ постом — писатель не должен его увидеть
    monkeypatch.setattr(threads_creator.threads_source, "resolve",
                        lambda *a, **kw: {"text": "ЧУЖОЙ ПОСТ ИЗ ЖУРНАЛА", "date": "2026-09-09"})

    out = threads_creator.write("scope", src={"text": "ПЕРЕДАННЫЙ ИСХОДНИК", "date": "2026-09-02"})
    assert out == "Готовый тред"
    assert "ПЕРЕДАННЫЙ ИСХОДНИК" in seen["task"] and "ЧУЖОЙ" not in seen["task"]
