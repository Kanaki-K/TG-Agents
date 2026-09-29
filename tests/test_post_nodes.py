"""Пометка [[УЗЕЛ]] — мост между автором ТГ-поста и дистилляцией в Threads.

Прямая просьба автора дистилляций 10.09.2026: слои должны быть разведены заранее. Тесты держат две
вещи, на которых это ломается: узел не должен попадать в опубликованное тело, и он должен доезжать
до деривации как подсказка."""
from core import published_journal as J

BODY = "Заголовок\n\nТело поста про потерю 110 млн$"
META = "\n\n[[SPLIT]]\nпримечание для владельца\n[[УЗЕЛ]] защита сработала, а деньги ушли\n[[УЗЕЛ]] проверяли подпись, а не смысл"


def test_nodes_are_read_from_meta():
    assert J.nodes_of(BODY + META) == ["защита сработала, а деньги ушли",
                                       "проверяли подпись, а не смысл"]


def test_node_in_the_body_is_ignored():
    """В теле такая строка была бы служебным мусором в опубликованном посте — читаем только мету."""
    assert J.nodes_of("[[УЗЕЛ]] это в теле\n\nтекст") == []


def test_no_meta_no_nodes():
    assert J.nodes_of(BODY) == []


def test_journal_entry_carries_nodes(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "JOURNAL", tmp_path / "journal.jsonl")
    monkeypatch.setattr(J, "LEGACY_JOURNAL", tmp_path / "legacy.jsonl")
    J.record(BODY + META, theme="Liquid", kind="scope")
    entry = J.latest("scope")
    assert entry["nodes"] == ["защита сработала, а деньги ушли", "проверяли подпись, а не смысл"]
    assert "[[УЗЕЛ]]" not in entry["text"]      # в Threads уходит только тело
