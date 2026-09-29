"""Живые эталоны короткого формата — ответ на вопрос владельца 19.08: почему флагман месяц выходит
без его правок, а короткий он правит каждый раз и правит ПО ТЕКСТУ.

Разница нашлась в сборке контекста: у флагмана 4-5 ПОЛНЫХ постов канала стоят ПЕРВЫМ блоком и имеют
приоритет над правилами, а у короткого было два эталона цитатами в §8 мануала — после 25 тысяч знаков
правил. Здесь проверяется, что у scope теперь тот же механизм: список курирует владелец в
memory/scope_anchors.md, тексты тянутся живые, а падение чтения не роняет пост.
Запуск: python -m pytest tests/test_scope_anchors.py"""
from core import scope_writer as sw


def test_ids_read_from_curated_file(tmp_path, monkeypatch):
    f = tmp_path / "scope_anchors.md"
    f.write_text("# коммент\n- #475 живой эталон\nпросто строка\n- #456\n", encoding="utf-8")
    monkeypatch.setattr(sw, "_read", lambda rel: f.read_text(encoding="utf-8"))
    assert sw._anchor_ids() == [475, 456]


def test_fallback_when_file_missing(monkeypatch):
    # файла нет / он пуст → курированный набор в коде, а не пустой промпт
    monkeypatch.setattr(sw, "_read", lambda rel: "")
    assert sw._anchor_ids() == sw.SCOPE_ANCHOR_FALLBACK


def test_ids_capped(monkeypatch):
    monkeypatch.setattr(sw, "_read", lambda rel: "".join(f"- #{i}\n" for i in range(400, 420)))
    assert len(sw._anchor_ids()) == sw.SCOPE_ANCHOR_MAX


def test_anchors_survive_unreadable_dump(monkeypatch):
    # выгрузка канала недоступна — пост важнее эталона, писать всё равно надо
    monkeypatch.setattr(sw.analytics, "read_post", lambda pid: (_ for _ in ()).throw(OSError("нет выгрузки")))
    assert "недоступны" in sw._anchors()


def test_anchors_join_live_texts(monkeypatch):
    monkeypatch.setattr(sw, "_read", lambda rel: "- #475\n- #456\n")
    monkeypatch.setattr(sw.analytics, "read_post", lambda pid: f"Эталон #{pid}\n\nтекст поста")
    out = sw._anchors()
    assert "Эталон #475" in out and "Эталон #456" in out


def test_anchors_first_in_system_prompt(monkeypatch):
    # порядок — часть решения: эталон должен стоять ДО правил, иначе он их не перевешивает
    monkeypatch.setattr(sw, "_anchors", lambda: "ЭТАЛОН-МАРКЕР")
    sys_prompt = sw._system()
    assert sys_prompt.index("ЭТАЛОН-МАРКЕР") < sys_prompt.index("МАНУАЛ РУБРИКИ")
