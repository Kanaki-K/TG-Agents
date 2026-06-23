"""Тесты Markdown→Telegram-HTML (core/tg_format). Чистые строковые преобразования, без сети."""
from core import tg_format as tf


def test_bold():
    assert tf.to_telegram_html("**hi**") == "<b>hi</b>"


def test_header_to_bold():
    assert tf.to_telegram_html("# Title") == "<b>Title</b>"
    assert tf.to_telegram_html("### Подзаголовок") == "<b>Подзаголовок</b>"


def test_inline_code_escaped_and_protected_from_bold():
    # внутри кода HTML экранируется, а **жирный** НЕ конвертируется
    assert tf.to_telegram_html("`<b>`") == "<code>&lt;b&gt;</code>"
    assert tf.to_telegram_html("`**x**`") == "<code>**x**</code>"


def test_html_escape_outside_code():
    assert tf.to_telegram_html("a < b & c") == "a &lt; b &amp; c"


def test_link():
    assert tf.to_telegram_html("[t](https://x.com)") == '<a href="https://x.com">t</a>'


def test_list_markers():
    assert tf.to_telegram_html("- item") == "• item"
    assert tf.to_telegram_html("* item") == "• item"


def test_strip_markdown():
    assert tf.strip_markdown("**bold**") == "bold"
    assert tf.strip_markdown("# H") == "H"
    assert tf.strip_markdown("- x") == "• x"
    assert tf.strip_markdown("[t](https://x.com)") == "t (https://x.com)"
