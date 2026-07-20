"""write-path Криейтора (N-68): _publish_now — ЧТО реально уходит в канал — и _md_files (гейт свежего
драфта). Тут живут channel-safety / data-loss пути (срез [[SPLIT]]/[ПРОВЕРИТЬ], гейт обложки), которые
были без тестов. Сеть/планировщик замоканы — проверяем чистую логику, а не отправку."""
import datetime

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
    d = tmp_path / "drafts"
    d.mkdir()
    (d / "2026-07-20-a.md").write_text("a", encoding="utf-8")
    (d / "2026-07-22-b.md").write_text("b", encoding="utf-8")
    (d / "notes.md").write_text("x", encoding="utf-8")        # без даты → игнор (N-19)
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
