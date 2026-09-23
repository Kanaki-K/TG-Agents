"""Скоуп обязан работать со СВОИМ драфтом — прогон 23.09.2026.

Писатель сохранил пост про BitMEX с kind не 'scope' → файл `2026-09-23-bitmex-close.md` без суффикса
`-scope`. Конвейер ищет свой пост через latest_draft('scope') (по суффиксу) и нашёл драфт 17.09 про
резерв H.R. 8957: веб-сверка, правки фактов, речи и эха пошли по нему, и в канал ушёл третий пост про
резерв за неделю — под темой BitMEX и с обложкой BitMEX.

Вторая половина того же прогона: кадр 1345x900 (1.49) прошёл отбор «горизонталь» (≥1.45), а
нормализация достроила его серыми полями до 16:9, потому что её граница была 1.5.
"""
import inspect
import os
import time

from PIL import Image

import run_pipeline as rp
from connectors.source_media import fetch
from core import creator_tools, scope_writer, verify


def _drafts(monkeypatch, tmp_path):
    d = tmp_path / "drafts"
    d.mkdir()
    monkeypatch.setattr(creator_tools, "DRAFTS_DIR", d)
    monkeypatch.setattr(creator_tools, "LAST_KIND", tmp_path / "kind.txt")
    return d


def test_scope_branch_saves_as_scope_whatever_the_model_says(monkeypatch, tmp_path):
    """Модель назвала формат по-своему — файл всё равно скоуповый, и конвейер его видит."""
    d = _drafts(monkeypatch, tmp_path)
    for kind in ("скоуп", "🔭", "", "короткий"):
        scope_writer._dispatch("save_draft", {"content": f"**Пост {kind}**\n\nТекст",
                                              "slug": "bitmex-close", "kind": kind})
    names = [p.name for p in d.glob("*.md")]
    assert names and all(n.endswith("-scope.md") for n in names), names
    assert "Пост" in verify.latest_draft("scope")


def test_scope_writer_turn_uses_forcing_dispatch():
    """Сторож против отката: _turn обязан звать модель через _dispatch, а не голый creator_tools.dispatch."""
    src = inspect.getsource(scope_writer._turn)
    assert "_dispatch" in src and "creator_tools.dispatch" not in src


def test_old_scope_draft_is_not_fresh(monkeypatch, tmp_path):
    """Свежий файл ДРУГОГО формата не делает старый скоуп-драфт свежим (ровно ситуация 23.09)."""
    d = _drafts(monkeypatch, tmp_path)
    old = d / "2026-09-17-hr8957-reserve-scope.md"
    old.write_text("резерв", encoding="utf-8")
    os.utime(old, (time.time() - 6 * 86400,) * 2)
    pre = time.time() - 60
    (d / "2026-09-23-bitmex-close.md").write_text("bitmex", encoding="utf-8")
    assert rp._latest_draft_mtime() > pre              # «какой-то новый файл есть» — да
    assert rp._latest_draft_mtime("scope") <= pre      # «наш скоуп свежий» — нет
    assert verify.latest_draft_path("scope") == old


def test_web_check_runs_only_on_fresh_scope_draft():
    """2FA и цепочка правок стоят под проверкой свежести СКОУП-драфта, а повтор записи — до них."""
    src = inspect.getsource(rp.run_cycle)
    gate = 'if scope and post and _latest_draft_mtime("scope") > pre_mtime:'
    assert gate in src
    retry = src.index('if scope and _latest_draft_mtime("scope") <= pre_mtime:')
    assert retry < src.index(gate), "повтор записи драфта обязан идти ДО веб-сверки"


def test_fix_facts_returns_scope_draft():
    src = inspect.getsource(scope_writer.fix_facts)
    assert 'verify.latest_draft()' not in src


def test_landscape_frame_is_not_padded(tmp_path):
    """Кадр 1345x900 (1.49) — горизонталь по отбору, значит полей быть не должно."""
    p = tmp_path / "f.png"
    Image.new("RGB", (1345, 900), (120, 60, 30)).save(p)
    out = fetch._normalize(p, min_side=400)
    with Image.open(out) as im:
        assert im.size == (1345, 900)
    assert fetch.is_landscape(out)


def test_selection_and_normalization_share_bounds():
    """Одна граница на двоих: всё, что отбор считает горизонталью, нормализация не трогает."""
    assert fetch.LANDSCAPE_MIN == fetch._RATIO_MIN
    assert fetch.LANDSCAPE_MAX == fetch._RATIO_MAX
