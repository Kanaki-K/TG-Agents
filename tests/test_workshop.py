"""Тесты гейта правок SKILL.md (core/workshop): защита от path-traversal и парс заголовка."""
import pytest

from core import workshop


@pytest.mark.parametrize("bad", ["../x", "a/b", "a\\b", "..", ""])
def test_agent_dir_rejects_traversal(bad):
    with pytest.raises(ValueError):
        workshop._agent_dir(bad)


def test_agent_dir_unknown_agent():
    with pytest.raises(ValueError):
        workshop._agent_dir("definitely-not-an-agent")


def test_agent_dir_valid_agent():
    d = workshop._agent_dir("creator")  # существует в репо
    assert d.name == "creator"
    assert (d / "SKILL.md").exists()


def test_title_first_nonempty_line():
    assert workshop._title("# Заголовок\nтело") == "Заголовок"
    assert workshop._title("\n\n  Просто строка\nдальше") == "Просто строка"
    assert workshop._title("") == ""
