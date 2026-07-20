"""TG-сборщик: защищённая запись не затирает хорошую историю урезанной/пустой выгрузкой (аудит 20.07).
Дыра была: безусловная перезапись → транзиентный сбой Telegram (меньше/пусто на exit 0) молча терял
корпус, а mtime-гейт свежести сертифицировал пустоту как «свежо». Зеркалит защиту Threads-сборщика."""
import json

from connectors.telegram_export import collect


def _seed(path, n):
    path.write_text(json.dumps([{"id": i, "views": 1} for i in range(n)]), encoding="utf-8")


def test_writes_when_healthy(monkeypatch, tmp_path):
    out = tmp_path / "channel_posts.json"
    monkeypatch.setattr(collect, "OUT", out)
    _seed(out, 100)
    collect._safe_write([{"id": i} for i in range(120)])            # выросло → пишем
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 120


def test_refuses_empty_keeps_old(monkeypatch, tmp_path):
    out = tmp_path / "channel_posts.json"
    monkeypatch.setattr(collect, "OUT", out)
    _seed(out, 100)
    collect._safe_write([])                                         # пусто → НЕ затираем
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 100  # старое цело


def test_refuses_drastic_shrink_keeps_old(monkeypatch, tmp_path):
    out = tmp_path / "channel_posts.json"
    monkeypatch.setattr(collect, "OUT", out)
    _seed(out, 100)
    collect._safe_write([{"id": i} for i in range(40)])            # <50% существующего → НЕ затираем
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 100


def test_first_collect_writes(monkeypatch, tmp_path):
    out = tmp_path / "channel_posts.json"
    monkeypatch.setattr(collect, "OUT", out)                        # файла ещё нет
    collect._safe_write([{"id": 1}])
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 1


def test_minor_shrink_still_writes(monkeypatch, tmp_path):
    # лёгкое колебание (удалили пару постов) — НЕ ложная тревога, пишем (порог 50%)
    out = tmp_path / "channel_posts.json"
    monkeypatch.setattr(collect, "OUT", out)
    _seed(out, 100)
    collect._safe_write([{"id": i} for i in range(95)])
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 95
