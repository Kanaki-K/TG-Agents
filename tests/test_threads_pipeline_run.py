"""Запуск Threads-пайплайна: разбор командной строки, выбор обложки и копия обложки в журнале.

Все три — находки аудита перед первым боевым запуском (11.09.2026): опечатка `-scope` молча запускала
мини-флагман в отложку; имена кадров scope_N_M.jpg переиспользует каждый ТГ-прогон, и у записей 09.09 и
10.09 на диске уже лежали картинки другого поста."""
import os
from datetime import datetime

import pytest

import run_threads_pipeline as rtp
from core import published_journal


def test_typo_is_an_error_not_another_mode():
    with pytest.raises(SystemExit):
        rtp._parse_args(["-scope"])


def test_old_argument_forms():
    assert rtp._parse_args([]).old is None                        # штатный путь — журнал
    assert rtp._parse_args(["--scope", "--old"]).old == 1
    assert rtp._parse_args(["--scope", "--old=3"]).old == 3       # раньше молча игнорировалось
    args = rtp._parse_args(["--scope", "--old", "2", "--review-only"])
    assert args.scope and args.review_only and args.old == 2
    with pytest.raises(SystemExit):
        rtp._parse_args(["--old", "0"])                           # раньше превращалось в 1


def _image(folder, name, day):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"\xff\xd8" + b"0" * 50)
    stamp = datetime(*day, 12, 0).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_cover_overwritten_by_later_run_is_not_used(tmp_path):
    frame = _image(tmp_path / "source_media", "scope_1_0.jpg", (2026, 9, 11))
    path, note = rtp._cover_for({"cover": str(frame), "date": "2026-09-10"})
    assert path == "" and "НЕ беру" in note                       # файл новее поста — картинка чужая
    path, note = rtp._cover_for({"cover": str(frame), "date": "2026-09-11"})
    assert path == str(frame) and "Беру" in note


def test_journal_cover_copy_is_trusted(tmp_path):
    copy = _image(tmp_path / "journal_covers", "2026-09-10_scope_77.jpg", (2026, 9, 12))
    assert rtp._cover_for({"cover": str(copy), "date": "2026-09-10"})[0] == str(copy)


def test_journal_keeps_its_own_copy_of_the_cover(tmp_path, monkeypatch):
    monkeypatch.setattr(published_journal, "JOURNAL", tmp_path / "journal.jsonl")
    monkeypatch.setattr(published_journal, "LEGACY_JOURNAL", tmp_path / "legacy.jsonl")
    monkeypatch.setattr(published_journal, "COVERS_DIR", tmp_path / "journal_covers")
    frame = tmp_path / "source_media" / "scope_1_0.jpg"
    frame.parent.mkdir()
    frame.write_bytes(b"ORIGINAL")
    published_journal.record("**Пост**\nтело", kind="scope", cover=str(frame),
                             tg={"msg_id": 77, "text": "**Пост**\nтело"})
    kept = published_journal.latest("scope")["cover"]
    assert "journal_covers" in kept and kept.endswith("_scope_77.jpg")
    frame.write_bytes(b"NEXT RUN")                                # следующий ТГ-прогон пишет поверх
    with open(kept, "rb") as f:
        assert f.read() == b"ORIGINAL"


# --- ПОСТАНОВКА СЕРИИ (аудит 11.09.2026): время своего формата, частичный провал, неопознанный канал ---

def _cycle_env(monkeypatch, publish_results, check=None):
    """Прогон мини-флагмана без сети и модели. Формат — флагман: у скоупа прогон ставит метку для сбора
    аналитики в data/, а тест в боевой data/ писать не должен."""
    calls = {"publish": [], "record": [], "notify": []}
    sep = rtp.threads_creator.POST_SEP
    monkeypatch.setattr(rtp.threads_creator, "manual_missing", lambda k: False)
    monkeypatch.setattr(rtp.threads_source, "resolve",
                        lambda k, b: {"text": "ТГ-флагман", "date": "2026-09-15", "theme": "т", "origin": "журнал"})
    monkeypatch.setattr(rtp.threads_creator, "write", lambda *a, **kw: f"пост один\n{sep}\nпост два")
    monkeypatch.setattr(rtp.threads_lint, "check_series", lambda posts: "")
    monkeypatch.setattr(rtp.runmode, "get", lambda: {"mode": "main", "model": "m"})
    monkeypatch.setattr(rtp, "_review_channel", lambda: "ревью")
    monkeypatch.setattr(rtp.config, "get_optional", lambda k: "@мейн" if k == "PUBLISH_NOTIFY" else None)
    monkeypatch.setattr(rtp.tg_publish, "check", lambda ch: check or {"ok": True, "channel": "test_treds"})
    results = iter(publish_results)
    monkeypatch.setattr(rtp.tg_publish, "publish",
                        lambda ch, text, cover, when: calls["publish"].append((text, when)) or next(results))
    monkeypatch.setattr(rtp.tg_publish, "scheduled_times", lambda ch: [])
    monkeypatch.setattr(rtp.tg_publish, "notify", lambda to, msg: calls["notify"].append(msg) or {"ok": True})
    monkeypatch.setattr(rtp.threads_distill_journal, "record", lambda src, body, sep_: calls["record"].append(body))
    return calls


def test_series_uses_its_own_format_slot_and_two_hour_step(monkeypatch):
    asked = []
    monkeypatch.setattr(rtp.content_plan, "next_slot",
                        lambda k, **kw: asked.append(k) or datetime(2026, 9, 15, 16, 0))
    assert [t.hour for t in rtp._series_times("flagship", 3)] == [16, 18, 20]
    rtp._series_times("scope", 1)
    assert asked == ["flagship", "short"]          # раньше флагман брал слот скоупа (день не тот)


def test_partial_series_records_and_reports_only_what_landed(monkeypatch):
    monkeypatch.setattr(rtp.content_plan, "next_slot", lambda k, **kw: datetime(2026, 9, 15, 16, 0))
    calls = _cycle_env(monkeypatch, [{"ok": True, "mode": "текст"}, {"ok": False, "error": "сеть"}])
    rtp.run_threads_cycle(emit=lambda *_: None, kind="flagship")
    assert [w.hour for _, w in calls["publish"]] == [16, 18]
    assert calls["record"] == ["пост один"]        # упавший №2 в журнал переработок не идёт
    assert "№2" in calls["notify"][0]


def test_nothing_landed_still_notifies(monkeypatch):
    monkeypatch.setattr(rtp.content_plan, "next_slot", lambda k, **kw: datetime(2026, 9, 15, 16, 0))
    calls = _cycle_env(monkeypatch, [{"ok": False, "error": "сеть"}, {"ok": False, "error": "сеть"}])
    rtp.run_threads_cycle(emit=lambda *_: None, kind="flagship")
    assert calls["record"] == [] and calls["notify"][0].startswith("❌")


def test_unrecognised_review_channel_stops_before_posting(monkeypatch):
    monkeypatch.setattr(rtp.content_plan, "next_slot", lambda k, **kw: datetime(2026, 9, 15, 16, 0))
    calls = _cycle_env(monkeypatch, [], check={"ok": True, "channel": None, "channel_error": "не найден"})
    out = rtp.run_threads_cycle(emit=lambda *_: None, kind="flagship")
    assert calls["publish"] == [] and "не ставлю" in out
