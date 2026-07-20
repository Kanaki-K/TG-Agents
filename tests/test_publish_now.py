"""write-path Криейтора (N-68): _publish_now — ЧТО реально уходит в канал — и _md_files (гейт свежего
драфта). Тут живут channel-safety / data-loss пути (срез [[SPLIT]]/[ПРОВЕРИТЬ], гейт обложки), которые
были без тестов. Сеть/планировщик замоканы — проверяем чистую логику, а не отправку."""
import datetime
import os

from core import creator_tools


class _FakePublish:
    def __init__(self):
        self.calls = []

    def publish(self, channel, text, cover, slot):
        self.calls.append({"channel": channel, "text": text, "cover": cover})
        return {"ok": True, "mode": "тест"}

    def scheduled_times(self, channel):
        return []

    def notify(self, target, msg):
        return {"ok": True}


def _setup(monkeypatch, tmp_path, channel="test_channel"):
    d = tmp_path / "drafts"
    d.mkdir()
    monkeypatch.setattr(creator_tools, "DRAFTS_DIR", d)
    monkeypatch.setattr(creator_tools, "LAST_KIND", tmp_path / "kind.txt")
    monkeypatch.setattr(creator_tools, "LAST_COVER", tmp_path / "cover.txt")
    monkeypatch.setattr(creator_tools, "SCOPE_COVER", tmp_path / "scope_cover.txt")
    pub = _FakePublish()
    monkeypatch.setattr(creator_tools, "publish", pub)
    monkeypatch.setattr(creator_tools.config, "get_optional",
                        lambda k: channel if k == "PUBLISH_CHANNEL" else None)
    cp = creator_tools.content_plan
    monkeypatch.setattr(cp, "next_slot", lambda kind, busy_dates=None: datetime.datetime(2026, 7, 22, 15, 0))
    monkeypatch.setattr(cp, "human", lambda slot: "Ср 22.07 15:00")
    monkeypatch.setattr(cp, "kind_label", lambda kind: kind)
    monkeypatch.setattr(cp, "infer_kind", lambda text: "short")
    return d, pub


def _draft(d, body, name="2026-07-22-post.md"):
    (d / name).write_text(body, encoding="utf-8")


def test_md_files_only_dated_newest_first(tmp_path):
    # _md_files сортирует по MTIME (свежий записанный = первым), НЕ по дате в имени. Задаём mtime ЯВНО:
    # мгновенные записи на Windows дают одинаковый mtime (грубое разрешение) → порядок был бы недетерминирован.
    d = tmp_path / "drafts"
    d.mkdir()
    a = d / "2026-07-20-a.md"
    a.write_text("a", encoding="utf-8")
    b = d / "2026-07-22-b.md"
    b.write_text("b", encoding="utf-8")
    (d / "notes.md").write_text("x", encoding="utf-8")        # без даты → игнор (N-19)
    os.utime(a, (1000, 1000))                                 # a записан раньше (mtime меньше)
    os.utime(b, (2000, 2000))                                 # b свежее → первым
    assert [p.name for p in creator_tools._md_files(d)] == ["2026-07-22-b.md", "2026-07-20-a.md"]


def test_publish_cuts_split_and_proveryay(monkeypatch, tmp_path):
    d, pub = _setup(monkeypatch, tmp_path)
    _draft(d, "**Пост**\nтело поста\n[ПРОВЕРИТЬ: цифра]\n[[SPLIT]]\nМЕТА владельцу")
    creator_tools._publish_now({})
    sent = pub.calls[0]["text"]
    assert "тело поста" in sent
    assert "МЕТА владельцу" not in sent      # мета после [[SPLIT]] в канал НЕ идёт
    assert "[ПРОВЕРИТЬ" not in sent          # флаг-строка вырезана из тела


def test_publish_guards_no_channel(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, channel="")
    assert "PUBLISH_CHANNEL" in creator_tools._publish_now({})


def test_publish_guards_no_draft(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    assert "Нет сохранённого драфта" in creator_tools._publish_now({})


def test_publish_guards_empty_after_strip(monkeypatch, tmp_path):
    d, _ = _setup(monkeypatch, tmp_path)
    _draft(d, "[ПРОВЕРИТЬ: только мета]\n[[SPLIT]]\nхвост")
    assert "пуст" in creator_tools._publish_now({})     # после выреза меты нечего публиковать


def test_forced_cover_bypasses_gate(monkeypatch, tmp_path):
    d, pub = _setup(monkeypatch, tmp_path)
    _draft(d, "**Пост**\nтело")
    cover = tmp_path / "c.jpg"
    cover.write_text("img", encoding="utf-8")
    creator_tools._publish_now({"cover": str(cover)})
    assert pub.calls[0]["cover"] == str(cover)          # явная обложка прогона — без mtime-гейта


def test_flagship_without_cover_goes_textonly(monkeypatch, tmp_path):
    d, pub = _setup(monkeypatch, tmp_path)
    _draft(d, "**Флагман**\nтело")
    res = creator_tools._publish_now({"kind": "флагман"})   # LAST_COVER не существует
    assert pub.calls[0]["cover"] is None                    # флагман ушёл ТЕКСТОМ, не с чужой картинкой
    assert "НЕ прицепил" in res


def _set_cover(tmp_path, mtime):
    img = tmp_path / "cover.jpg"
    img.write_text("img", encoding="utf-8")
    creator_tools.LAST_COVER.write_text(str(img), encoding="utf-8")
    os.utime(creator_tools.LAST_COVER, (mtime, mtime))
    return str(img)


def test_flagship_stale_cover_goes_textonly(monkeypatch, tmp_path):
    # mtime-гейт (N-66): LAST_COVER СТАРШЕ драфта (make_image упал / прошлый флагман) → ТЕКСТОМ, не чужой
    # картинкой. Поведение fail-safe+видимое (пометка) — тестируем ЕГО, а не «чиним» (расширение окна
    # внесло бы тихий риск прицепить чужую обложку — хуже для бренда).
    d, pub = _setup(monkeypatch, tmp_path)
    _draft(d, "**Флагман**\nтело")
    draft_mtime = next(d.glob("*.md")).stat().st_mtime
    _set_cover(tmp_path, draft_mtime - 100)                 # обложка на 100с старше драфта
    res = creator_tools._publish_now({"kind": "флагман"})
    assert pub.calls[0]["cover"] is None
    assert "НЕ прицепил" in res


def test_flagship_fresh_cover_attached(monkeypatch, tmp_path):
    # обложка ЭТОГО прогона (не старше драфта) → прицепляется
    d, pub = _setup(monkeypatch, tmp_path)
    _draft(d, "**Флагман**\nтело")
    draft_mtime = next(d.glob("*.md")).stat().st_mtime
    img = _set_cover(tmp_path, draft_mtime)                 # ровесник драфта — в пределах гейта
    creator_tools._publish_now({"kind": "флагман"})
    assert pub.calls[0]["cover"] == img
