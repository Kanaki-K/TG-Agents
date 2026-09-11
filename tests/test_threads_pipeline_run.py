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
    copy = _image(tmp_path / "published_covers", "2026-09-10_scope_77.jpg", (2026, 9, 12))
    assert rtp._cover_for({"cover": str(copy), "date": "2026-09-10"})[0] == str(copy)


def test_journal_keeps_its_own_copy_of_the_cover(tmp_path, monkeypatch):
    monkeypatch.setattr(published_journal, "JOURNAL", tmp_path / "journal.jsonl")
    monkeypatch.setattr(published_journal, "LEGACY_JOURNAL", tmp_path / "legacy.jsonl")
    monkeypatch.setattr(published_journal, "COVERS_DIR", tmp_path / "published_covers")
    frame = tmp_path / "source_media" / "scope_1_0.jpg"
    frame.parent.mkdir()
    frame.write_bytes(b"ORIGINAL")
    published_journal.record("**Пост**\nтело", kind="scope", cover=str(frame),
                             tg={"msg_id": 77, "text": "**Пост**\nтело"})
    kept = published_journal.latest("scope")["cover"]
    assert "published_covers" in kept and kept.endswith("_scope_77.jpg")
    frame.write_bytes(b"NEXT RUN")                                # следующий ТГ-прогон пишет поверх
    with open(kept, "rb") as f:
        assert f.read() == b"ORIGINAL"
