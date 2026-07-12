"""Тесты бэкапа незаменимого состояния (AUDIT P2-14/N-3): классификация живое/скретч + архивация (backup.py)."""
import zipfile

import backup


def test_live_and_scratch_do_not_overlap():
    # один путь не может быть одновременно «незаменимым» и «скретчем» — иначе классификация врёт
    overlap = set(backup.IRREPLACEABLE) & set(backup.SCRATCH)
    assert not overlap, f"пересечение живое/скретч: {overlap}"
    assert backup.IRREPLACEABLE and backup.SCRATCH


def test_iter_files_missing_path_is_empty():
    assert list(backup._iter_files("data/definitely_absent_xyz.json")) == []


def test_make_backup_zips_only_irreplaceable(tmp_path, monkeypatch):
    # синтетический корень: и незаменимое, и скретч рядом — в архив должно попасть ТОЛЬКО первое
    fake = tmp_path / "root"
    (fake / "data").mkdir(parents=True)
    (fake / ".env").write_text("SECRET=x", encoding="utf-8")
    (fake / "data" / "evgeniyp.session").write_text("sess", encoding="utf-8")
    (fake / "data" / "channel_posts.json").write_text("scratch", encoding="utf-8")  # SCRATCH
    (fake / "memory").mkdir()
    (fake / "memory" / "post_lessons.md").write_text("lesson", encoding="utf-8")
    monkeypatch.setattr(backup, "ROOT", fake)

    out = backup.make_backup(tmp_path / "out")

    assert out.exists() and zipfile.is_zipfile(out)
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
    assert ".env" in names
    assert "data/evgeniyp.session" in names
    assert "memory/post_lessons.md" in names
    assert "data/channel_posts.json" not in names   # скретч НЕ бэкапится
