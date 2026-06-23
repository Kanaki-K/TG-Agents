"""Тесты предохранителей движка: подрезка истории и разбивка длинных сообщений (core/agent_runtime)."""
from core import agent_runtime as ar


def test_trim_history_empty():
    assert ar._trim_history([]) == []


def test_trim_history_drops_leading_non_user():
    # срез не должен начинаться с assistant-хода или tool_result без пары — отбрасываем ведущие
    hist = [
        {"role": "assistant", "content": [{"type": "text", "text": "x"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "r"}]},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    ]
    out = ar._trim_history(hist, keep=12)
    assert out[0] == {"role": "user", "content": "hello"}
    assert len(out) == 2


def test_trim_history_all_invalid_returns_empty():
    hist = [{"role": "assistant", "content": [{"type": "text", "text": "x"}]}]
    assert ar._trim_history(hist) == []


def test_chunks_short_text_single_chunk():
    assert ar._chunks("hello") == ["hello"]


def test_chunks_respects_size_limit():
    text = "\n".join("line%d" % i for i in range(2000))
    chunks = ar._chunks(text, size=200)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    # содержимое не теряется (границы кусков съедают только разделитель-перевод строки)
    assert "".join(c.replace("\n", "") for c in chunks) == text.replace("\n", "")


def test_chunks_hard_splits_overlong_single_line():
    text = "x" * 1000
    chunks = ar._chunks(text, size=100)
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks) == text
